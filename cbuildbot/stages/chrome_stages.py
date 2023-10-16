# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the Chrome stages."""

import logging
import os

from chromite.cbuildbot import cbuildbot_alerts
from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import generic_stages
from chromite.lib import constants
from chromite.lib import failures_lib
from chromite.lib import osutils
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
