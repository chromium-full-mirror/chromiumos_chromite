# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the Chrome stages."""

import glob
import logging
import multiprocessing
import os

from chromite.cbuildbot import cbuildbot_alerts
from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import artifact_stages
from chromite.cbuildbot.stages import generic_stages
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import failures_lib
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import path_util
from chromite.lib import portage_util
from chromite.lib import results_lib


MASK_CHANGES_ERROR_SNIPPET = "The following mask changes are necessary"
CHROMEPIN_MASK_PATH = os.path.join(
    constants.SOURCE_ROOT,
    constants.CHROMIUMOS_OVERLAY_DIR,
    "profiles",
    "default",
    "linux",
    "package.mask",
    "chromepin",
)


class SyncChromeStage(
    generic_stages.BuilderStage, generic_stages.ArchivingStageMixin
):
    """Stage that syncs Chrome sources if needed."""

    option_name = "managed_chrome"
    category = constants.PRODUCT_CHROME_STAGE

    def __init__(self, builder_run, buildstore, **kwargs):
        super().__init__(builder_run, buildstore, **kwargs)
        # PerformStage() will fill this out for us.
        # TODO(mtennant): Replace with a run param.
        self.chrome_version = None

    def HandleSkip(self):
        """Set run.attrs.chrome_version to chrome version in buildroot now."""
        self._run.attrs.chrome_version = self._run.DetermineChromeVersion()
        logging.debug(
            "Existing chrome version is %s.", self._run.attrs.chrome_version
        )
        self._WriteChromeVersionToMetadata()
        super().HandleSkip()

    def _GetChromeVersionFromMetadata(self):
        """Return Chrome version from metadata; None if is does not exist."""
        version_dict = self._run.attrs.metadata.GetDict().get("version")
        return None if not version_dict else version_dict.get("chrome")

    @failures_lib.SetFailureType(failures_lib.InfrastructureFailure)
    def PerformStage(self):
        chrome_atom_to_build = None
        if self._chrome_rev:
            if (
                self._chrome_rev == constants.CHROME_REV_SPEC
                and self._run.options.chrome_version
            ):
                self.chrome_version = self._run.options.chrome_version
                logging.info(
                    "Using chrome version from options.chrome_version: %s",
                    self.chrome_version,
                )
            else:
                self.chrome_version = self._GetChromeVersionFromMetadata()
                if self.chrome_version:
                    logging.info(
                        "Using chrome version from the metadata dictionary: %s",
                        self.chrome_version,
                    )

            # Perform chrome uprev.
            try:
                chrome_atom_to_build = commands.MarkChromeAsStable(
                    self._build_root,
                    self._run.manifest_branch,
                    self._chrome_rev,
                    self._boards,
                    chrome_version=self.chrome_version,
                )
            except commands.ChromeIsPinnedUprevError as e:
                # If uprev failed due to a chrome pin, record that failure (so
                # that the build ultimately fails) but try again without the
                # pin, to allow the slave to test the newer chrome anyway).
                chrome_atom_to_build = e.new_chrome_atom
                if chrome_atom_to_build:
                    results_lib.Results.Record(self.name, e)
                    cbuildbot_alerts.PrintBuildbotStepFailure()
                    logging.error(
                        "Chrome is pinned. Unpinning chrome and continuing "
                        "build for chrome atom %s. This stage will be marked "
                        "as failed to prevent an uprev.",
                        chrome_atom_to_build,
                    )
                    logging.info(
                        "Deleting pin file at %s and proceeding.",
                        CHROMEPIN_MASK_PATH,
                    )
                    osutils.SafeUnlink(CHROMEPIN_MASK_PATH)
                else:
                    raise

        kwargs = {}
        if self._chrome_rev == constants.CHROME_REV_SPEC:
            kwargs["revision"] = self.chrome_version
            cbuildbot_alerts.PrintBuildbotStepText(
                "revision %s" % kwargs["revision"]
            )
        else:
            if not self.chrome_version:
                self.chrome_version = self._run.DetermineChromeVersion()

            kwargs["tag"] = self.chrome_version
            cbuildbot_alerts.PrintBuildbotStepText("tag %s" % kwargs["tag"])

        useflags = self._run.config.useflags
        git_cache_dir = (
            self._run.options.chrome_preload_dir
            or self._run.options.git_cache_dir
        )
        commands.SyncChrome(
            self._build_root,
            self._run.options.chrome_root,
            useflags,
            git_cache_dir=git_cache_dir,
            **kwargs,
        )

    def _WriteChromeVersionToMetadata(self):
        """Write chrome version to metadata and upload partial json file."""
        self._run.attrs.metadata.UpdateKeyDictWithDict(
            "version", {"chrome": self._run.attrs.chrome_version}
        )
        self.UploadMetadata(filename=constants.PARTIAL_METADATA_JSON)

    def Finish(self):
        """Provide chrome_version to the rest of the run."""
        # Even if the stage failed, a None value for chrome_version still
        # means something.  In other words, this stage tried to run.
        self._run.attrs.chrome_version = self.chrome_version
        self._WriteChromeVersionToMetadata()
        super().Finish()


