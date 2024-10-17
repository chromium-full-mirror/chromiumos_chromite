# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flexor build library."""

import os
from pathlib import Path
from typing import Optional

from chromite.lib import build_target_lib
from chromite.lib import cros_build_lib
from chromite.lib import kernel_builder


FLEXOR_KERNEL_IMAGE = Path("flexor.img")
FLEXOR_VMLINUZ = Path("flexor_vmlinuz")
KERNEL_FLAGS = (
    "flexor_ramfs",
    "tpm",
    "i2cdev",
    "vfat",
    "kernel_compress_xz",
    "pcserial",
    "-kernel_afdo",
    "-kernel_afdo_verify",
)


class Error(Exception):
    """Base error class for the module."""


class FlexorBuildError(Error):
    """Error class thrown when failing to build the Flexor kernel (image)."""


def create_flexor_kernel_image(
    build_target: build_target_lib.BuildTarget,
    version: str,
    work_dir: Path,
    keys_dir: Path,
    public_key: Path,
    private_key: Path,
    keyblock: Path,
    serial: Optional[str],
    jobs: int,
    build_kernel: bool = True,
) -> str:
    """Creates the Flexor kernel image.

    And puts it in the work directory.

    Args:
        jobs: The number of packages to build in parallel.
        build_target: The target to build the kernel for.
        version: The chromeos version string.
        work_dir: The directory for keeping intermediary files.
        keys_dir: The path to kernel keys directories.
        public_key: Filename to the public key whose private part signed the
            keyblock.
        private_key: Filename to the private key whose public part is baked into
            the keyblock.
        keyblock: Filename to the kernel keyblock.
        serial: Serial port for the kernel console (e.g. printks).
        build_kernel: Build a new kernel from source.

    Returns:
        The path to the generated kernel image.
    """
    board = build_target.name
    install_root = Path(build_target.full_path("factory-root"))
    kb = kernel_builder.Builder(board, work_dir, install_root, jobs)
    if build_kernel:
        # Flexor ramfs cannot be built with multiple conflicting `_ramfs`
        # flags.
        try:
            kb.CreateCustomKernel(
                KERNEL_FLAGS,
                [
                    x
                    for x in os.environ.get("USE", "").split()
                    if not x.endswith("_ramfs")
                ],
            )
        except kernel_builder.KernelBuildError as e:
            raise FlexorBuildError(
                "flexor: Failed to build flexor kernel image"
            ) from e
    kernel = work_dir / FLEXOR_KERNEL_IMAGE
    assert " " not in version, f"bad version: {version}"
    boot_args = f"noinitrd panic=60 cros_flexor_version={version}"
    try:
        kb.CreateKernelImage(
            kernel,
            boot_args=boot_args,
            serial=serial,
            keys_dir=keys_dir,
            public_key=public_key,
            private_key=private_key,
            keyblock=keyblock,
        )
    except:
        raise FlexorBuildError(
            "flexor: Failed to create flexor kernel image"
        ) from e
    vmlinuz = work_dir / FLEXOR_VMLINUZ
    try:
        cros_build_lib.sudo_run(
            ["vbutil_kernel", "--get-vmlinuz", kernel, "--vmlinuz-out", vmlinuz]
        )
    except cros_build_lib.RunCommandError as e:
        raise FlexorBuildError("Failed to extract flexor vmlinuz") from e
    return vmlinuz
