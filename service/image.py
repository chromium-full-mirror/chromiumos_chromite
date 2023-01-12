# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The Image API is the entry point for image functionality."""

import errno
import glob
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Iterable, List, NamedTuple, Optional, Union

from chromite.lib import build_target_lib
from chromite.lib import chromeos_version
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import dlc_lib
from chromite.lib import image_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import portage_util
from chromite.lib import sysroot_lib
from chromite.lib.parser import package_info


PARALLEL_EMERGE_STATUS_FILE_NAME = "status_file"

_IMAGE_TYPE_DESCRIPTION = {
    constants.BASE_IMAGE_BIN: "Non-developer Chromium OS",
    constants.DEV_IMAGE_BIN: "Developer",
    constants.TEST_IMAGE_BIN: "Test",
    constants.FACTORY_IMAGE_BIN: "Chromium OS Factory install shim",
}


class Error(Exception):
    """Base module error."""


class InvalidArgumentError(Error, ValueError):
    """Invalid argument values."""


class MissingImageError(Error):
    """An image that was expected to exist was not found."""


class ImageToVmError(Error):
    """Error converting the image to a vm."""


class BuildConfig(NamedTuple):
    """Named tuple to hold the build configuration options.

    Attributes:
        builder_path: The value to which the builder path lsb key should be
            set, the build_name installed on DUT during hwtest.
        disk_layout: The disk layout type.
        enable_rootfs_verification: Whether the rootfs verification is enabled.
        replace: Whether to replace existing output if any exists.
        version: The version string to use for the image.
        build_attempt: The build_attempt number to pass to build_image.
        symlink: Symlink name (defaults to "latest").
        output_dir_suffix: String to append to the image build directory.
        adjust_partition: Adjustments to apply to partition table
            (LABEL:[+-=]SIZE) e.g. ROOT-A:+1G
        boot_args: Additional boot arguments to pass to the commandline.
        enable_bootcache: Enable bootloaders to use boot cache.
        output_root: Directory in which to place image result directories.
        build_root: Directory in which to compose the image, before copying it
            to output_root.
        enable_serial: Enable serial port for printks. Example values: ttyS0
        kernel_loglevel: The loglevel to add to the kernel command line.
        jobs: Number of packages to process in parallel at maximum.
        base_is_recovery: Copy the base image to recovery_image.bin.
    """

    builder_path: Optional[str] = None
    disk_layout: Optional[str] = None
    enable_rootfs_verification: bool = True
    replace: bool = False
    version: Optional[str] = None
    build_attempt: int = 1
    symlink: str = "latest"
    output_dir_suffix: Optional[str] = None
    adjust_partition: Optional[str] = None
    boot_args: str = "noinitrd"
    enable_bootcache: bool = False
    output_root: Union[str, os.PathLike] = (
        Path(constants.DEFAULT_BUILD_ROOT) / "images"
    )
    build_root: Union[str, os.PathLike] = (
        Path(constants.DEFAULT_BUILD_ROOT) / "images"
    )
    enable_serial: Optional[str] = None
    kernel_loglevel: int = 7
    jobs: int = os.cpu_count()
    base_is_recovery: bool = False


# TODO(b/232566937): Remove the argument generation function, once the
# build_image.sh is removed.
def GetBuildImageCommand(
    config: BuildConfig, image_names: List[str], board: str
) -> List[Union[str, os.PathLike]]:
    """Get the build_image command for the configuration.

    Args:
        config: BuildConfig to use to generate the command.
        image_names: A set of image names that need to be built.
        board: The board for which the image to be built.

    Returns:
        List with build_image command with arguments.
    """
    cmd = [
        Path(constants.CROSUTILS_DIR) / "build_image.sh",
        "--script-is-run-only-by-chromite-and-not-users",
        "--board",
        board,
    ]

    _config = config._asdict()
    if constants.FACTORY_IMAGE_BIN in image_names:
        _config["boot_args"] += " cros_factory_install"
        _config["enable_bootcache"] = False

    if _config["builder_path"]:
        cmd.extend(["--builder_path", _config["builder_path"]])
    if not _config["enable_rootfs_verification"]:
        cmd.append("--noenable_rootfs_verification")
    if _config["adjust_partition"]:
        cmd.extend(["--adjust_part", _config["adjust_partition"]])
    if _config["enable_bootcache"]:
        cmd.append("--enable_bootcache")
    if _config["enable_serial"]:
        cmd.extend(["--enable_serial", _config["enable_serial"]])
    cmd.extend(
        [
            "--disk_layout",
            _config["disk_layout"] if _config["disk_layout"] else "default",
        ]
    )
    cmd.extend(["--boot_args", _config["boot_args"]])
    cmd.extend(["--loglevel", f"{_config['kernel_loglevel']}"])
    cmd.extend(["--jobs", f"{_config['jobs']}"])

    cmd.extend(image_names)
    return cmd


