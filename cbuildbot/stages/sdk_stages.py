# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing SDK stages."""

import glob
import json
import logging
import os
from pathlib import Path
import re

from chromite.cbuildbot import cbuildbot_alerts
from chromite.cbuildbot import commands
from chromite.cbuildbot import prebuilts
from chromite.cbuildbot.stages import generic_stages
from chromite.lib import binpkg
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import perf_uploader
from chromite.lib import portage_util
from chromite.service import sdk


def SdkPerfPath(buildroot):
    """Return the path to the perf file for sdk stages."""
    return path_util.FromChrootPath(
        os.path.join(os.path.sep, "tmp", "cros-sdk.perf"),
        source_path=buildroot,
    )


def CreateTarball(source_root, tarball_path, exclude_paths=None):
    """Packs |source_root| into |tarball_path|.

    Args:
        source_root: Path to the directory we want to package.
        tarball_path: Path of the tarball that should be created.
        exclude_paths: Subdirectories to exclude.
    """
    # TODO(zbehan): We cannot use xz from the chroot unless it's
    # statically linked.
    extra_args = None
    if exclude_paths is not None:
        extra_args = ["--anchored"]
        extra_args.extend("--exclude=./%s/*" % x for x in exclude_paths)
    # Options for maximum compression.
    extra_env = {"XZ_OPT": "-e9"}
    cros_build_lib.CreateTarball(
        tarball_path,
        source_root,
        sudo=True,
        extra_args=extra_args,
        debug_level=logging.INFO,
        extra_env=extra_env,
    )
    # Make sure the regular user has the permission to read.
    cmd = ["chmod", "a+r", tarball_path]
    cros_build_lib.sudo_run(cmd)


class SDKBuildToolchainsStage(
    generic_stages.BuilderStage, generic_stages.ArchivingStageMixin
):
    """Stage that builds all the cross-compilers we care about"""

    category = constants.PRODUCT_TOOLCHAIN_STAGE

    def PerformStage(self):
        path_resolver = path_util.ChrootPathResolver(
            source_path=self._build_root
        )

        # Build the toolchains first.  Since we're building & installing the
        # compilers, need to run as root.
        self.CrosSetupToolchains(
            ["--nousepkg"], sudo=True, extra_env=self._portage_extra_env
        )

        # Create toolchain packages.
        self.CreateRedistributableToolchains(path_resolver)
        toolchain_path = path_resolver.FromChroot(
            Path("/") / constants.SDK_TOOLCHAINS_OUTPUT
        )
        for files in os.listdir(toolchain_path):
            self.UploadArtifact(
                os.path.join(toolchain_path, files), strict=True, archive=True
            )

    def CrosSetupToolchains(self, cmd_args, **kwargs):
        """Wrapper around cros_setup_toolchains to simplify things."""
        commands.RunBuildScript(
            self._build_root,
            ["cros_setup_toolchains"] + list(cmd_args),
            chromite_cmd=True,
            enter_chroot=True,
            **kwargs,
        )

    def CreateRedistributableToolchains(
        self, path_resolver: path_util.ChrootPathResolver
    ):
        """Create the toolchain packages"""
        osutils.RmDir(
            path_resolver.FromChroot(
                Path("/") / constants.SDK_TOOLCHAINS_OUTPUT
            ),
            ignore_missing=True,
        )

        # We need to run this as root because the tool creates hard links to
        # root owned files and our bots enable security features which disallow
        # that. Specifically, these features cause problems:
        #  /proc/sys/kernel/yama/protected_nonaccess_hardlinks
        #  /proc/sys/fs/protected_hardlinks
        self.CrosSetupToolchains(
            [
                # TODO(crbug.com/917193): Enable debugging for now.
                "--debug",
                "--create-packages",
                "--output-dir",
                os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT),
            ],
            sudo=True,
        )


