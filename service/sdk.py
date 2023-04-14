# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Operations to work with the SDK chroot."""

import json
import logging
import os
import tempfile
from typing import List, Optional, TYPE_CHECKING
import uuid

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import osutils


if TYPE_CHECKING:
    from chromite.lib import chroot_lib


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
        use_image: bool = True,
        chroot_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
        sdk_version: Optional[str] = None,
        skip_chroot_upgrade: Optional[bool] = False,
    ):
        """Create arguments init.

        Args:
          replace: Whether an existing chroot should be deleted.
          bootstrap: Whether to build the SDK from source.
          use_image: Whether to mount the chroot on a loopback image or create it
            directly in a directory.
          chroot_path: Path to where the chroot should be reside.
          cache_dir: Alternative directory to use as a cache for the chroot.
          sdk_version: Specific SDK version to use, e.g. 2022.01.20.073008.
          skip_chroot_upgrade: Whether or not to skip any chroot upgrades (using
            the --skip-chroot-upgrade arg to cros_sdk).
        """
        self.replace = replace
        self.bootstrap = bootstrap
        self.use_image = use_image
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

        if self.use_image:
            args.append("--use-image")
        else:
            args.append("--nouse-image")

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
          toolchain_targets: The list of build targets whose toolchains should be
            updated.
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
        # Force replace scenarios. Only needed when we're not already replacing it.
        if not version:
            # Force replace when we can't get a version for a chroot that exists,
            # since something must have gone wrong.
            logging.notice("Replacing broken chroot.")
            arguments.replace = True
            return Create(arguments)
        elif not cros_sdk_lib.IsChrootVersionValid(arguments.chroot_path):
            # Force replace when the version is not valid, i.e. ahead of the chroot
            # version hooks.
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


def CreateSnapshot(
    chroot: Optional["chroot_lib.Chroot"] = None,
    replace_if_needed: bool = False,
) -> str:
    """Create a logical volume snapshot of a chroot.

    Args:
      chroot: The chroot to perform the operation on.
      replace_if_needed: If True, will replace the existing chroot with a new one
        capable of being mounted as a loopback image if needed.

    Returns:
      The name of the snapshot created.
    """
    _EnsureSnapshottableState(chroot, replace=replace_if_needed)

    snapshot_token = str(uuid.uuid4())
    logging.info("Creating SDK snapshot with token ID: %s", snapshot_token)

    cmd = [
        os.path.join(constants.CHROMITE_BIN_DIR, "cros_sdk"),
        "--snapshot-create",
        snapshot_token,
    ]
    if chroot:
        cmd.extend(["--chroot", chroot.path])

    cros_build_lib.run(cmd)

    return snapshot_token


def RestoreSnapshot(
    snapshot_token: str, chroot: Optional["chroot_lib.Chroot"] = None
) -> None:
    """Restore a logical volume snapshot of a chroot.

    Args:
      snapshot_token: The name of the snapshot to restore. Typically an opaque
        generated name returned from `CreateSnapshot`.
      chroot: The chroot to perform the operation on, or None for the default
        chroot.
    """
    # Unmount to clean up stale processes that may still be in the chroot, in
    # order to prevent 'device busy' errors from umount.
    Unmount(chroot)
    logging.info("Restoring SDK snapshot with ID: %s", snapshot_token)
    cmd = [
        os.path.join(constants.CHROMITE_BIN_DIR, "cros_sdk"),
        "--snapshot-restore",
        snapshot_token,
    ]
    if chroot:
        cmd.extend(["--chroot", chroot.path])

    # '--snapshot-restore' will automatically remount the image after restoring.
    cros_build_lib.run(cmd)


def _EnsureSnapshottableState(
    chroot: Optional["chroot_lib.Chroot"] = None, replace: bool = False
) -> None:
    """Ensures that a chroot is in a capable state to create an LVM snapshot.

    Args:
      chroot: The chroot to perform the operation on, or None for the default
        chroot.
      replace: If true, will replace the existing chroot with a new one capable of
        being mounted as a loopback image if needed.
    """
    cmd = [
        os.path.join(constants.CHROMITE_BIN_DIR, "cros_sdk"),
        "--snapshot-list",
    ]
    if chroot:
        cmd.extend(["--chroot", chroot.path])

    cache_dir = chroot.cache_dir if chroot else None
    chroot_path = chroot.path if chroot else None

    res = cros_build_lib.run(
        cmd, check=False, encoding="utf-8", capture_output=True
    )

    if res.returncode == 0:
        return
    elif "Unable to find VG" in res.stderr and replace:
        logging.warning(
            "SDK was created with nouse-image which does not support "
            "snapshots. Recreating SDK to support snapshots."
        )

        args = CreateArguments(
            replace=True,
            bootstrap=False,
            use_image=True,
            cache_dir=cache_dir,
            chroot_path=chroot_path,
        )

        Create(args)
        return
    else:
        res.check_returncode()


def BuildPrebuilts(chroot: "chroot_lib.Chroot"):
    """Builds the binary packages that comprise the Chromium OS SDK.

    Args:
      chroot: The chroot in which to run the build.
    """
    cros_build_lib.run(
        ["./build_sdk_board"],
        enter_chroot=True,
        extra_env=chroot.env,
        chroot_args=chroot.get_enter_args(),
        check=True,
    )


def CreateBinhostCLs(
    prepend_version: str, version: str, upload_location: str
) -> List[str]:
    """Create CLs that update the binhost to point at uploaded prebuilts.

    The CLs are *not* automatically submitted.

    Args:
      prepend_version: String to prepend to version.
      version: The SDK version string.
      upload_location: prefix of the upload path (e.g. 'gs://bucket')

    Returns:
      List of URIs of the created CLs.
    """
    with tempfile.NamedTemporaryFile() as report:
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
                report.name,
            ],
            check=True,
        )
        return json.load(report.file)["created_cls"]


def UploadPrebuiltPackages(
    chroot: "chroot_lib.Chroot",
    prepend_version: str,
    version: str,
    upload_location: str,
):
    """Uploads prebuilt packages (such as built by BuildSdkPrebuilts).

    Args:
      chroot: The chroot that contains the packages to upload.
      build_path: Location of the sources.
      prepend_version: String to prepend to version.
      version: The SDK version string.
      upload_location: prefix of the upload path (e.g. 'gs://bucket')
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
