# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper script to call third_party_inventory service.

This script is intended to run inside chroot, after the system image has been
built (i.e. after `cros build-packages` and `cros build-image`) for a board.
"""

from typing import Optional

from chromite.lib import commandline
from chromite.service import third_party_inventory


def get_parser() -> commandline.ArgumentParser:
    """Returns the command line parser of this tool."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-b",
        "--board",
        type=str,
        required=True,
        help='which board to run for, like "amd64-generic"',
    )
    return parser


def main(args: Optional[list[str]] = None) -> Optional[int]:
    opts = get_parser().parse_args(args)

    third_party_inventory.collect_inventory(opts.board)
