# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Operations to work with the SDK chroot."""

import dataclasses
import json
import logging
import os
from pathlib import Path
import re
import tempfile
from typing import Dict, List, Optional, Tuple, Union

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import binpkg
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib import sdk_builder_lib
from chromite.lib import sysroot_lib
from chromite.lib.parser import package_info
from chromite.service import binhost
from chromite.utils import gs_urls_util
from chromite.utils import key_value_store


# Version of the Manifest file being generated for SDK artifacts. Should be
# incremented for major format changes.
PACKAGE_MANIFEST_VERSION = "1"


class Error(Exception):
    """Base module error."""


class SdkCreateError(Error):
    """Error creating the SDK."""


class UnmountError(Error):
    """An error raised when unmount fails."""

    def __init__(
        self,
        path: str,
        cmd_error: cros_build_lib.RunCommandError,
        fs_debug: cros_sdk_lib.FileSystemDebugInfo,
    ) -> None:
        super().__init__(path, cmd_error, fs_debug)
        self.path = path
        self.cmd_error = cmd_error
        self.fs_debug = fs_debug

    def __str__(self) -> str:
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
        bootstrap: bool = False,
        chroot: Optional["chroot_lib.Chroot"] = None,
        sdk_version: Optional[str] = None,
        force: bool = False,
        ccache_disable: bool = False,
        no_delete_out_dir: bool = False,
    ) -> None:
        """Create arguments init.

        Args:
            bootstrap: Use the SDK bootstrap version.
            chroot: chroot_lib.Chroot object representing the paths for the
                chroot to create.
            sdk_version: Specific SDK version to use, e.g. 2022.01.20.073008.
            force: Force delete of the current SDK chroot when replacing, even
                if obtaining the write lock fails.
            ccache_disable: Whether ccache should be disabled after chroot
                creation.
            no_delete_out_dir: If True, `out` directory will be preserved.
        """
        self.chroot = chroot or chroot_lib.Chroot()
        if sdk_version:
            self.sdk_version = sdk_version
        else:
            version_conf = cros_sdk_lib.SdkVersionConfig.load()
            self.sdk_version = version_conf.get_default_version(
                bootstrap=bootstrap
            )
        self.force = force
        self.ccache_disable = ccache_disable
        self.no_delete_out_dir = no_delete_out_dir

    def GetEntryArgList(self) -> List[str]:
        """Get the list of command line arguments to simply enter the chroot.

        Note that these are a subset of `GetArgList`.
        """
        args = [
            "--chroot",
            self.chroot.path,
            "--out-dir",
            str(self.chroot.out_path),
            # Builders want to exercise a read-only SDK, even if developers may
            # not, for ease of use. Rather than plumb this through every
            # builder API call, we make this sticky at creation time.
            "--read-only",
            "--read-only-sticky",
        ]
        if self.chroot.cache_dir:
            args.extend(["--cache-dir", self.chroot.cache_dir])

        args.extend(["--sdk-version", self.sdk_version])

        return args

    def GetArgList(self) -> List[str]:
        """Get the list of the corresponding command line arguments.

        Returns:
            The list of the corresponding command line arguments.
        """
        args = ["--replace"]

        if self.no_delete_out_dir:
            args.append("--no-delete-out-dir")
        else:
            args.append("--delete-out-dir")
        if self.force:
            args.append("--force")

        args.extend(self.GetEntryArgList())

        return args


class UpdateArguments:
    """Value object to handle the update arguments."""

    def __init__(
        self,
        root: Union[str, os.PathLike] = "/",
        build_source: bool = False,
        toolchain_targets: Optional[List[str]] = None,
        toolchain_changed: bool = False,
        jobs: Optional[int] = None,
        backtrack: Optional[int] = None,
        update_toolchain: bool = False,
        use_snapshot_binhosts: bool = False,
        log_installed_packages: bool = False,
    ) -> None:
        """Update arguments init.

        Args:
            root: The general root to operate on.  Mostly for testing.
            build_source: Whether to build the source or use prebuilts.
            toolchain_targets: The list of build targets whose toolchains should
                be updated.
            toolchain_changed: Whether a toolchain change has occurred. Implies
                build_source and update_toolchain.
            jobs: Max number of simultaneous packages to build.
            backtrack: emerge --backtrack value.
            update_toolchain: Update the toolchain?
            use_snapshot_binhosts: If True, use the host packages binhosts
                generated by snapshot builders.
            log_installed_packages: Log the packages and their versions
                installed in the SDK prior to updating it.
        """
        self.root = Path(root)
        self.build_source = build_source or toolchain_changed
        self.toolchain_targets = toolchain_targets
        self.jobs = jobs
        self.backtrack = backtrack
        self.update_toolchain = update_toolchain or toolchain_changed
        self.use_snapshot_binhosts = use_snapshot_binhosts
        self.log_installed_packages = log_installed_packages

    def GetArgList(self) -> List[str]:
        """Get the list of the corresponding command line arguments.

        Returns:
            The list of the corresponding command line arguments.
        """
        args = []

        if self.build_source:
            args.append("--nousepkg")
        else:
            args.append("--usepkg")

        if self.jobs is not None:
            args.append(f"--jobs={self.jobs}")

        if self.backtrack is not None:
            args.append(f"--backtrack={self.backtrack}")

        return args