class SimpleChromeArtifactsStage(
    generic_stages.BoardSpecificBuilderStage, generic_stages.ArchivingStageMixin
):
    """Archive Simple Chrome artifacts."""

    option_name = "chrome_sdk"
    config_name = "chrome_sdk"
    category = constants.PRODUCT_CHROME_STAGE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._upload_queue = multiprocessing.Queue()
        self._pkg_dir = os.path.join(
            self._build_root,
            constants.DEFAULT_CHROOT_DIR,
            "build",
            self._current_board,
            portage_util.VDB_PATH,
        )

    def _BuildAndArchiveChromeSysroot(self):
        """Generate and upload sysroot for building Chrome."""
        assert self.archive_path.startswith(self._build_root)
        extra_env = {}
        if self._run.config.useflags:
            extra_env["USE"] = " ".join(self._run.config.useflags)
        in_chroot_path = path_util.ToChrootPath(self.archive_path)
        cmd = [
            "cros_generate_sysroot",
            "--out-dir",
            in_chroot_path,
            "--board",
            self._current_board,
            "--deps-only",
            "--package",
            constants.CHROME_CP,
        ]
        cros_build_lib.run(
            cmd, cwd=self._build_root, enter_chroot=True, extra_env=extra_env
        )
        self._upload_queue.put([constants.CHROME_SYSROOT_TAR])

    def _ArchiveChromeEbuildEnv(self):
        """Generate and upload Chrome ebuild environment."""
        files = glob.glob(
            os.path.join(self._pkg_dir, constants.CHROME_CP) + "-*"
        )
        if not files:
            raise artifact_stages.NothingToArchiveException(
                "Failed to find package %s" % constants.CHROME_CP
            )
        if len(files) > 1:
            cbuildbot_alerts.PrintBuildbotStepWarnings()
            logging.warning(
                "Expected one package for %s, found %d",
                constants.CHROME_CP,
                len(files),
            )

        chrome_dir = sorted(files)[-1]
        env_bzip = os.path.join(chrome_dir, "environment.bz2")
        with osutils.TempDir(prefix="chrome-sdk-stage") as tempdir:
            # Convert from bzip2 to tar format.
            bzip2 = cros_build_lib.FindCompressor(
                cros_build_lib.CompressionType.BZIP2
            )
            cros_build_lib.run(
                [bzip2, "-d", env_bzip, "-c"],
                stdout=os.path.join(tempdir, constants.CHROME_ENV_FILE),
            )
            env_tar = os.path.join(self.archive_path, constants.CHROME_ENV_TAR)
            cros_build_lib.CreateTarball(env_tar, tempdir)
            self._upload_queue.put([os.path.basename(env_tar)])

    def _GenerateAndUploadMetadata(self):
        self.UploadMetadata(
            upload_queue=self._upload_queue,
            filename=constants.PARTIAL_METADATA_JSON,
        )

    def PerformStage(self):
        steps = [
            self._BuildAndArchiveChromeSysroot,
            self._ArchiveChromeEbuildEnv,
            self._GenerateAndUploadMetadata,
        ]
        with self.ArtifactUploader(self._upload_queue, archive=False):
            parallel.RunParallelSteps(steps)
