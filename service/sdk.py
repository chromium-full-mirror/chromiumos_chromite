# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Operations to work with the SDK chroot."""

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import binpkg
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib import sdk_builder_lib
from chromite.utils import key_value_store


if TYPE_CHECKING:
    from chromite.lib import chroot_lib


# Version of the Manifest file being generated for SDK artifacts. Should be
# incremented for major format changes.
PACKAGE_MANIFEST_VERSION = "1"


class Error(Exception):
    """Base module error."""


class UnmountError(Error):
    """An error raised when unmount fails."""

    def __init__(
        self,
        path: str,
        cmd_error: cros_build_lib.RunCommandError,
        fs_debug: cros_sdk_lib.FileSystemDebugInfo,
    ):
        super().__init__(path, cmd_error, fs_debug)
        self.path = path
        self.cmd_error = cmd_error
        self.fs_debug = fs_debug

    def __str__(self):
        return (
            f"Umount failed: {self.cmd_error.stdout}.\n"
            f"fuser output={self.fs_debug.fuser}\n"
            f"lsof output={self.fs_debug.lsof}\n"
            f"ps output={self.fs_debug.ps}\n"
        )


class CreateArguments(object):
    """Value object to handle the chroot creation arguments."""

    def __init__(
        self,
        replace: bool = False,
        bootstrap: bool = False,
        chroot_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        sdk_version: Optional[str] = None,
        skip_chroot_upgrade: Optional[bool] = False,
    ):
        """Create arguments init.

        Args:
            replace: Whether an existing chroot should be deleted.
            bootstrap: Whether to build the SDK from source.
            chroot_path: Path to where the chroot should reside.
            cache_dir: Alternative directory to use as a cache for the chroot.
            sdk_version: Specific SDK version to use, e.g. 2022.01.20.073008.
            skip_chroot_upgrade: Whether to skip any chroot upgrades (using
                the --skip-chroot-upgrade arg to cros_sdk).
        """
        self.replace = replace
        self.bootstrap = bootstrap
        self.chroot_path = chroot_path
        self.cache_dir = cache_dir
        self.sdk_version = sdk_version
        self.skip_chroot_upgrade = skip_chroot_upgrade

    def GetArgList(self) -> List[str]:
        """Get the list of the corresponding command line arguments.

        Returns:
            The list of the corresponding command line arguments.
        """
        args = []

        if self.replace:
            args.append("--replace")
        else:
            args.append("--create")

        if self.bootstrap:
            args.append("--bootstrap")

        if self.cache_dir:
            args.extend(["--cache-dir", self.cache_dir])

        if self.chroot_path:
            args.extend(["--chroot", self.chroot_path])

        if self.sdk_version:
            args.extend(["--sdk-version", self.sdk_version])

        if self.skip_chroot_upgrade:
            args.append("--skip-chroot-upgrade")

        return args


class UpdateArguments(object):
    """Value object to handle the update arguments."""

    def __init__(
        self,
        build_source: bool = False,
        toolchain_targets: Optional[List[str]] = None,
        toolchain_changed: bool = False,
    ):
        """Update arguments init.

        Args:
            build_source: Whether to build the source or use prebuilts.
            toolchain_targets: The list of build targets whose toolchains should
                be updated.
            toolchain_changed: Whether a toolchain change has occurred. Implies
                build_source.
        """
        self.build_source = build_source or toolchain_changed
        self.toolchain_targets = toolchain_targets

    def GetArgList(self) -> List[str]:
        """Get the list of the corresponding command line arguments.

        Returns:
            The list of the corresponding command line arguments.
        """
        args = []

        if self.build_source:
            args.append("--nousepkg")
        elif self.toolchain_targets:
            args.extend(
                ["--toolchain_boards", ",".join(self.toolchain_targets)]
            )

        return args


