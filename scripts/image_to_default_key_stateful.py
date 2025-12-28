# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Converts ChromeOS disk image to dm-default_key_stateful."""

import contextlib
from pathlib import Path
from typing import List, Optional

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import image_lib


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


def convert_to_default_key_stateful(
    in_image_name: Path, out_image_name: Path
) -> str:
    """Attaches a disk image using losetup and returns the loop device.

    Formats partition 11 of the loop device as ext4.

    Returns:
        A return code indicating whether the conversion was successful (0 means
        success).
    """

    with contextlib.ExitStack() as stack:
        cros_build_lib.run(
            [
                "dd",
                f"if={in_image_name}",
                f"of={out_image_name}",
                "conv=sparse",
                "bs=2M",
            ]
        )

        out_loop = stack.enter_context(
            image_lib.LoopbackPartitions(out_image_name)
        )

        metadata_dev = out_loop.GetPartitionDevName(
            constants.PART_POWERWASH_DATA
        )

        cros_build_lib.sudo_run(["mkfs.ext4", metadata_dev])

    return 0


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.freeze()

    return convert_to_default_key_stateful(opts.from_image, opts.to_image)