class BuildResult(object):
    """Class to record and report build image results."""

    def __init__(self, image_types: List[str]):
        """Init method.

        Args:
            image_types: A list of image names that were requested to be built.
        """
        self._unbuilt_image_types = image_types
        self.images = {}
        self.return_code = None
        self._failed_packages = []
        self.output_dir = None

    @property
    def failed_packages(self) -> List[package_info.PackageInfo]:
        """Get the failed packages."""
        return self._failed_packages

    @failed_packages.setter
    def failed_packages(self, packages: Union[Iterable[str], None]):
        """Set the failed packages."""
        self._failed_packages = [package_info.parse(x) for x in packages or []]

    @property
    def all_built(self) -> bool:
        """Check that all of the images that were meant to be built were built."""
        return not self._unbuilt_image_types

    @property
    def build_run(self) -> bool:
        """Check if build images has been run."""
        return self.return_code is not None

    @property
    def run_error(self) -> bool:
        """Check if an error occurred during the build.

        True iff build images ran and returned a non-zero return code.
        """
        return bool(self.return_code)

    @property
    def run_success(self) -> bool:
        """Check if the build was successful.

        True when the build ran, returned a zero return code, and no failed packages
        were parsed.
        """
        return self.return_code == 0 and not self.failed_packages

    def add_image(self, image_type: str, image_path: Path):
        """Add an image to the result.

        Record the image path by the image name, and remove the image type from the
        un-built image list.
        """
        if image_path and image_path.exists():
            self.images[image_type] = image_path
            logging.debug("Added %s image path %s", image_type, image_path)
            if image_type in self._unbuilt_image_types:
                self._unbuilt_image_types.remove(image_type)
                logging.debug("Removed unbuilt type %s", image_type)
            else:
                logging.warning("Unexpected Image Type %s", image_type)
        else:
            logging.error(
                "%s image path does not exist: %s", image_type, image_path
            )