class SDKPackageStage(
    generic_stages.BuilderStage, generic_stages.ArchivingStageMixin
):
    """Stage that performs preparing and packaging SDK files"""

    category = constants.PRODUCT_TOOLCHAIN_STAGE

    def __init__(self, builder_run, buildstore, version=None, **kwargs):
        self.sdk_version = version
        super().__init__(builder_run, buildstore, **kwargs)

    def PerformStage(self):
        tarball_location = os.path.join(
            self._build_root, constants.SDK_TARBALL_NAME
        )
        board_location = path_util.FromChrootPath(
            "/build/amd64-host", source_path=self._build_root
        )
        manifest_location = tarball_location + ".Manifest"

        # Cleanup etc/make.conf.board_setup for use in SDK.
        self.CleanupMakeConfBoardSetup(board_location)

        # Create a tarball of the latest SDK.
        CreateTarball(
            board_location,
            tarball_location,
            exclude_paths=constants.SDK_PACKAGE_EXCLUDED_PATHS,
        )
        self.UploadArtifact(tarball_location, strict=True, archive=True)

        # Create a package manifest for the tarball.
        self.CreateManifestFromSDK(board_location, manifest_location)

        self.SendPerfValues(tarball_location)

    def CreateManifestFromSDK(self, sdk_path, dest_manifest):
        """Creates a manifest from a given source chroot.

        Args:
            sdk_path: Path to the root of the SDK to describe.
            dest_manifest: Path to the manifest that should be generated.
        """
        logging.info("Generating manifest for new sdk")
        package_data = {}
        for key, version in portage_util.ListInstalledPackages(sdk_path):
            package_data.setdefault(key, []).append((version, {}))
        self._WriteManifest(package_data, dest_manifest)

    def _WriteManifest(self, data, manifest):
        """Encode manifest into a json file."""
        json_input = dict(version=sdk.PACKAGE_MANIFEST_VERSION, packages=data)
        osutils.WriteFile(manifest, json.dumps(json_input))

    def _SendPerfValues(
        self, buildroot, sdk_tarball, buildbot_uri_log, version, platform_name
    ):
        """Generate & upload perf data for the build"""
        perf_path = SdkPerfPath(buildroot)
        test_name = "sdk"
        units = "bytes"

        # Make sure the file doesn't contain previous data.
        osutils.SafeUnlink(perf_path)

        common_kwargs = {
            "higher_is_better": False,
            "graph": "cros-sdk-size",
            "stdio_uri": buildbot_uri_log,
        }

        sdk_size = os.path.getsize(sdk_tarball)
        perf_uploader.OutputPerfValue(
            perf_path, "base", sdk_size, units, **common_kwargs
        )

        for tarball in glob.glob(
            path_util.FromChrootPath(
                os.path.join(
                    os.path.sep,
                    constants.SDK_TOOLCHAINS_OUTPUT,
                    "*.tar.*",
                ),
                source_path=buildroot,
            )
        ):
            name = os.path.basename(tarball).rsplit(".", 2)[0]
            size = os.path.getsize(tarball)
            perf_uploader.OutputPerfValue(
                perf_path, name, size, units, **common_kwargs
            )
            perf_uploader.OutputPerfValue(
                perf_path,
                "base_plus_%s" % name,
                sdk_size + size,
                units,
                **common_kwargs,
            )

        # Due to limitations in the perf dashboard, we have to create an integer
        # based on the current timestamp.  This field only accepts integers, and
        # the perf dashboard accepts this or CrOS+Chrome official versions.
        revision = int(version.replace(".", ""))
        perf_values = perf_uploader.LoadPerfValues(perf_path)
        self._UploadPerfValues(
            perf_values, platform_name, test_name, revision=revision
        )

    def SendPerfValues(self, sdk_tarball):
        """Generate & upload perf data for the build"""
        self._SendPerfValues(
            self._build_root,
            sdk_tarball,
            self.ConstructDashboardURL(),
            self.sdk_version,
            self._run.bot_id,
        )

    def CleanupMakeConfBoardSetup(self, board_location):
        """Cleanup etc/make.conf.board_setup to be usable in the SDK"""
        board_setup = os.path.join(board_location, "etc/make.conf.board_setup")
        lines = osutils.ReadFile(board_setup).splitlines()

        to_remove = re.compile(r"^(ROOT|PKG_CONFIG)=")
        lines = [x for x in lines if not to_remove.match(x)]
        data = "\n".join(lines) + "\n"
        if "/build/" in data:
            logging.error("%s content:\n%s", board_setup, data)
            raise ValueError("/build/ paths must be cleaned from make.conf")
        osutils.WriteFile(board_setup, data, sudo=True)