@dataclasses.dataclass
class UpdateResult:
    """Result value object."""

    return_code: int
    version: Optional[int] = None
    failed_pkgs: List[package_info.PackageInfo] = dataclasses.field(
        default_factory=list
    )

    @property
    def success(self):
        return self.return_code == 0 and not self.failed_pkgs


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

    cros_sdk = constants.CHROMITE_BIN_DIR / "cros_sdk"
    try:
        cros_build_lib.run([cros_sdk] + arguments.GetArgList())
    except cros_build_lib.RunCommandError as e:
        raise SdkCreateError(f"Error creating the SDK: {str(e)}") from e

    disable_arg = "true" if arguments.ccache_disable else "false"
    ccache_cmd = [cros_sdk]
    ccache_cmd.extend(arguments.GetEntryArgList())
    ccache_cmd.extend(
        (
            "--",
            "sudo",
            "CCACHE_DIR=/var/cache/distfiles/ccache",
            "ccache",
            f"--set-config=disable={disable_arg}",
        )
    )
    if cros_build_lib.run(ccache_cmd, check=False).returncode:
        logging.warning(
            "ccache disable=%s command failed; ignoring", disable_arg
        )

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


def Update(arguments: UpdateArguments) -> UpdateResult:
    """Update the chroot.

    Args:
        arguments: The various arguments for updating a chroot.

    Returns:
        The version of the chroot after the update, or None if the chroot is
        invalid.
    """
    # TODO: This should be able to be run either in or out of the chroot.
    cros_build_lib.AssertInsideChroot()

    logging.info("Updating chroot in %s.", arguments.root)

    if arguments.log_installed_packages:
        pkgs = portage_util.get_installed_packages()
        logging.debug("Pre-update Installed Packages:\n%s", "\n".join(pkgs))

    with cros_sdk_lib.ChrootReadWrite():
        return _Update(arguments)


