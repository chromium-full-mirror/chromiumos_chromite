# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros build-kernel: Build a ChromeOS kernel image."""

import logging
from pathlib import Path

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import osutils
from chromite.service import kernel_image
from chromite.utils import timer


@command.command_decorator("build-kernel")
class BuildKernelCommand(command.CliCommand):
    """Build a ChromeOS kernel image."""

    use_jobs_options = True

    @classmethod
    def AddParser(cls, parser: commandline.ArgumentParser) -> None:
        """Adds command-specific arguments."""
        super(BuildKernelCommand, cls).AddParser(parser)

        # === Required Build Arguments ===
        parser.add_argument(
            "--board",
            type=str,
            required=True,
            help="Target board name (e.g., 'amd64-generic').",
        )
        parser.add_argument(
            "--working-dir",
            type=Path,
            required=True,
            help="Directory for intermediate build artifacts. Will be "
            "created if it doesn't exist.",
        )
        parser.add_argument(
            "--install-root",
            type=Path,
            required=True,
            help="Path to the installed board root directory containing "
            "necessary build tools (e.g., '/build/BOARD').",
        )

        group = parser.add_argument_group("Kernel Options")
        group.add_argument(
            "--kernel-serial-console",
            type=str,
            help="The tty for serial console logging.",
        )
        group.add_argument(
            "--kernel-ramfs",
            type=str,
            default="recovery_ramfs",
            help="Kernel initramfs variant to use.",
        )
        group.add_argument(
            "--kernel-version",
            type=str,
            default="0.0.1",
            help="Version string to embed in the kernel command line.",
        )
        group.add_argument(
            "--kernel-flags",
            nargs="*",
            help="Additional kernel features/flags to enable/disable "
            "(e.g., '-some_feature' '+another_feature'). "
            "These supplement the defaults.",
        )

        group = parser.add_argument_group("Signing Options")
        group.add_argument(
            "--keys-dir",
            type="dir_exists",
            help="Path to kernel signing keys directory. "
            "(Default: Dev keys).",
        )
        group.add_argument(
            "--public-key",
            type=str,
            help="Filename of the public key for keyblock signing.",
        )
        group.add_argument(
            "--private-key",
            type=str,
            help="Filename of the private key baked into the keyblock.",
        )
        group.add_argument(
            "--keyblock",
            type=str,
            help="Filename of the kernel keyblock.",
        )
        group.add_argument(
            "--extra-pkgs",
            action="split_extend",
            default=[],
            help="A list of extra packages to be built into kernel initramfs "
            "separated by space.",
        )

        group = parser.add_argument_group("Image Generation Options")
        group.add_bool_argument(
            "--bootable-image",
            default=False,
            enabled_desc=(
                "EXPERIMENTAL: After building the kernel, attempt to "
                "generate a bootable disk image (using the placeholder "
                "function)."
            ),
            disabled_desc="No bootable disk image.",
        )

    def __init__(self, options) -> None:
        """Initializes BuildKernelCommand."""
        super().__init__(options)
        self.builder = None
        self.kernel_image_path = None

    @timer.timed("Elapsed time (cros build-kernel)")
    def Run(self) -> int:
        """Executes the kernel build process."""
        commandline.RunInsideChroot()

        osutils.SafeMakedirs(self.options.working_dir, sudo=True)
        logging.info(
            "Using working directory: %s", self.options.working_dir.resolve()
        )

        kernel_options = {
            k: v
            for k, v in {
                "kernel_serial_console": self.options.kernel_serial_console,
                "kernel_ramfs": self.options.kernel_ramfs,
                "kernel_version": self.options.kernel_version,
                "kernel_flags": self.options.kernel_flags,
                "keys_dir": self.options.keys_dir,
                "public_key": self.options.public_key,
                "private_key": self.options.private_key,
                "keyblock": self.options.keyblock,
                "extra_pkgs": self.options.extra_pkgs,
            }.items()
            if v is not None
        }

        kernel_image_path = kernel_image.BuildKernel(
            board=self.options.board,
            work_dir=self.options.working_dir,
            install_root=self.options.install_root,
            bootable_image=self.options.bootable_image,
            jobs=self.options.jobs,
            **kernel_options,
        )

        if kernel_image_path is None:
            return 1

        logging.info("Build process finished.")
        return 0