def Clean(
    chroot: Optional["chroot_lib.Chroot"],
    images: bool = False,
    sysroots: bool = False,
    tmp: bool = False,
    safe: bool = False,
    cache: bool = False,
    logs: bool = False,
    workdirs: bool = False,
) -> None:
    """Clean the chroot.

    See:
        cros clean -h

    Args:
        chroot: The chroot to clean.
        images: Remove all built images.
        sysroots: Remove all of the sysroots.
        tmp: Clean the tmp/ directory.
        safe: Clean all produced artifacts.
        cache: Clean the shared cache.
        logs: Clean up various logs.
        workdirs: Clean out various package build work directories.
    """
    if not (images or sysroots or tmp or safe or cache or logs or workdirs):
        # Nothing specified to clean.
        return

    cmd = ["cros", "clean", "--debug"]
    if chroot:
        cmd.extend(["--sdk-path", chroot.path])
    if safe:
        cmd.append("--safe")
    if images:
        cmd.append("--images")
    if sysroots:
        cmd.append("--sysroots")
    if tmp:
        cmd.append("--chroot-tmp")
    if cache:
        cmd.append("--cache")
    if logs:
        cmd.append("--logs")
    if workdirs:
        cmd.append("--workdirs")

    cros_build_lib.run(cmd)


def Create(arguments: CreateArguments) -> Optional[int]:
    """Create or replace the chroot.

    Args:
        arguments: The various arguments to create a chroot.

    Returns:
        The version of the resulting chroot.
    """
    cros_build_lib.AssertOutsideChroot()

    cmd = [os.path.join(constants.CHROMITE_BIN_DIR, "cros_sdk")]
    cmd.extend(arguments.GetArgList())

    cros_build_lib.run(cmd)

    version = GetChrootVersion(arguments.chroot_path)
    if not arguments.replace:
        # Force replace scenarios. Only needed when we're not already replacing
        # it.
        if not version:
            # Force replace when we can't get a version for a chroot that
            # exists, since something must have gone wrong.
            logging.notice("Replacing broken chroot.")
            arguments.replace = True
            return Create(arguments)
        elif not cros_sdk_lib.IsChrootVersionValid(arguments.chroot_path):
            # Force replace when the version is not valid, i.e. ahead of the
            # chroot version hooks.
            logging.notice("Replacing chroot ahead of current checkout.")
            arguments.replace = True
            return Create(arguments)
        elif not cros_sdk_lib.IsChrootDirValid(arguments.chroot_path):
            # Force replace when the permissions or owner are not correct.
            logging.notice("Replacing chroot with invalid permissions.")
            arguments.replace = True
            return Create(arguments)

    return GetChrootVersion(arguments.chroot_path)


def Delete(
    chroot: Optional["chroot_lib.Chroot"] = None, force: bool = False
) -> None:
    """Delete the chroot.

    Args:
        chroot: The chroot being deleted, or None for the default chroot.
        force: Whether to apply the --force option.
    """
    # Delete the chroot itself.
    logging.info("Removing the SDK.")
    cmd = [os.path.join(constants.CHROMITE_BIN_DIR, "cros_sdk"), "--delete"]
    if force:
        cmd.extend(["--force"])
    if chroot:
        cmd.extend(["--chroot", chroot.path])

    cros_build_lib.run(cmd)

    # Remove any images that were built.
    logging.info("Removing images.")
    Clean(chroot, images=True)


def Unmount(chroot: Optional["chroot_lib.Chroot"] = None) -> None:
    """Unmount the chroot.

    Args:
        chroot: The chroot being unmounted, or None for the default chroot.
    """
    logging.info("Unmounting the chroot.")
    cmd = [os.path.join(constants.CHROMITE_BIN_DIR, "cros_sdk"), "--unmount"]
    if chroot:
        cmd.extend(["--chroot", chroot.path])

    cros_build_lib.run(cmd)


def UnmountPath(path: str) -> None:
    """Unmount the specified path.

    Args:
        path: The path being unmounted.
    """
    logging.info("Unmounting path %s", path)
    try:
        osutils.UmountTree(path)
    except cros_build_lib.RunCommandError as e:
        fs_debug = cros_sdk_lib.GetFileSystemDebug(path, run_ps=True)
        raise UnmountError(path, e, fs_debug)