def Build(
    board: str,
    images: List[str],
    config: Optional[BuildConfig] = None,
    extra_env: Optional[dict] = None,
) -> BuildResult:
    """Build an image.

    Args:
        board: The board name.
        images: The image types to build.
        config: The build configuration options.
        extra_env: Environment variables to set for build_image.

    Returns:
        BuildResult
    """
    cros_build_lib.AssertInsideChroot()

    if not board:
        raise InvalidArgumentError("A build target name is required.")

    build_result = BuildResult(images[:])
    if not images:
        return build_result

    config = config or BuildConfig()
    try:
        image_names = image_lib.GetImagesToBuild(images)
    except ValueError:
        logging.error("Invalid image types requested: %s", " ".join(images))
        build_result.return_code = errno.EINVAL
        return build_result
    logging.info("The following images will be built %s", " ".join(image_names))

    version_info = chromeos_version.VersionInfo(
        version_file=Path(constants.SOURCE_ROOT) / constants.VERSION_FILE
    )
    cmd = GetBuildImageCommand(config, image_names, board)

    cros_build_lib.ClearShadowLocks(
        build_target_lib.get_default_sysroot_path(board)
    )

    try:
        build_dir, output_dir, image_dir = image_lib.CreateBuildDir(
            config.build_root,
            config.output_root,
            version_info.chrome_branch,
            config.version or version_info.VersionStringWithDateTime(),
            board,
            config.symlink,
            config.replace,
            config.build_attempt,
            config.output_dir_suffix,
        )
    except FileExistsError:
        build_result.return_code = errno.EEXIST
        return build_result
    build_result.output_dir = output_dir

    extra_env_local = image_lib.GetBuildImageEnvvars(
        image_names, board, version_info, build_dir, output_dir, extra_env
    )

    with osutils.TempDir() as tempdir:
        status_file = os.path.join(tempdir, PARALLEL_EMERGE_STATUS_FILE_NAME)
        extra_env_local[
            constants.PARALLEL_EMERGE_STATUS_FILE_ENVVAR
        ] = status_file
        result = cros_build_lib.run(
            cmd, enter_chroot=True, check=False, extra_env=extra_env_local
        )
        build_result.return_code = result.returncode
        try:
            content = osutils.ReadFile(status_file).strip()
        except IOError:
            # No file means no packages.
            pass
        else:
            build_result.failed_packages = content.split() if content else None

    if build_result.return_code != 0:
        return build_result

    # Move the completed image to the output_root.
    osutils.MoveDirContents(
        build_dir, output_dir, remove_from_dir=True, allow_nonempty=True
    )

    # TODO(rchandrasekar): move build_dlc to a module that we can import.
    # Copy DLC images to the output_root directory.
    dlc_dir = output_dir / "dlc"
    dlc_cmd = [
        "build_dlc",
        "--sysroot",
        build_target_lib.get_default_sysroot_path(board),
        "--install-root-dir",
        dlc_dir,
        "--board",
        board,
    ]
    result = cros_build_lib.run(dlc_cmd, enter_chroot=True, check=False)
    if result.returncode:
        logging.warning("Copying DLC images to %s failed.", dlc_dir)

    logging.info("Done. Image(s) created in %s\n", output_dir)

    # Save the path to each image that was built.
    for image_type in images:
        filename = constants.IMAGE_TYPE_TO_NAME[image_type]
        image_path = (image_dir / filename).resolve()
        logging.debug("%s Resolved Image Path: %s", image_type, image_path)
        build_result.add_image(image_type, image_path)

        if image_type is constants.IMAGE_TYPE_RECOVERY:
            continue
        # Get the image path relative to the CWD.
        image_path = os.path.relpath(image_path)
        msg = (
            f"{_IMAGE_TYPE_DESCRIPTION[filename]} image created as {filename}\n"
            "To copy the image to a USB key, use:\n"
            f"  cros flash usb:// {image_path}\n"
            "To flash the image to a Chrome OS device, use:\n"
            f"  cros flash YOUR_DEVICE_IP {image_path}\n"
            "Note that the device must be accessible over the network.\n"
            "A base image will not work in this mode, but a test or dev image"
            " will.\n"
        )
        if any(
            filename == x
            for x in [constants.DEV_IMAGE_BIN, constants.TEST_IMAGE_BIN]
        ):
            msg += (
                "To run the image in a virtual machine, use:\n"
                f"  cros_vm --start --image-path={image_path} --board={board}\n"
            )
        logging.info(msg)

    return build_result


def _GetResultAndAddImage(
    board: str, cmd: list, image_path: Path = None
) -> BuildResult:
    """Add an image to the BuildResult.

    Args:
        board: The board name.
        cmd: An array of command-line arguments.
        image_path: The chrooted path to the image.

    Returns:
        BuildResult
    """
    build_result = BuildResult([constants.IMAGE_TYPE_RECOVERY])
    result = cros_build_lib.run(cmd, enter_chroot=True, check=False)
    build_result.return_code = result.returncode

    if result.returncode:
        return build_result

    image_name = constants.IMAGE_TYPE_TO_NAME[constants.IMAGE_TYPE_RECOVERY]
    if image_path:
        recovery_image = image_path.parent / image_name
    else:
        image_dir = Path(image_lib.GetLatestImageLink(board))
        image_path = image_dir / image_name
        recovery_image = image_path.resolve()

    if recovery_image.exists():
        build_result.add_image(constants.IMAGE_TYPE_RECOVERY, recovery_image)

    return build_result


def CopyBaseToRecovery(board: str, image_path: Path) -> BuildResult:
    """Copy the first base image to recovery_image.bin.

    For build targets that do not support a recovery image: the base image gets
    copied to "recovery_image.bin" so images are available in the Chromebook
    Recovery Utility, GoldenEye and other locations.

    Args:
        board: The board name.
        image_path: The chrooted path to the base image.

    Returns:
        BuildResult
    """
    image_name = constants.IMAGE_TYPE_TO_NAME[constants.IMAGE_TYPE_RECOVERY]
    recovery_image_path = image_path.parent / image_name
    cmd = ["cp", image_path, recovery_image_path]
    return _GetResultAndAddImage(board, cmd, recovery_image_path)