@osutils.rotate_log_file(portage_util.get_die_hook_status_file())
def _Update(arguments: UpdateArguments) -> UpdateResult:
    cros_build_lib.ClearShadowLocks(arguments.root)

    cros_sdk_lib.RunChrootVersionHooks()

    portage_util.RegenDependencyCache(jobs=arguments.jobs)

    build_target = build_target_lib.BuildTarget(constants.CHROOT_BUILDER_BOARD)
    sysroot = sysroot_lib.Sysroot(arguments.root)
    sysroot.InstallMakeConfSdk(build_target)

    if os.environ.get("CROS_CLEAN_OUTDATED_PKGS") != "0":
        cop_command = [
            constants.CHROMITE_BIN_DIR / "cros",
            "clean-outdated-pkgs",
            "--host",
        ]
        try:
            cros_build_lib.run(cop_command)
        except Exception as e:
            cmd_as_str = " ".join(cop_command)
            logging.error(
                'While cleaning outdated packages with "%s": %s', cmd_as_str, e
            )
            raise e

    if arguments.update_toolchain:
        logging.info("Updating cross-compilers")
        cmd = [
            constants.CHROMITE_BIN_DIR / "cros_setup_toolchains",
        ]
        if arguments.toolchain_targets:
            cmd += [f"--include-boards={','.join(arguments.toolchain_targets)}"]

        # This should really only be skipped while bootstrapping.
        if arguments.build_source:
            cmd += ["--nousepkg"]
        cros_build_lib.sudo_run(cmd)

    cmd = [
        constants.CHROMITE_SHELL_DIR / "update_chroot.sh",
        "--script-is-run-only-by-chromite-and-not-users",
    ]
    cmd.extend(arguments.GetArgList())

    # The sdk update uses splitdebug instead of separatedebug. Make sure
    # separatedebug is disabled and enable splitdebug.
    existing = os.environ.get("FEATURES", "")
    features = " ".join((existing, "-separatedebug splitdebug")).strip()
    extra_env = {"FEATURES": features}

    # We require USE be passed as SDK_USE in the environment.  Users setting USE
    # likely intend the flags to apply to the board, not the SDK.
    extra_env["USE"] = os.environ.get("SDK_USE", "")

    binhosts = portage_util.PortageqEnvvar("PORTAGE_BINHOST")
    if arguments.use_snapshot_binhosts:
        portage_binhosts = binhost.GetHostBinhosts()
        if portage_binhosts:
            binhosts = " ".join(portage_binhosts)
            extra_env["PORTAGE_BINHOST"] = binhosts
    logging.info("PORTAGE_BINHOST: %s", binhosts)

    result = cros_build_lib.run(cmd, extra_env=extra_env, check=False)
    failed_pkgs = portage_util.ParseDieHookStatusFile()
    ret = UpdateResult(result.returncode, GetChrootVersion(), failed_pkgs)

    # Automatically discard all CONFIG_PROTECT'ed files. Those that are
    # protected should not be overwritten until the variable is changed.
    # Autodiscard is option "-9" followed by the "YES" confirmation.
    cros_build_lib.sudo_run(["etc-update", "--automode", "-9"], input="YES\n")

    # If the user still has old perl modules installed, update them.
    cros_build_lib.run(
        [constants.CROSUTILS_DIR / "build_library" / "perl_rebuild.sh"]
    )

    # Generate /usr/bin/remote_toolchain_inputs file for Reclient used by Chrome
    # for distributed builds. go/rbe/dev/x/reclient
    result = cros_build_lib.run(["generate_reclient_inputs"], check=False)
    if result.returncode:
        ret.return_code = result.returncode

    return ret


def _get_remote_latest_file_value(key: str) -> str:
    """Return a value from the remote latest SDK file on GS://, if it exists.

    Returns:
        The value of the given key in the remote latest file.

    Raises:
        ValueError: If the given key is not found in the file.
    """
    uri = cros_sdk_lib.get_sdk_latest_conf_file_url(for_gsutil=True)
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


