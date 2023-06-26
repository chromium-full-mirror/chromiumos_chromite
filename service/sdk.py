# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Operations to work with the SDK chroot."""

import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Dict, List, Optional, Tuple

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import binpkg
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib import sdk_builder_lib
from chromite.utils import key_value_store


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


class CreateArguments:
    """Value object to handle the chroot creation arguments."""

    def __init__(
        self,
        replace: bool = False,
        bootstrap: bool = False,
        chroot: Optional["chroot_lib.Chroot"] = None,
        sdk_version: Optional[str] = None,
        skip_chroot_upgrade: Optional[bool] = False,
    ):
        """Create arguments init.

        Args:
            replace: Whether an existing chroot should be deleted.
            bootstrap: Whether to build the SDK from source.
            chroot: chroot_lib.Chroot object representing the paths for the
                chroot to create.
            sdk_version: Specific SDK version to use, e.g. 2022.01.20.073008.
            skip_chroot_upgrade: Whether to skip any chroot upgrades (using
                the --skip-chroot-upgrade arg to cros_sdk).
        """
        self.replace = replace
        self.bootstrap = bootstrap
        self.chroot = chroot or chroot_lib.Chroot()
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

        if self.chroot.cache_dir:
            args.extend(["--cache-dir", self.chroot.cache_dir])

        args.extend(["--chroot", self.chroot.path])
        args.extend(["--out-dir", str(self.chroot.out_path)])

        if self.sdk_version:
            args.extend(["--sdk-version", self.sdk_version])

        if self.skip_chroot_upgrade:
            args.append("--skip-chroot-upgrade")

        return args


class UpdateArguments:
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
    incrementals: bool = False,
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
        incrementals: Clean out the incremental artifacts.
    """
    if not (images or sysroots or tmp or safe or cache or logs or workdirs):
        # Nothing specified to clean.
        return

    cmd = ["cros", "clean", "--debug"]
    if chroot:
        cmd.extend(["--sdk-path", chroot.path])
        cmd.extend(["--out-path", chroot.out_path])
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
    if incrementals:
        cmd.append("--incrementals")

    cros_build_lib.run(cmd)


def Create(arguments: CreateArguments) -> Optional[int]:
    """Create or replace the chroot.

    Args:
        arguments: The various arguments to create a chroot.

    Returns:
        The version of the resulting chroot.
    """
    cros_build_lib.AssertOutsideChroot()

    cmd = [constants.CHROMITE_BIN_DIR / "cros_sdk"]
    cmd.extend(arguments.GetArgList())

    cros_build_lib.run(cmd)

    version = GetChrootVersion(arguments.chroot.path)
    if not arguments.replace:
        # Force replace scenarios. Only needed when we're not already replacing
        # it.
        if not version:
            # Force replace when we can't get a version for a chroot that
            # exists, since something must have gone wrong.
            logging.notice("Replacing broken chroot.")
            arguments.replace = True
            return Create(arguments)
        elif not cros_sdk_lib.IsChrootVersionValid(arguments.chroot.path):
            # Force replace when the version is not valid, i.e. ahead of the
            # chroot version hooks.
            logging.notice("Replacing chroot ahead of current checkout.")
            arguments.replace = True
            return Create(arguments)
        elif not cros_sdk_lib.IsChrootDirValid(arguments.chroot.path):
            # Force replace when the permissions or owner are not correct.
            logging.notice("Replacing chroot with invalid permissions.")
            arguments.replace = True
            return Create(arguments)

    return GetChrootVersion(arguments.chroot.path)


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
    cmd = [constants.CHROMITE_BIN_DIR / "cros_sdk", "--delete"]
    if force:
        cmd.extend(["--force"])
    if chroot:
        cmd.extend(["--chroot", chroot.path])
        cmd.extend(["--out-dir", chroot.out_path])

    cros_build_lib.run(cmd)

    # Remove any images that were built.
    logging.info("Removing images.")
    Clean(chroot, images=True)


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

    cmd = [constants.CROSUTILS_DIR / "update_chroot"]
    cmd.extend(arguments.GetArgList())

    # The sdk update uses splitdebug instead of separatedebug. Make sure
    # separatedebug is disabled and enable splitdebug.
    existing = os.environ.get("FEATURES", "")
    features = " ".join((existing, "-separatedebug splitdebug")).strip()
    extra_env = {"FEATURES": features}

    cros_build_lib.run(cmd, extra_env=extra_env)

    return GetChrootVersion()


def _get_remote_latest_file_value(key: str) -> str:
    """Return a value from the remote latest SDK file on GS://, if it exists.

    Returns:
        The value of the given key in the remote latest file.

    Raises:
        ValueError: If the given key is not found in the file.
    """
    uri = gs.GetGsURL(
        constants.SDK_GS_BUCKET,
        for_gsutil=True,
        suburl="cros-sdk-latest.conf",
    )
    contents = gs.GSContext().Cat(uri).decode()
    contents_dict = key_value_store.LoadData(
        contents, source="remote latest SDK file"
    )
    if key not in contents_dict:
        raise ValueError(
            f"Unable to find key {key} in latest SDK file ({uri}):\n{contents}"
        )
    return contents_dict[key]


def get_latest_version() -> str:
    """Return the latest SDK version according to GS://."""
    return _get_remote_latest_file_value("LATEST_SDK")


