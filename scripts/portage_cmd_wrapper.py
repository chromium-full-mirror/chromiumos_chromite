# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper for board specific portage commands.

This script is meant to be used in generated wrapper scripts, not used directly.
"""

import os
from pathlib import Path
from typing import List, Optional

from chromite.lib import commandline
from chromite.lib import cros_build_lib


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--build-target",
        required=True,
        help="The build target name.",
    )
    parser.add_argument(
        "--sysroot",
        type="path",
        required=True,
        help="The path to the sysroot for which the command will be created.",
    )
    parser.add_argument(
        "--chost",
        required=True,
        help="The CHOST value for the sysroot.",
    )
    parser.add_argument(
        "command",
        nargs="+",
        help="The command to run.",
    )

    return parser


def parse_arguments(argv: List[str]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)

    opts.Freeze()
    return opts


def main(argv: Optional[List[str]]) -> Optional[int]:
    """Main."""
    commandline.RunInsideChroot()

    opts = parse_arguments(argv)

    extra_env = {
        "CHOST": opts.chost,
        "PORTAGE_CONFIGROOT": opts.sysroot,
        "SYSROOT": opts.sysroot,
        "ROOT": opts.sysroot,
        "PORTAGE_USERNAME": (
            os.environ.get("PORTAGE_USERNAME") or Path("~").expanduser().name
        ),
    }

    # If we try to use sudo when the sandbox is active, we get ugly warnings
    # that just confuse developers.
    if os.environ.get("SANDBOX_ON") == "1":
        os.environ["SANDBOX_ON"] = "0"
    os.environ.pop("LD_PRELOAD", None)

    result = cros_build_lib.sudo_run(
        opts.command,
        preserve_env=True,
        extra_env=extra_env,
        check=False,
    )

    return result.returncode