def GetChrootVersion(chroot_path: Optional[str] = None) -> Optional[int]:
    """Get the chroot version.

    Args:
        chroot_path: The chroot path, or None for the default chroot path.

    Returns:
        The version of the chroot if the chroot is valid, else None.
    """
    if chroot_path:
        path = chroot_path
    elif cros_build_lib.IsInsideChroot():
        path = None
    else:
        path = constants.DEFAULT_CHROOT_PATH

    return cros_sdk_lib.GetChrootVersion(path)


def Update(arguments: UpdateArguments) -> Optional[int]:
    """Update the chroot.

    Args:
        arguments: The various arguments for updating a chroot.

    Returns:
        The version of the chroot after the update, or None if the chroot is
        invalid.
    """
    # TODO: This should be able to be run either in or out of the chroot.
    cros_build_lib.AssertInsideChroot()

    cmd = [os.path.join(constants.CROSUTILS_DIR, "update_chroot")]
    cmd.extend(arguments.GetArgList())

    # The sdk update uses splitdebug instead of separatedebug. Make sure
    # separatedebug is disabled and enable splitdebug.
    existing = os.environ.get("FEATURES", "")
    features = " ".join((existing, "-separatedebug splitdebug")).strip()
    extra_env = {"FEATURES": features}

    cros_build_lib.run(cmd, extra_env=extra_env)

    return GetChrootVersion()


def GetLatestVersion() -> str:
    """Return the latest SDK version according to GS://."""
    uri = gs.GetGsURL(
        constants.SDK_GS_BUCKET,
        for_gsutil=True,
        suburl="cros-sdk-latest.conf",
    )
    contents = gs.GSContext().Cat(uri).decode()
    contents_dict = key_value_store.LoadData(
        contents, source="remote latest SDK file"
    )
    if "LATEST_SDK" not in contents_dict:
        raise ValueError(
            f"Failed to parse latest SDK file ({uri}) contents:\n{contents}"
        )
    return contents_dict["LATEST_SDK"]


def UprevSdkAndPrebuilts(
    chroot: "chroot_lib.Chroot",
    binhost_gs_bucket: str,
    version: str,
) -> List[Path]:
    """Uprev the SDK version and prebuilt conf files on the local filesystem.

    Returns:
        List of modified filepaths.
    """
    raise NotImplementedError()


def BuildPrebuilts(chroot: "chroot_lib.Chroot", board: str = ""):
    """Builds the binary packages that compose the Chromium OS SDK.

    Args:
        chroot: The chroot in which to run the build.
        board: The name of the SDK build target to build packages for.
    """
    cmd = ["./build_sdk_board"]
    if board:
        cmd.append(f"--board={board}")
    cros_build_lib.run(
        cmd,
        enter_chroot=True,
        extra_env=chroot.env,
        chroot_args=chroot.get_enter_args(),
        check=True,
    )


def BuildSdkTarball(chroot: "chroot_lib.Chroot") -> Path:
    """Create a tarball previously built (e.g. by BuildPrebuilts) SDK.

    Args:
        chroot: The chroot that contains the built SDK.

    Returns:
        The path at which the SDK tarball has been created.
    """
    sdk_path = Path(chroot.path) / "build/amd64-host"
    return sdk_builder_lib.BuildSdkTarball(sdk_path)


def CreateManifestFromSdk(sdk_path: Path, dest_dir: Path) -> Path:
    """Create a manifest file showing the ebuilds in an SDK.

    Args:
        sdk_path: The path to the full SDK. (Not a tarball!)
        dest_dir: The directory in which the manifest file should be created.

    Returns:
        The filepath of the generated manifest file.
    """
    dest_manifest = dest_dir / f"{constants.SDK_TARBALL_NAME}.Manifest"
    # package_data: {"category/package" : [("version", {}), ...]}
    package_data: Dict[str, List[Tuple[str, Dict]]] = {}
    for package in portage_util.PortageDB(sdk_path).InstalledPackages():
        key = f"{package.category}/{package.package}"
        package_data.setdefault(key, []).append((package.version, {}))
    json_input = dict(version=PACKAGE_MANIFEST_VERSION, packages=package_data)
    osutils.WriteFile(dest_manifest, json.dumps(json_input))
    return dest_manifest


