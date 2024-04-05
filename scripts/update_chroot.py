# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Update the SDK.

Performs an update of the chroot. This script is called as part of
build_packages, so there is typically no need to call this script directly.
"""

import argparse
from typing import List, Optional

from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.service import sdk as sdk_service
from chromite.service import sysroot
from chromite.utils import timer


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    # TODO(vapier): Remove underscore separated arguments and the deprecated
    # message after Jun 2024.
    deprecated = "Argument will be removed Jun 2024. Use %s instead."

    parser = commandline.ArgumentParser(description=__doc__)

    parser.add_bool_argument(
        "--usepkg",
        True,
        "Use binary packages to bootstrap.",
        "Do not use binary packages to bootstrap.",
    )
    parser.add_argument(
        "--nousepkg",
        dest="usepkg",
        action="store_false",
        deprecated=deprecated % "--no-usepkg",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow manual update_chroot.",
    )

    group = parser.add_argument_group("Advanced Build Modification Options")
    group.add_argument(
        "--jobs",
        type=int,
        help="Maximum number of packages to build in parallel.",
    )
    group.add_argument(
        "--skip-toolchain-update",
        dest="update_toolchain",
        action="store_false",
        help="Deprecated (flag is ignored if passed.)",
    )
    group.add_argument(
        "--skip_toolchain_update",
        dest="update_toolchain",
        action="store_false",
        deprecated=deprecated % "--skip-toolchain-update",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--toolchain-boards",
        nargs="+",
        help="Extra toolchains to setup for the specified boards.",
    )
    group.add_argument(
        "--toolchain_boards",
        nargs="+",
        deprecated=deprecated % "--toolchain-boards",
        help=argparse.SUPPRESS,
    )
    group.add_argument(
        "--backtrack",
        type=int,
        default=sysroot.BACKTRACK_DEFAULT,
        help="See emerge --backtrack.",
    )

    return parser


@timer.timed("Elapsed time (update_chroot)")
def main(argv: Optional[List[str]] = None) -> Optional[int]:
    commandline.RunInsideChroot()

    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()

    if not opts.force:
        cros_build_lib.Die(
            "Automatic chroot upgrade is done by `cros_sdk --update` (normally "
            "enabled by default), and there's generally no need to manually "
            "call update_chroot.  If you really want to update your SDK "
            "packages (thereby invalidating your chroot), pass --force to "
            "this command."
        )

    update_args = sdk_service.UpdateArguments(
        build_source=not opts.usepkg,
        toolchain_targets=opts.toolchain_boards,
        jobs=opts.jobs,
        backtrack=opts.backtrack,
    )
    result = sdk_service.Update(update_args)
    return result.return_code
