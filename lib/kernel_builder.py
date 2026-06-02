# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for building ChromeOS kernels.

Provides a Builder class with methods for various kernel build steps,
including generating specific kernel images (e.g., for recovery) with
custom features and signing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence

from chromite.lib import build_target_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import ensure_bootstrap
from chromite.lib import kernel_cmdline
from chromite.lib import osutils


class Error(Exception):
    """Base error class for the module."""


class KernelBuildError(Error):
    """Error class thrown when failing to build kernel (image)."""


class Builder:
    """A class for building kernel images and related artifacts."""

    def __init__(
        self,
        board: str,
        work_dir: str | os.PathLike,
        install_root: str | os.PathLike,
        jobs: Optional[int] = None,
    ) -> None:
        """Initialize this class.

        Args:
            board: The board to build the kernel for.
            work_dir: The directory for keeping intermediary files.
            install_root: A directory to put the built kernel files (e.g.
                vmlinuz).
            jobs: The number of packages to build in parallel. If None, emerge's
                default might be used (often based on core count).
        """
        self._board = board
        # Store paths as Path objects internally.
        self._work_dir = Path(work_dir)
        self._install_root = Path(install_root)
        # Convert jobs to emerge argument string.
        self.jobs_arg = f"--jobs={jobs}" if jobs is not None else None
        self._build_target = build_target_lib.BuildTarget(self._board)
        self._board_root = build_target_lib.get_default_sysroot_path(board)

        # Ensure work_dir exists.
        self._work_dir.mkdir(parents=True, exist_ok=True)
        # install_root might be managed elsewhere (like emerge --root=),
        # so don't create it here unless necessary, but ensure it's a Path.

    def CreateCustomKernel(
        self,
        kernel_flags: List[str],
        use_flags_override: Optional[List[str]] = None,
        extra_pkgs: Optional[List[str]] = None,
    ) -> None:
        """Builds a custom kernel package and installs it to the install_root.

        This method handles building the kernel package (`.tbz2`) using the
        specified USE flags and then installing that package into the
        `install_root` directory configured for this Builder instance. It also
        builds the necessary initramfs package first.

        Args:
            kernel_flags: A list of USE flags specific to this kernel build.
            use_flags_override: A list of USE flags to entirely replace the
                default environment USE variable for this build. If None,
                the environment USE flags are combined with kernel_flags.
            extra_pkgs: Extra packages to be built before building initramfs.
        """
        pkgdir = self._work_dir / "packages"
        logging.info("Using PKGDIR: %s", pkgdir)
        # Ensure pkgdir exists and is clean for sudo operations later.
        try:
            # Attempt cleanup first in case of stale permissions or contents.
            osutils.RmDir(pkgdir, ignore_missing=True, sudo=True)
        except cros_build_lib.RunCommandError as e:
            logging.warning(
                "Failed initial cleanup of %s: %s. Proceeding anyway.",
                pkgdir,
                e,
            )
        osutils.SafeMakedirs(pkgdir, sudo=True)

        try:
            self._CreateCustomKernelInternal(
                str(pkgdir), kernel_flags, use_flags_override, extra_pkgs
            )
        finally:
            # Force delete the pkgdir as it may contain root-owned files.
            try:
                osutils.RmDir(pkgdir, ignore_missing=True, sudo=True)
            except cros_build_lib.RunCommandError as e:
                # Log error but don't fail the whole process just for cleanup.
                logging.warning(
                    "Failed to delete temp pkgdir %s: %s", pkgdir, e
                )

    def _CreateCustomKernelInternal(
        self,
        pkgdir: str,
        kernel_flags: List[str],
        use_flags_override: Optional[List[str]] = None,
        extra_pkgs: Optional[List[str]] = None,
    ) -> None:
        """Internal implementation for CreateCustomKernel()."""
        logging.info("Building custom kernel package.")
        # Determine final USE flags.
        use_flags = (
            list(use_flags_override)
            if use_flags_override is not None
            else os.environ.get("USE", "").split()
        ) + list(kernel_flags)
        logging.debug("Using USE flags: %s", use_flags)
        extra_env = {"PKGDIR": pkgdir, "USE": " ".join(use_flags)}
        emerge = self._build_target.get_command("emerge")

        # Prepare emerge command base args.
        # Add --verbose to print out the dep list.
        emerge_cmd_base = [emerge, "--verbose"]
        if self.jobs_arg:
            emerge_cmd_base.append(self.jobs_arg)

        # 1. Build/Update chromeos-initramfs package.
        logging.info("Ensuring chromeos-initramfs package is up-to-date.")
        initramfs_pkg = "chromeos-base/chromeos-initramfs"
        try:
            # Build the extra packages before initramfs.
            if extra_pkgs:
                for pkg in extra_pkgs:
                    cros_build_lib.run(
                        emerge_cmd_base + [pkg],
                        enter_chroot=True,
                        extra_env=extra_env,
                    )
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                f"Failed to build the extra package: {e}"
            ) from e

        try:
            # Build the initramfs package.
            cros_build_lib.run(
                emerge_cmd_base + [initramfs_pkg],
                enter_chroot=True,
                extra_env=extra_env,
            )
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                f"Failed to build initramfs package '{initramfs_pkg}': {e}"
            ) from e

        # 2. Verify kernel dependencies.
        logging.info("Verifying kernel dependencies.")
        try:
            # Find the actual kernel package name (e.g., chromeos-kernel-5_15).
            kernel_pkg = cros_build_lib.run(
                [
                    self._build_target.get_command("portageq"),
                    "expand_virtual",
                    self._board_root,
                    "virtual/linux-sources",
                ],
                encoding="utf-8",
                enter_chroot=True,
                capture_output=True,
            ).stdout.strip()

            if not kernel_pkg:
                raise KernelBuildError(
                    "Could not determine kernel package name for "
                    "virtual/linux-sources"
                )

            logging.debug("Target kernel package: %s", kernel_pkg)

            # Emerge dependencies only.
            cros_build_lib.run(
                emerge_cmd_base + ["--onlydeps", kernel_pkg],
                enter_chroot=True,
                extra_env=extra_env,
                clear_env=["INSTALL_MASK"],
            )
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                f"Failed to satisfy kernel dependencies for '{kernel_pkg}': {e}"
            ) from e

        # 3. Build the kernel package only (into PKGDIR).
        logging.info("Building the custom kernel package.")
        try:
            cros_build_lib.run(
                emerge_cmd_base + ["--buildpkgonly", kernel_pkg],
                enter_chroot=True,
                extra_env=extra_env,
            )
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                f"Failed to build kernel package '{kernel_pkg}': {e}"
            ) from e

        # 4. Install the built kernel package into the specified install_root.
        logging.info(
            "Installing custom kernel package into install root '%s'.",
            self._install_root,
        )
        try:
            # Use --usepkgonly to ensure we install the package just built.
            # Use --root to specify the installation target directory.
            install_cmd = emerge_cmd_base + [
                "--usepkgonly",
                f"--root={self._install_root}",
                kernel_pkg,
            ]
            cros_build_lib.run(
                install_cmd,
                enter_chroot=True,
                extra_env=extra_env,
            )
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                "Failed to install kernel package "
                f"'{kernel_pkg}' into '{self._install_root}': {e}"
            ) from e

        logging.info("Custom kernel package built and installed successfully.")

    def CreateKernelImage(
        self,
        output_image: str,
        boot_args: Optional[str] = None,
        serial: Optional[str] = None,
        keys_dir: str = constants.VBOOT_DEVKEYS_DIR,
        public_key: str = constants.KERNEL_PUBLIC_SUBKEY,
        private_key: str = constants.KERNEL_DATA_PRIVATE_KEY,
        keyblock: str = constants.KERNEL_KEYBLOCK,
        disable_rootfs_verification: bool = False,
    ) -> None:
        """Builds the final bootable kernel image (e.g., kernel.image).

        This uses the vmlinuz file previously installed into `install_root`
        (typically by `CreateCustomKernel`) and packages it with specified
        boot arguments and signing keys using `build_kernel_image.sh`.

        Args:
            output_image: The path where the final kernel image will be written.
            boot_args: Kernel command line arguments.
            serial: Serial port configuration string.
            keys_dir: Path to the directory containing kernel signing keys.
            public_key: Filename of the public key within keys_dir.
            private_key: Filename of the private key within keys_dir.
            keyblock: Filename of the kernel keyblock within keys_dir.
            disable_rootfs_verification: If True, add flags to disable rootfs
                verification in the kernel command line.
        """
        logging.info("Building final kernel image: %s", output_image)

        portageq = self._build_target.get_command("portageq")
        try:
            # Query the architecture for the target board.
            arch = cros_build_lib.run(
                [portageq, "envvar", "ARCH"],
                encoding="utf-8",
                enter_chroot=True,
                capture_output=True,
            ).stdout.strip()
            logging.debug("Using architecture %s", arch)
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                "Failed to query kernel architecture for board "
                f"{self._board}: {e}"
            ) from e

        vmlinuz_path = self._install_root / "boot" / "vmlinuz"

        # Construct the command for build_kernel_image.sh.
        cmd = [
            constants.CROSUTILS_DIR / "build_kernel_image.sh",
            f"--board={self._board}",
            f"--arch={arch}",
            f"--to={output_image}",
            f"--vmlinuz={vmlinuz_path}",
            # Pass work_dir as a string, as the script expects it.
            f"--working_dir={self._work_dir}",
            # Keep intermediate files in work_dir for debugging.
            "--keep_work",
            f"--keys_dir={keys_dir}",
            f"--public={public_key}",
            f"--private={private_key}",
            f"--keyblock={keyblock}",
        ]

        # Add optional arguments.
        if disable_rootfs_verification:
            cmd.append("--noenable_rootfs_verification")
        if boot_args:
            # Format boot args consistently.
            arg_list = kernel_cmdline.KernelArgList(boot_args)
            cmd.append(f"--boot_args={arg_list.Format()}")
        if serial:
            # Basic validation for serial format.
            if not serial.startswith("tty"):
                logging.warning(
                    "Serial port '%s' does not start with 'tty'. "
                    "Ensure this is correct.",
                    serial,
                )
            cmd.append(f"--enable_serial={serial}")

        # Execute the script within the chroot.
        try:
            cros_build_lib.run(cmd, enter_chroot=True)
        except cros_build_lib.RunCommandError as e:
            raise KernelBuildError(
                "Failed to create kernel image using build_kernel_image.sh: "
                f"{e}"
            ) from e

        logging.info("Kernel image created successfully at %s", output_image)

    # --- Integrated High-Level Methods ---

    def _get_default_base_features(self, kernel_ramfs: str) -> List[str]:
        """Returns the default list of base kernel features for recovery."""
        # Note: Features starting with '-' are disabled, others enabled.
        # Ensure the specified ramfs is included.
        # Trusted Platform Module support.
        # I2C device interface.
        # FAT filesystem support (common for EFI/USB).
        # Use XZ compression for the kernel.
        # PC serial port support.
        # Disable AutoFDO for kernel (typical for recovery).
        # Disable AutoFDO verification.
        return [
            kernel_ramfs,
            "i2cdev",
            "vfat",
            "kernel_compress_xz",
            "pcserial",
            "-kernel_afdo",
            "-kernel_afdo_verify",
        ]

    def BuildCustomKernelImage(
        self,
        kernel_version: str = "0.0.1",
        kernel_ramfs: str = "recovery_ramfs",
        kernel_flags: Optional[List[str]] = None,
        base_kernel_features: Optional[Sequence[str]] = None,
        kernel_serial_console: Optional[str] = None,
        keys_dir: str = constants.VBOOT_DEVKEYS_DIR,
        public_key: str = constants.KERNEL_PUBLIC_SUBKEY,
        private_key: str = constants.KERNEL_DATA_PRIVATE_KEY,
        keyblock: str = constants.KERNEL_KEYBLOCK,
        disable_rootfs_verification: bool = False,
        output_filename: str = constants.KERNEL_IMAGE_IMG,
        extra_pkgs: Optional[List[str]] = None,
        debug: bool = False,
    ) -> Path:
        """Builds a custom kernel package and creates a bootable kernel image.

        This is a higher-level method that orchestrates:
        1. Determining the full set of USE flags (base + custom).
        2. Calling `CreateCustomKernel` to build and install the kernel package.
        3. Calling `CreateKernelImage` to create the final signed image file.

        Defaults are often set for creating a recovery kernel image.

        Args:
            kernel_version: The version to embed in the kernel command line.
            kernel_ramfs: The specific kernel initramfs variant USE flag
                Added to features if `base_kernel_features` is None.
            kernel_flags: Additional USE flags for this build
                (e.g. ["-debug"]).
            base_kernel_features: Explicit list of base USE flags. If None, the
                defaults suitable for recovery are used (see
                `_get_default_base_features`). If provided, ensure you include
                the desired ramfs flag.
            kernel_serial_console: Serial console for kernel command line.
            keys_dir: Path to kernel signing keys directory.
            public_key: Public key filename within keys_dir.
            private_key: Private key filename within keys_dir.
            keyblock: Keyblock filename within keys_dir.
            disable_rootfs_verification: Disable rootfs verification.
            output_filename: The name of the final kernel image file to be
                created within the builder's work_dir.
            extra_pkgs: Extra packages to be built before building initramfs.

        Returns:
            The absolute Path to the generated kernel image file.

        Raises:
            KernelBuildError: If any step of the build process fails.
        """
        logging.info(
            "Starting custom kernel image build for board '%s'",
            self._board,
        )

        # We'll compile packages which might call `cros lint`.
        ensure_bootstrap.for_lint()

        # 1. Determine Kernel Features (USE flags).
        if base_kernel_features is None:
            actual_base_features = self._get_default_base_features(kernel_ramfs)
            logging.info(
                "Using default base kernel features for '%s'.", kernel_ramfs
            )
        else:
            # Use the provided list directly. User must include ramfs flag.
            if kernel_ramfs not in base_kernel_features:
                raise KernelBuildError(
                    "Provided `base_kernel_features` must include the "
                    f"specified `kernel_ramfs` flag: {kernel_ramfs}"
                )
            actual_base_features = base_kernel_features
            logging.info("Using provided base kernel features.")

        # Combine base features with user-provided additional flags.
        final_kernel_flags = list(actual_base_features)
        if kernel_flags:
            final_kernel_flags.extend(kernel_flags)

        # Filter conflicting ramfs flags from environment USE flags.
        # This prevents accidental overrides if USE env var has
        # e.g. 'dev_ramfs'.
        env_use_flags = os.environ.get("USE", "").split()
        filtered_use_flags = [
            x for x in env_use_flags if not x.endswith("_ramfs")
        ]
        logging.debug(
            "Base environment USE flags (ramfs filtered): %s",
            filtered_use_flags,
        )

        # 2. Build and install the kernel package using determined flags.
        logging.info(
            "Building kernel package with features: %s", final_kernel_flags
        )
        self.CreateCustomKernel(
            kernel_flags=final_kernel_flags,
            use_flags_override=filtered_use_flags,
            extra_pkgs=extra_pkgs,
        )

        # 3. Prepare for final image creation.
        kernel_image_path = self._work_dir / output_filename
        # Kernel command line arguments.
        # Ensure version is clean.
        # NOTE: Make cmdline args more configurable if needed beyond version.
        boot_args = f"noinitrd panic=60 version={kernel_version.strip()}"
        if debug:
            boot_args += " cros_debug"
        logging.info("Using kernel command line: %s", boot_args)

        # 4. Create the final signed kernel image.
        self.CreateKernelImage(
            output_image=str(kernel_image_path),
            boot_args=boot_args,
            serial=kernel_serial_console,
            keys_dir=keys_dir,
            public_key=public_key,
            private_key=private_key,
            keyblock=keyblock,
            disable_rootfs_verification=disable_rootfs_verification,
        )

        logging.info(
            "Successfully generated custom kernel image: %s", kernel_image_path
        )
        return kernel_image_path

    def GenerateBootableImage(
        self, kernel_image_path: Path, *args, **kwargs
    ) -> Path:
        """Generates a bootable disk image containing the kernel.

        (Placeholder) This method is intended to take the generated kernel
        (from `BuildCustomKernelImage` or `CreateKernelImage`) and other
        necessary components (like a root filesystem, bootloader configuration)
        and assemble them into a final bootable disk image (e.g., USB image).

        Args:
            kernel_image_path: Path to the kernel image (e.g., kernel.image).
            # ... other parameters needed for image creation ...
            *args: Additional positional arguments.
            **kwargs: Additional keyword arguments.

        Returns:
            The Path to the generated bootable disk image.

        Raises:
            NotImplementedError: This function is not yet implemented.
        """
        # NOTE: Implement the logic to create a bootable image.
        # This would typically involve using tools like `cros build-image`
        # or custom scripting with `cgpt`, `mkfs`, bootloader setup etc.
        # It would likely need access to self._board, self._work_dir, etc.
        logging.info("Placeholder method called: generate_bootable_image.")
        logging.info("Board: %s", self._board)
        logging.info("Work directory: %s", self._work_dir)
        logging.info("Input Kernel image: %s", kernel_image_path)
        logging.info("Args: %s, Kwargs: %s", args, kwargs)

        raise NotImplementedError(
            "Bootable disk image generation is not yet implemented "
            "in this class."
        )
        # Example return (when implemented):
        # return self._work_dir / "final_bootable_image.bin"