def BuildRecoveryImage(
    board: str, image_path: Optional[Path] = None
) -> BuildResult:
    """Build a recovery image.

    This must be done after a base image has been created.

    Args:
        board: The board name.
        image_path: The chrooted path to the image, defaults to
            chromiums_image.bin.

    Returns:
        BuildResult
    """
    if not board:
        raise InvalidArgumentError("board is required.")

    if cros_build_lib.IsInsideChroot():
        cmd = [
            os.path.join(constants.CROSUTILS_DIR, "mod_image_for_recovery.sh")
        ]
    else:
        cmd = ["./mod_image_for_recovery.sh"]

    cmd.extend(["--board", board])
    if image_path:
        cmd.extend(["--image", str(image_path)])

    return _GetResultAndAddImage(board, cmd, image_path)


def CreateVm(
    board: str,
    disk_layout: Optional[str] = None,
    is_test: bool = False,
    chroot: Optional["chroot_lib.Chroot"] = None,
    image_dir: Optional[str] = None,
) -> str:
    """Create a VM from an image.

    Args:
        board: The board for which the VM is being created.
        disk_layout: The disk layout type.
        is_test: Whether it is a test image.
        chroot: The chroot where the image lives.
        image_dir: The built image directory.

    Returns:
        str: Path to the created VM .bin file.
    """
    assert board
    cmd = ["./image_to_vm.sh", "--board", board]

    if is_test:
        cmd.append("--test_image")

    if disk_layout:
        cmd.extend(["--disk_layout", disk_layout])

    if image_dir:
        if chroot:
            inside_image_dir = chroot.chroot_path(image_dir)
        else:
            inside_image_dir = path_util.ToChrootPath(image_dir)
        cmd.extend(["--from", inside_image_dir])

    chroot_args = None
    if chroot and cros_build_lib.IsOutsideChroot():
        chroot_args = chroot.get_enter_args()

    result = cros_build_lib.run(
        cmd, check=False, enter_chroot=True, chroot_args=chroot_args
    )

    if result.returncode:
        # Error running the command. Unfortunately we can't be much more helpful
        # than this right now.
        raise ImageToVmError(
            "Unable to convert the image to a VM. "
            "Consult the logs to determine the problem."
        )

    vm_path = os.path.join(
        image_dir or image_lib.GetLatestImageLink(board), constants.VM_IMAGE_BIN
    )
    return os.path.realpath(vm_path)


def CreateGuestVm(
    board: str,
    is_test: bool = False,
    chroot: chroot_lib.Chroot = None,
    image_dir: str = None,
) -> str:
    """Convert an existing image into a guest VM image.

    Args:
        board: The name of the board to convert.
        is_test: Flag to create a test guest VM image.
        chroot: The chroot where the cros image lives.
        image_dir: The directory containing the built images.

    Returns:
        Path to the created guest VM folder.
    """
    assert board

    cmd = [os.path.join(constants.TERMINA_TOOLS_DIR, "termina_build_image.py")]

    if image_dir:
        if chroot:
            image_dir = chroot.chroot_path(image_dir)
        else:
            image_dir = path_util.ToChrootPath(image_dir)
    else:
        image_dir = image_lib.GetLatestImageLink(board, force_chroot=True)

    image_file = (
        constants.TEST_IMAGE_BIN if is_test else constants.BASE_IMAGE_BIN
    )
    image_path = os.path.join(image_dir, image_file)

    output_dir = (
        constants.TEST_GUEST_VM_DIR if is_test else constants.BASE_GUEST_VM_DIR
    )
    output_path = os.path.join(image_dir, output_dir)

    cmd.append(image_path)
    cmd.append(output_path)

    chroot_args = None
    if chroot and cros_build_lib.IsOutsideChroot():
        chroot_args = chroot.get_enter_args()

    result = cros_build_lib.sudo_run(
        cmd, check=False, enter_chroot=True, chroot_args=chroot_args
    )

    if result.returncode:
        # Error running the command. Unfortunately we can't be much more helpful
        # than this right now.
        raise ImageToVmError(
            "Unable to convert the image to a Guest VM using"
            "termina_build_image.py."
            "Consult the logs to determine the problem."
        )

    return os.path.realpath(output_path)


