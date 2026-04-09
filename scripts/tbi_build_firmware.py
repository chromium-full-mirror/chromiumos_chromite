# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Entry point script for TBI builders.

This is intended to be run from the chromite root directory on builders,
so it will do things that may be suboptimal in a dev environment, like
writing files to arbitrary locations.
"""

import json
import subprocess
from typing import List, Optional

from chromite.lib import commandline


def get_parser() -> commandline.ArgumentParser:
    """Creates the argparse parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--location",
        type=int,
        required=True,
        help="Firmware location (int).",
    )
    parser.add_argument(
        "--targets",
        required=True,
        action="split_extend",
        help="Space-separated list of firmware target names.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    parser = get_parser()
    opts = parser.parse_args(argv or [])

    # TODO(ayatane): setup chroot

    request = {
        "firmwareLocation": opts.location,
        "firmwareTargets": [{"name": t} for t in opts.targets],
    }
    with open("input.json", "w", encoding="utf-8") as f:
        json.dump(request, f, indent=2)

    p = subprocess.run(
        [
            "bin/build_api",
            "chromite.api.FirmwareService/BuildAllFirmware",
            "--input-json=input.json",
            "--output-json=output.json",
        ],
        check=False,
    )
    return p.returncode