def get_latest_uprev_target_version() -> str:
    """Return the latest-built target version for SDK uprevs form GS://."""
    return _get_remote_latest_file_value("LATEST_SDK_UPREV_TARGET")


def _uprev_local_sdk_version_file(
    new_sdk_version: str,
    new_toolchain_tarball_template: str,
) -> bool:
    """Update the local SDK version file (but don't commit the change).

    Args:
        new_sdk_version: The SDK version to update to.
        new_toolchain_tarball_template: The new value for the TC_PATH

    Returns:
        True if changes were made, else False.

    Raises:
        ValueError: If the toolchain tarball template is malformatted.
    """
    if "%(target)s" not in new_toolchain_tarball_template:
        raise ValueError(
            "Toolchain tarball template doesn't contain %(target)s: "
            + new_toolchain_tarball_template
        )
    logging.info(
        "Updating SDK version file (%s)", constants.SDK_VERSION_FILE_FULL_PATH
    )
    return key_value_store.UpdateKeysInLocalFile(
        constants.SDK_VERSION_FILE_FULL_PATH,
        {
            "SDK_LATEST_VERSION": new_sdk_version,
            "TC_PATH": new_toolchain_tarball_template,
        },
    )


def _uprev_local_host_prebuilts_file(
    binhost_gs_bucket: str, target_version: str
) -> bool:
    """Update the local amd64-host prebuilt file (but don't commit the change).

    Args:
        binhost_gs_bucket: The bucket containing prebuilt files (including
            the "gs://" prefix).
        target_version: The prebuilts version to sync to. Typically this is
            identical to an SDK version (ex. "chroot-2023.03.14.159265"), since
            the host prebuilts are typically created during SDK uprevs.

    Returns:
        True if changes were made, else False.
    """
    if not gs.PathIsGs(binhost_gs_bucket):
        raise ValueError(
            "binhost_gs_bucket doesn't look like a gs path: %s"
            % binhost_gs_bucket
        )
    logging.info(
        "Updating amd64-host prebuilt file (%s)",
        constants.HOST_PREBUILT_CONF_FILE_FULL_PATH,
    )
    new_binhost = "%(bucket)s/board/amd64-host/%(version)s/packages/" % {
        "bucket": binhost_gs_bucket.rstrip("/"),
        "version": target_version,
    }
    return key_value_store.UpdateKeyInLocalFile(
        constants.HOST_PREBUILT_CONF_FILE_FULL_PATH,
        "FULL_BINHOST",
        new_binhost,
    )


def uprev_sdk_and_prebuilts(
    binhost_gs_bucket: str, version: str, toolchain_tarball_template: str
) -> List[Path]:
    """Uprev the SDK version and prebuilt conf files on the local filesystem.

    Args:
        binhost_gs_bucket: The bucket to which prebuilts get uploaded, including
            the "gs://" prefix. Example: "gs://chromeos-prebuilt/"
        version: The SDK version to uprev to, which is also the prebuilt version
            to uprev to. Example: "2023.02.12.144623
        toolchain_tarball_template: The new TC_PATH value for the SDK version
            file.

    Returns:
        List of absolute paths to modified files.
    """
    modified_paths = []
    if _uprev_local_sdk_version_file(version, toolchain_tarball_template):
        modified_paths.append(constants.SDK_VERSION_FILE_FULL_PATH)
    if _uprev_local_host_prebuilts_file(binhost_gs_bucket, version):
        modified_paths.append(constants.HOST_PREBUILT_CONF_FILE_FULL_PATH)
    return modified_paths


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
    sdk_path = Path(chroot.full_path("build/amd64-host"))
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
                constants.CHROMITE_BIN_DIR / "upload_prebuilts",
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
            constants.SDK_VERSION_FILE_FULL_PATH,
            sdk_settings,
            report=report,
            dryrun=True,
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
            constants.CHROMITE_BIN_DIR / "upload_prebuilts",
            "--sync-host",
            "--build-path",
            constants.SOURCE_ROOT,
            "--chroot",
            chroot.path,
            "--out-dir",
            chroot.out_path,
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
    extra_env: Optional[Dict[str, str]] = None,
) -> List[common_pb2.Path]:
    """Build cross-compiler toolchain packages for the SDK.

    Args:
        extra_env: Any extra env vars to pass into cros_setup_toolchains.

    Returns:
        List of generated filepaths.
    """
    cros_build_lib.AssertInsideChroot()
    toolchain_dir = os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT)

    def _SetupToolchains(flags: List[str], include_extra_env: bool):
        """Run the cros_setup_toolchains binary."""
        cmd = ["cros_setup_toolchains"] + flags
        cros_build_lib.sudo_run(
            cmd,
            extra_env=extra_env if include_extra_env else None,
        )

    _SetupToolchains(["--nousepkg", "--debug"], True)
    osutils.RmDir(
        toolchain_dir,
        ignore_missing=True,
        sudo=True,
    )
    _SetupToolchains(
        [
            "--debug",
            "--create-packages",
            "--output-dir",
            toolchain_dir,
        ],
        False,
    )
    return [
        common_pb2.Path(
            path=os.path.join(toolchain_dir, filename),
            location=common_pb2.Path.INSIDE,
        )
        for filename in os.listdir(toolchain_dir)
    ]