def copy_dlc_image(base_path: str, output_dir: str) -> List[str]:
    """Copy DLC images from base_path to output_dir.

    Args:
        base_path: Base path wherein DLC images are expected to be.
        output_dir: Folder destination for DLC images folder.

    Returns:
      A list of folder paths after move or None if the source path doesn't exist
    """
    ret = []
    for (dlc_build_dir, dlc_dir) in (
        (dlc_lib.DLC_BUILD_DIR, dlc_lib.DLC_DIR),
        (dlc_lib.DLC_BUILD_DIR_SCALED, dlc_lib.DLC_DIR_SCALED),
    ):
        dlc_source_path = os.path.join(base_path, dlc_build_dir)
        if not os.path.exists(dlc_source_path):
            continue

        dlc_dest_path = os.path.join(output_dir, dlc_dir)
        os.mkdir(dlc_dest_path)

        ret.append(dlc_dest_path)

        # Only archive DLC images, all other uncompressed files/data should not be
        # uploaded into archives.
        dlc_re = (
            f"({dlc_lib.DLC_ID_RE}/{dlc_lib.DLC_PACKAGE}/{dlc_lib.DLC_IMAGE})"
        )
        pat = f"/{dlc_build_dir}/{dlc_re}$"
        for path in osutils.DirectoryIterator(dlc_source_path):
            if not path.is_file():
                continue
            m = re.search(pat, str(path))
            if m:
                img_path = os.path.join(
                    dlc_dest_path,
                    m.group(1),
                )
                os.makedirs(os.path.dirname(img_path))
                shutil.copyfile(path, img_path)

    # Empty list returns `None`.
    return ret or None


def copy_license_credits(
    board: str, output_dir: str, symlink: Optional[str] = None
) -> List[str]:
    """Copies license_credits.html from image build dir to output_dir.

    Args:
        board: The board name.
        output_dir: Folder destination for license_credits.html.
        symlink: Symlink name to use instead of "latest".

    Returns:
        The output path or None if the source path doesn't exist.
    """
    filename = "license_credits.html"
    license_credits_source_path = os.path.join(
        image_lib.GetLatestImageLink(board, pointer=symlink), filename
    )
    if not os.path.exists(license_credits_source_path):
        return None

    license_credits_dest_path = os.path.join(output_dir, filename)
    shutil.copyfile(license_credits_source_path, license_credits_dest_path)
    return license_credits_dest_path


def Test(board: str, result_directory: str, image_dir: str = None) -> bool:
    """Run tests on an already built image.

    Currently this is just running test_image.

    Args:
        board: The board name.
        result_directory: Root directory where the results should be stored
            relative to the chroot.
        image_dir: The path to the image. Uses the board's default image
        build path when not provided.

    Returns:
        True if all tests passed, False otherwise.
    """
    if not board:
        raise InvalidArgumentError("Board is required.")
    if not result_directory:
        raise InvalidArgumentError("Result directory required.")

    if not image_dir:
        # We can build the path to the latest image directory.
        image_dir = image_lib.GetLatestImageLink(board, force_chroot=True)
    elif not cros_build_lib.IsInsideChroot() and os.path.exists(image_dir):
        # Outside chroot with outside chroot path--we need to convert it.
        image_dir = path_util.ToChrootPath(image_dir)

    cmd = [
        os.path.join(
            constants.CHROOT_SOURCE_ROOT,
            constants.CHROMITE_BIN_SUBDIR,
            "test_image",
        ),
        "--board",
        board,
        "--test_results_root",
        result_directory,
        image_dir,
    ]

    result = cros_build_lib.sudo_run(cmd, enter_chroot=True, check=False)

    return result.returncode == 0


