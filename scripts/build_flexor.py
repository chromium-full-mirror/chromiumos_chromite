# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to generate Flexor kernel images."""

import logging
import os
import shutil
import tempfile
from typing import List, Optional

from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import flexor


def get_parser() -> commandline.ArgumentParser:
    """Creates an argument parser and returns it."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--board", "-b", "--build-target", required=True, help="The board name."
    )
    parser.add_argument(
        "--version", required=True, help="The chromeos version string."
    )
    parser.add_argument(
        "--image",
        type="path",
        required=True,
        help="The path to the chromium os image.",
    )
    parser.add_argument(
        "--keys-dir",
        type="dir_exists",
        help="The path to keyset.",
        default=constants.VBOOT_DEVKEYS_DIR,
    )
    parser.add_argument(
        "--public-key",
        help="Filename to the public key whose private part "
        "signed the keyblock.",
        default=constants.KERNEL_PUBLIC_SUBKEY,
    )
    parser.add_argument(
        "--private-key",
        help="Filename to the private key whose public part is "
        "baked into the keyblock.",
        default=constants.KERNEL_DATA_PRIVATE_KEY,
    )
    parser.add_argument(
        "--keyblock",
        help="Filename to the kernel keyblock.",
        default=constants.KERNEL_KEYBLOCK,
    )
    parser.add_argument(
        "--serial",
        type=str,
        help="Serial port for the kernel console (e.g. printks)",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="Force the kernel to be rebuilt when repacking with "
        "debug flags. Use with --mod-for-dev in case kernel is "
        "not already built or needs to be rebuilt.",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=os.cpu_count(),
        help="Number of packages to build in parallel. "
        "(Default: %(default)s)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    logging.info("Start building Flexor")
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()

    with tempfile.TemporaryDirectory() as work_dir:
        build_kernel = opts.force_build
        assert opts.board == "reven", f"Unable to build flexor for {opts.board}"
        build_target = build_target_lib.BuildTarget(opts.board)
        kernel = flexor.create_flexor_kernel_image(
            build_target,
            opts.version,
            work_dir,
            opts.keys_dir,
            opts.public_key,
            opts.private_key,
            opts.keyblock,
            opts.serial,
            opts.jobs,
            build_kernel,
        )
        shutil.copy2(kernel, opts.image)
        logging.info("Saved Flexor kernel image to %s", opts.image)