class SDKTestStage(generic_stages.BuilderStage):
    """Stage that performs testing an SDK created in a previous stage"""

    option_name = "tests"
    category = constants.PRODUCT_TOOLCHAIN_STAGE

    def PerformStage(self):
        new_chroot_dir = "new-sdk-chroot"
        tarball_location = os.path.join(
            self._build_root, constants.SDK_TARBALL_NAME
        )
        new_chroot_args = ["--chroot", new_chroot_dir]
        if self._run.options.chrome_root:
            new_chroot_args += ["--chrome_root", self._run.options.chrome_root]

        # Build a new SDK using the provided tarball.
        chroot_args = new_chroot_args + [
            "--download",
            "--replace",
            "--nousepkg",
            "--url",
            "file://" + tarball_location,
        ]
        cros_build_lib.run(
            ["true"],
            cwd=self._build_root,
            enter_chroot=True,
            chroot_args=chroot_args,
            extra_env=self._portage_extra_env,
        )

        # Inject the toolchain binpkgs from the previous sdk build.  On end user
        # systems, they'd be fetched from the binpkg mirror, but we don't have
        # one set up for this local build.
        pkgdir = os.path.join("var", "lib", "portage", "pkgs")
        old_pkgdir = path_util.FromChrootPath(
            os.path.join(os.path.sep, pkgdir),
            source_path=self._build_root,
        )
        new_pkgdir = os.path.join(self._build_root, new_chroot_dir, pkgdir)
        osutils.SafeMakedirs(new_pkgdir, sudo=True)
        cros_build_lib.sudo_run(
            ["cp", "-r"]
            + glob.glob(os.path.join(old_pkgdir, "*"))
            + [new_pkgdir]
        )

        # Now install those toolchains in the new chroot.  We skip the chroot
        # upgrade below which means we need to install the toolchain manually.
        cmd = [
            "cros_setup_toolchains",
            "--targets=boards",
            "--include-boards=%s" % ",".join(self._boards),
        ]
        commands.RunBuildScript(
            self._build_root,
            cmd,
            chromite_cmd=True,
            enter_chroot=True,
            sudo=True,
            chroot_args=new_chroot_args,
            extra_env=self._portage_extra_env,
        )

        # Build all the boards with the new sdk.
        for board in self._boards:
            cbuildbot_alerts.PrintBuildbotStepText(board)
            commands.SetupBoard(
                self._build_root,
                board,
                usepkg=True,
                chroot_upgrade=False,
                extra_env=self._portage_extra_env,
                chroot_args=new_chroot_args,
            )
            commands.Build(
                self._build_root,
                board,
                build_autotest=True,
                usepkg=False,
                extra_env=self._portage_extra_env,
                chroot_args=new_chroot_args,
                disable_revdep_logic=True,
            )


class SDKUprevStage(generic_stages.BuilderStage):
    """Stage that uprevs SDK version."""

    category = constants.PRODUCT_TOOLCHAIN_STAGE

    def __init__(self, builder_run, buildstore, version=None, **kwargs):
        super().__init__(builder_run, buildstore, **kwargs)
        self._version = version

    def PerformStage(self):
        cbuildbot_alerts.PrintBuildbotStepText(self._version)

        if self._run.config.prebuilts == constants.PUBLIC:
            binhost_conf_dir = constants.PUBLIC_BINHOST_CONF_DIR
        else:
            binhost_conf_dir = constants.PRIVATE_BINHOST_CONF_DIR
        sdk_conf = os.path.join(
            self._build_root, binhost_conf_dir, "host", "sdk_version.conf"
        )

        tc_path_format = prebuilts.GetToolchainSdkUploadFormat(
            self._version,
            prebuilts.GetToolchainSdkPaths(self._build_root)[0][1],
        )
        sdk_settings = {
            "SDK_LATEST_VERSION": self._version,
            "TC_PATH": tc_path_format % {"version": self._version},
        }
        if self._run.options.publish:
            binpkg.UpdateAndSubmitKeyValueFile(
                sdk_conf, sdk_settings, dryrun=self._run.options.debug
            )
        else:
            logging.info(
                "Not updating sdk_version.conf because publishing was disabled."
            )