def create_factory_image_zip(
    chroot: chroot_lib.Chroot,
    sysroot_class: sysroot_lib.Sysroot,
    factory_shim_dir: Path,
    version: str,
    output_dir: str,
) -> Union[str, None]:
    """Build factory_image.zip in archive_dir.

    Args:
        chroot: The chroot class used for these artifacts.
        sysroot_class: The sysroot where the original environment archive
            can be found.
        factory_shim_dir: Directory containing factory shim.
        version: if not None, version to include in factory_image.zip
        output_dir: Directory to store factory_image.zip.

    Returns:
        The path to the zipfile if it could be created, else None.
    """
    filename = "factory_image.zip"

    zipfile = os.path.join(output_dir, filename)
    cmd = ["zip", "-r", zipfile]

    if not factory_shim_dir or not factory_shim_dir.exists():
        logging.error(
            "create_factory_image_zip: %s not found", factory_shim_dir
        )
        return None
    files = [
        "*factory_install*.bin",
        "*partition*",
        os.path.join("netboot", "*"),
    ]
    cmd_files = []
    for file in files:
        cmd_files.extend(
            ["--include", os.path.join(factory_shim_dir.name, file)]
        )
    # factory_shim_dir may be a symlink. We can not use '-y' here.
    cros_build_lib.run(
        cmd + [factory_shim_dir.name] + cmd_files,
        cwd=factory_shim_dir.parent,
        capture_output=True,
    )

    # Everything in /usr/local/factory/bundle gets overlaid into the
    # bundle.
    bundle_src_dir = chroot.full_path(
        sysroot_class.path, "usr", "local", "factory", "bundle"
    )
    if os.path.exists(bundle_src_dir):
        cros_build_lib.run(
            cmd + ["-y", "."], cwd=bundle_src_dir, capture_output=True
        )
    else:
        logging.warning(
            "create_factory_image_zip: %s not found, skipping", bundle_src_dir
        )

    # Add a version file in the zip file.
    if version is not None:
        version_filename = "BUILD_VERSION"
        # Creates a staging temporary folder.
        with osutils.TempDir() as temp_dir:
            version_file = os.path.join(temp_dir, version_filename)
            osutils.WriteFile(version_file, version)
            cros_build_lib.run(
                cmd + [version_filename], cwd=temp_dir, capture_output=True
            )

    return zipfile if os.path.exists(zipfile) else None


def create_stripped_packages_tar(
    chroot: chroot_lib.Chroot,
    build_target: build_target_lib.BuildTarget,
    output_dir: str,
) -> Union[str, None]:
    """Build stripped_packages.tar in archive_dir.

    Args:
        chroot: The chroot class used for these artifacts.
        build_target: The build target.
        output_dir: Directory to store stripped_packages.tar.

    Returns:
        The path to the zipfile if it could be created, else None.
    """
    package_globs = [
        "chromeos-base/chromeos-chrome",
        "sys-kernel/*kernel*",
    ]
    board = build_target.name
    stripped_pkg_dir = chroot.full_path(build_target.root, "stripped-packages")
    tarball_paths = []
    strip_package_path = path_util.ToChrootPath(
        os.path.join(constants.CHROMITE_SCRIPTS_DIR, "strip_package")
    )
    tarball_cwd = chroot.full_path(build_target.root)
    for pattern in package_globs:
        packages = portage_util.FindPackageNameMatches(pattern, board)
        for cpv in packages:
            cmd = [strip_package_path, "--board", board, cpv.cpf]
            cros_build_lib.run(
                cmd, enter_chroot=True, chroot_args=chroot.get_enter_args()
            )
            # Find the stripped package.
            files = glob.glob(os.path.join(stripped_pkg_dir, cpv.cpf) + ".*")
            if not files:
                bin_path = os.path.join(stripped_pkg_dir, cpv.cpf)
                raise AssertionError(
                    f"Silent failure to strip binary {cpv.cpf}? "
                    f"Failed to find stripped files at {bin_path}."
                )
            if len(files) > 1:
                logging.warning(
                    "Expected one stripped package for %s, found %d",
                    cpv.cpf,
                    len(files),
                )

            tarball = sorted(files)[-1]
            tarball_paths.append(os.path.relpath(tarball, tarball_cwd))

    if not tarball_paths:
        # tar barfs on an empty list of files, so skip tarring completely.
        return None

    tarball_output = os.path.join(output_dir, "stripped-packages.tar")
    cros_build_lib.CreateTarball(
        tarball_path=tarball_output,
        cwd=tarball_cwd,
        compression=cros_build_lib.CompressionType.NONE,
        chroot=chroot,
        inputs=tarball_paths,
    )
    return tarball_output


def create_netboot_kernel(
    board: str,
    output_dir: str,
):
    """Build netboot kernel artifacts in output_dir.

    Args:
        board: The board being built.
        output_dir: Directory to place the artifact
    """
    cmd = ["./make_netboot.sh", f"--board={board}", f"--image_dir={output_dir}"]
    cros_build_lib.run(cmd, enter_chroot=True)