def _uprev_local_sdk_version_file(
    new_sdk_version: str,
    new_toolchain_tarball_template: str,
    new_sdk_gs_bucket: Optional[str] = None,
) -> bool:
    """Update the local SDK version file (but don't commit the change).

    Args:
        new_sdk_version: The new value for SDK_LATEST_VERSION.
        new_toolchain_tarball_template: The new value for TC_PATH.
        new_sdk_gs_bucket: The new value for SDK_BUCKET. If None, don't modify.
            (But the empty string is a meaningful value!) This may either
            include or exclude the "gs://" prefix.
            Examples: "gs://my-bucket", "my-bucket".
            If the given bucket is equal to the default SDK bucket, then instead
            the empty string will be written to the file so that Chromite can
            continue to use the default, whatever it may be.

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
    new_values = {
        "SDK_LATEST_VERSION": new_sdk_version,
        "TC_PATH": new_toolchain_tarball_template,
    }
    if new_sdk_gs_bucket is not None:
        new_sdk_gs_bucket = gs_urls_util.extract_gs_bucket(new_sdk_gs_bucket)
        if new_sdk_gs_bucket == constants.SDK_GS_BUCKET:
            new_sdk_gs_bucket = ""
        new_values["SDK_BUCKET"] = new_sdk_gs_bucket
    logging.info(
        "Updating SDK version file (%s)", constants.SDK_VERSION_FILE_FULL_PATH
    )
    return key_value_store.UpdateKeysInLocalFile(
        constants.SDK_VERSION_FILE_FULL_PATH, new_values
    )


def _uprev_local_host_prebuilts_files(
    binhost_gs_bucket: str, binhost_version: str
) -> List[Path]:
    """Update the local amd64-host prebuilt files (but don't commit changes).

    Args:
        binhost_gs_bucket: The bucket containing prebuilt files. This may either
            include or exclude the "gs://" prefix.
            Examples: "gs://chromeos-prebuilt", "chromeos-prebuilt".
        binhost_version: The binhost version to sync to. Typically this
            corresponds directly to an SDK version, since host prebuilts are
            created during SDK uprevs: for example, if the SDK version were
            "2023.03.14.159265", then the binhost version would normally be
            "chroot-2023.03.14.159265".

    Returns:
        A list of files that were actually modified, if any.
    """
    bucket = gs_urls_util.extract_gs_bucket(binhost_gs_bucket)
    modified_paths: List[Path] = []
    for conf_path, new_binhost_value in (
        (
            constants.HOST_PREBUILT_CONF_FILE_FULL_PATH,
            f"gs://{bucket}/board/amd64-host/{binhost_version}/packages/",
        ),
        (
            constants.MAKE_CONF_AMD64_HOST_FILE_FULL_PATH,
            f"gs://{bucket}/host/amd64/amd64-host/{binhost_version}/packages/",
        ),
    ):
        logging.info("Updating amd64-host prebuilt file (%s)", conf_path)
        if key_value_store.UpdateKeyInLocalFile(
            conf_path,
            "FULL_BINHOST",
            new_binhost_value,
        ):
            modified_paths.append(conf_path)
    return modified_paths


def _find_newest_stable_ebuild(
    in_dir: Path,
) -> Tuple[Path, package_info.PackageInfo]:
    """Find the ebuild in `in_dir` with the newest version.

    This skips 9999 ebuilds.

    Raises:
        ValueError if the given directory contains no non-9999 ebuilds, or if
        the ebuilds in the directory could not be parsed.
    """
    ebuilds = (
        (x, package_info.parse(x))
        for x in in_dir.glob("*.ebuild")
        if not x.name.endswith("-9999.ebuild")
    )
    return max(ebuilds, key=lambda x: x[1])


def _generate_updated_virtual_contents(
    virtual_path: Path,
    host_package_info: package_info.PackageInfo,
) -> Optional[str]:
    """Generates an updated virtual ebuild given the host package info.

    Toolchain virtuals track the version of the package they represent in a
    comment in the virtual package, e.g.,

    ```
    # Corresponding package version: dev-lang/rust-1.81.0-r16
    ```

    This function extracts that info from the virtual's ebuild & compares
    host_package_dir to it. If there's no change, no update is necessary.

    Returns:
        The contents of a new virtual ebuild as a string, or None if there's no
        change to make to the virtual ebuild.
    """
    virtual_contents = virtual_path.read_text(encoding="utf-8")
    package_version_re = re.compile(
        r"^# Corresponding package version:\s*(\S.*)$", re.MULTILINE
    )
    match = package_version_re.search(virtual_contents)
    if not match:
        raise ValueError(
            f"Could not find match to {package_version_re} in {virtual_path}"
        )

    recorded_package = match.group(1)
    logging.info("Recorded package in %s is %s", virtual_path, recorded_package)
    current_package = host_package_info.cpvr
    if current_package == recorded_package:
        return None

    return "".join(
        (
            virtual_contents[: match.start(1)],
            current_package,
            virtual_contents[match.end(1) :],
        )
    )


def uprev_toolchain_virtuals(
    chromiumos_overlay: Path = constants.SOURCE_ROOT
    / constants.CHROMIUMOS_OVERLAY_DIR,
) -> List[Path]:
    """Uprev virtual packages to match their in-tree versions."""
    # List of host package -> virtual package to keep in sync.
    virtuals_to_sync = [
        (
            chromiumos_overlay / "dev-lang/rust",
            chromiumos_overlay / "virtual/rust",
        )
    ]

    updated_files = []
    for host_package_dir, virtual_package_dir in virtuals_to_sync:
        _, host_info = _find_newest_stable_ebuild(host_package_dir)
        virtual_path, virtual_info = _find_newest_stable_ebuild(
            virtual_package_dir
        )

        new_virtual_contents = _generate_updated_virtual_contents(
            virtual_path, host_info
        )

        if not new_virtual_contents:
            logging.info(
                "No need to uprev %s; no new updates to its host path.",
                virtual_path,
            )
            continue

        logging.info(
            "Max version for %s is now %s, updating virtual package...",
            host_package_dir,
            host_info.version,
        )

        # For convenience, try to keep the virtual version equal to the package
        # version (this causes revision to decrease on version upgrades).
        # If doing so wouldn't result in an upgrade, just bump the revision.
        new_virtual_info = max(
            virtual_info.with_version(
                host_info.version,
                host_info.revision,
            ),
            virtual_info.revision_bump(),
        )

        new_virtual_path = virtual_path.parent / new_virtual_info.ebuild
        new_virtual_path.write_text(new_virtual_contents, encoding="utf-8")
        virtual_path.unlink()
        updated_files.append(new_virtual_path)
    return updated_files


def uprev_sdk_and_prebuilts(
    sdk_version: str,
    toolchain_tarball_template: str,
    binhost_gs_bucket: str,
    sdk_gs_bucket: Optional[str] = None,
) -> List[Path]:
    """Uprev the SDK version and prebuilt conf files on the local filesystem.

    Args:
        sdk_version: The SDK version to uprev to. Example: "2023.03.14.159265".
        toolchain_tarball_template: The new TC_PATH value for the SDK version
            file.
        binhost_gs_bucket: The bucket to which prebuilts were uploaded. This may
            either include or exclude the "gs://" prefix.
            Examples: "gs://chromeos-prebuilt", "chromeos-prebuilt".
        sdk_gs_bucket: The bucket to which the SDK and toolchains get uploaded.
            This may either include or exclude the "gs://" prefix.
            Examples: "gs://chromiumos-sdk", "chromiumos-sdk".
            Only required if the artifacts were uploaded to somewhere besides
            the usual bucket (chromiumos-sdk).

    Returns:
        List of absolute paths to modified files.
    """
    modified_paths = []
    if _uprev_local_sdk_version_file(
        sdk_version,
        toolchain_tarball_template,
        new_sdk_gs_bucket=sdk_gs_bucket,
    ):
        modified_paths.append(constants.SDK_VERSION_FILE_FULL_PATH)
    binhost_version = f"chroot-{sdk_version}"
    modified_paths.extend(
        _uprev_local_host_prebuilts_files(binhost_gs_bucket, binhost_version)
    )
    return modified_paths


def BuildPrebuilts(
    chroot: chroot_lib.Chroot, board: str = ""
) -> Tuple[Path, Path]:
    """Builds the binary packages that compose the ChromiumOS SDK.

    Args:
        chroot: The chroot in which to run the build.
        board: The name of the SDK build target to build packages for.

    Returns:
        A tuple (host_prebuilts_dir, target_prebuilts_dir), where each is an
        absolute path INSIDE the chroot to the directory containing prebuilts
        for the given board (or for the default SDK board).

    Raises:
        FileNotFoundError: If either of the expected return paths is not found
            after running `build_sdk_board`.
    """
    cmd = [chroot.chroot_path(constants.CHROMITE_SHELL_DIR / "build_sdk_board")]
    if board:
        cmd.append(f"--board={board}")

    # --no-read-only: build_sdk_board updates various SDK build cache files
    # which otherwise tend to be read-only.
    # --no-update: We expect the caller already called SdkService/Create with
    # the desired version (bootstrap version) and don't want to auto-update.
    chroot.run(cmd, check=True, chroot_args=["--no-read-only", "--no-update"])

    host_prebuilts_dir = Path("/var/lib/portage/pkgs")
    target_prebuilts_dir = (
        Path("/build") / (board or constants.CHROOT_BUILDER_BOARD) / "packages"
    )
    for path in (host_prebuilts_dir, target_prebuilts_dir):
        if not chroot.has_path(path):
            raise FileNotFoundError(path)
    return (host_prebuilts_dir, target_prebuilts_dir)


def BuildSdkTarball(chroot: "chroot_lib.Chroot", sdk_version: str) -> Path:
    """Create a tarball of a previously built (e.g. by BuildPrebuilts) SDK.

    Args:
        chroot: The chroot that contains the built SDK.
        sdk_version: The version to be included as BUILD_ID in /etc/os-release.

    Returns:
        The path at which the SDK tarball has been created.
    """
    sdk_path = Path(chroot.full_path("build/amd64-host"))
    return sdk_builder_lib.BuildSdkTarball(sdk_path, sdk_version)


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
) -> None:
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
            "--upload-board-tarball",
            "--prepackaged-tarball",
            os.path.join(constants.SOURCE_ROOT, constants.SDK_TARBALL_NAME),
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
            # upload_prebuilts updates cros-latest-sdk.conf by default, but
            # we only want to upload the prebuilts here, so turn it off.
            "--no-sync-remote-latest-sdk-file",
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

    def _SetupToolchains(flags: List[str], include_extra_env: bool) -> None:
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
