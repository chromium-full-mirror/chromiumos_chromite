# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Converts ChromeOS disk image to LVM stateful."""

import contextlib
import logging
import math
from pathlib import Path
import tempfile
from typing import Iterator, List, Optional
import uuid

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import image_lib
from chromite.lib import osutils


def get_parser() -> commandline.ArgumentParser:
    """Creates an argument parser for this script."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-image",
        required=True,
        type="file_exists",
        help="Path to chromiumos_test_image.bin.",
    )
    parser.add_argument(
        "--to-image",
        required=True,
        type="path",
        help="Destination image name.",
    )
    return parser


@contextlib.contextmanager
def activate_lvm_vg(lvm_vg_name: str) -> Iterator[None]:
    """Context manager for activating an LVM volume group.

    Without deactivation we won't be able to cleanly detach the loopback device.

    Args:
        lvm_vg_name: Name of the LVM volume group to activate.

    Yields:
        None. This context manager is used for its side effects.
    """

    cros_build_lib.sudo_run(["vgchange", "-ay", lvm_vg_name])
    try:
        yield
    finally:
        cros_build_lib.sudo_run(["vgchange", "-an", lvm_vg_name])


@contextlib.contextmanager
def create_lvm_state_partition(image_name: str) -> Iterator[Path]:
    """Creates a logical volume management (LVM) partition inside for stateful.

    Args:
        image_name: Name of the ChromeOS image.

    Yields:
        An unencrypted partition device name that's valid until the context
        manager exits.
    """
    with contextlib.ExitStack() as stack:
        logging.info("Creating logical volume setup...")
        loop = stack.enter_context(image_lib.LoopbackPartitions(image_name))
        partition_size = loop.GetPartitionInfo(constants.PART_STATE).size
        lvm_dev = loop.GetPartitionDevName(constants.PART_STATE)

        cros_build_lib.sudo_run(["pvcreate", "-ff", "--yes", lvm_dev])

        lvm_vg_name = str(uuid.uuid4())
        cros_build_lib.sudo_run(["vgcreate", "-p", "1", lvm_vg_name, lvm_dev])
        stack.enter_context(activate_lvm_vg(lvm_vg_name))

        # https://crsrc.org/o/src/platform2/chromeos-common-script/share/lvm-utils.sh;l=59-64;drc=a8f359bd28881351a729cc6069f1646522b9aee3
        thinpool_size = math.floor(partition_size * 98 / (100 * 1024 * 1024))
        ret = cros_build_lib.sudo_run(
            [
                "thin_metadata_size",
                "--block-size",
                "4k",
                "--pool-size",
                f"{thinpool_size}M",
                "--max-thins",
                "200",
                "--numeric-only",
                "-u",
                "M",
            ],
            capture_output=True,
            encoding="utf-8",
        )
        thinpool_metadata_size = ret.stdout.strip()

        cros_build_lib.sudo_run(
            [
                "lvcreate",
                "--zero",
                "n",
                "--size",
                f"{thinpool_size}M",
                "--poolmetadatasize",
                f"{thinpool_metadata_size}M",
                "--thinpool",
                "thinpool",
                f"{lvm_vg_name}/thinpool",
            ]
        )

        # https://crsrc.org/o/src/platform2/chromeos-common-script/share/lvm-utils.sh;l=79;drc=a8f359bd28881351a729cc6069f1646522b9aee3
        lv_size = math.floor(thinpool_size * 95 / 100)
        unencrypted_name = "unencrypted"
        cros_build_lib.sudo_run(
            [
                "lvcreate",
                "--thin",
                "-V",
                f"{lv_size}M",
                "-n",
                unencrypted_name,
                f"{lvm_vg_name}/thinpool",
            ]
        )

        # We use paths the LVM tools guarantee for us.
        # https://man7.org/linux/man-pages/man8/lvm.8.html#VALID_NAMES
        unencrypted_partition_device_name = (
            f"/dev/{lvm_vg_name}/{unencrypted_name}"
        )
        cros_build_lib.sudo_run(
            ["mkfs.ext4", unencrypted_partition_device_name]
        )

        yield unencrypted_partition_device_name


def convert_to_lvm_stateful(in_image_name: Path, out_image_name: Path) -> int:
    """Converts a CrOS image to an LVM stateful format.

    Takes a source CrOS image, converts it to an LVM stateful format,
    and writes it to the specified destination.

    Args:
        in_image_name: A string representing the path to the source CrOS image.
        out_image_name: A string representing the path where the converted image
            should be saved.

    Returns:
        A return code indicating whether the conversion was successful (0 means
        success).
    """

    with contextlib.ExitStack() as stack:
        in_loop = stack.enter_context(
            image_lib.LoopbackPartitions(in_image_name)
        )
        lvm_temp_in_mount_dir = in_loop.Mount([constants.PART_STATE])[0]

        logging.info("Creating a copy of the image...")
        cros_build_lib.run(
            [
                "dd",
                f"if={in_image_name}",
                f"of={out_image_name}",
                "conv=sparse",
                "bs=2M",
            ]
        )
        lvm_unencrypted_partition_device_name = stack.enter_context(
            create_lvm_state_partition(out_image_name)
        )

        logging.info("Copying files from original stateful filesystem...")
        lvm_temp_out_mount_dir = stack.enter_context(
            tempfile.TemporaryDirectory(prefix="lvm_temp_out_mount_")
        )
        stack.enter_context(
            osutils.MountDirContext(
                lvm_unencrypted_partition_device_name, lvm_temp_out_mount_dir
            )
        )
        cros_build_lib.sudo_run(
            [
                "cp",
                "--sparse=auto",
                "-a",
                f"{lvm_temp_in_mount_dir}/.",
                lvm_temp_out_mount_dir,
            ]
        )

        return 0


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()

    return convert_to_lvm_stateful(opts.from_image, opts.to_image)