def CreateBinhostCLs(
    prepend_version: str,
    version: str,
    upload_location: str,
    sdk_tarball_template: str,
) -> List[str]:
    """Create CLs that update the binhost to point at uploaded prebuilts.

    The CLs are *not* automatically submitted.

    Args:
        prepend_version: String to prepend to version.
        version: The SDK version string.
        upload_location: Prefix of the upload path (e.g. 'gs://bucket')
        sdk_tarball_template: Template for the path to the SDK tarball.
            This will be stored in SDK_VERSION_FILE, and looks something
            like '2022/12/%(target)s-2022.12.11.185558.tar.xz'.

    Returns:
        List of created CLs (in str:num format).
    """
    with tempfile.NamedTemporaryFile() as report_file:
        cros_build_lib.run(
            [
                os.path.join(constants.CHROMITE_BIN_DIR, "upload_prebuilts"),
                "--skip-upload",
                "--dry-run",
                "--sync-host",
                "--git-sync",
                "--key",
                "FULL_BINHOST",
                "--build-path",
                constants.SOURCE_ROOT,
                "--board",
                "amd64-host",
                "--set-version",
                version,
                "--prepend-version",
                prepend_version,
                "--upload",
                upload_location,
                "--binhost-conf-dir",
                constants.PUBLIC_BINHOST_CONF_DIR,
                "--output",
                report_file.name,
            ],
            check=True,
        )
        report = json.load(report_file.file)
        sdk_settings = {
            "SDK_LATEST_VERSION": version,
            "TC_PATH": sdk_tarball_template,
        }
        # Note: dryrun=True prevents the change from being automatically
        # submitted. We only want to create the change, not submit it.
        binpkg.UpdateAndSubmitKeyValueFile(
            constants.SDK_VERSION_FILE, sdk_settings, report=report, dryrun=True
        )
        return report["created_cls"]


def UploadPrebuiltPackages(
    chroot: "chroot_lib.Chroot",
    prepend_version: str,
    version: str,
    upload_location: str,
):
    """Uploads prebuilt packages (such as built by BuildPrebuilts).

    Args:
        chroot: The chroot that contains the packages to upload.
        prepend_version: String to prepend to version.
        version: The SDK version string.
        upload_location: Prefix of the upload path (e.g. 'gs://bucket')
    """
    cros_build_lib.run(
        [
            os.path.join(constants.CHROMITE_BIN_DIR, "upload_prebuilts"),
            "--sync-host",
            "--build-path",
            constants.SOURCE_ROOT,
            "--chroot",
            chroot.path,
            "--board",
            "amd64-host",
            "--set-version",
            version,
            "--prepend-version",
            prepend_version,
            "--upload",
            upload_location,
            "--binhost-conf-dir",
            os.path.join(
                constants.SOURCE_ROOT,
                "src/third_party/chromiumos-overlay/chromeos/binhost",
            ),
        ],
        check=True,
    )


def BuildSdkToolchain(
    chroot: "chroot_lib.Chroot",
    extra_env: Optional[Dict[str, str]] = None,
) -> List[common_pb2.Path]:
    """Build cross-compiler toolchain packages for the SDK.

    Args:
        chroot: The chroot in which the build is being run.
        extra_env: Any extra env vars to pass into cros_setup_toolchains.

    Returns:
        List of generated filepaths.
    """
    toolchain_dir = os.path.join(chroot.path, constants.SDK_TOOLCHAINS_OUTPUT)

    def _SetupToolchains(flags: List[str], include_extra_env: bool):
        """Run the cros_setup_toolchains binary."""
        cmd = ["cros_setup_toolchains"] + flags
        cros_build_lib.sudo_run(
            cmd,
            extra_env=extra_env if include_extra_env else None,
            enter_chroot=True,
        )

    _SetupToolchains(["--nousepkg"], True)
    osutils.RmDir(
        os.path.join(chroot.path, constants.SDK_TOOLCHAINS_OUTPUT),
        ignore_missing=True,
        sudo=True,
    )
    _SetupToolchains(
        [
            "--debug",
            "--create-packages",
            "--output-dir",
            os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT),
        ],
        False,
    )
    return [
        common_pb2.Path(
            path=os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT, filename),
            location=common_pb2.Path.INSIDE,
        )
        for filename in os.listdir(toolchain_dir)
    ]
