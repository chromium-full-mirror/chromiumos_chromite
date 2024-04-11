# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Skeleton for new scripts or to allow quickly implementing temp scripts.

TODO(skeleton): Rewrite file docblock.
"""

from typing import List, Optional

from chromite.lib import commandline


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)

    # TODO(skeleton): Delete.
    _add_local_script_args(parser)
    # TODO(skeleton): Add arguments.

    return parser


def _add_local_script_args(parser: commandline.ArgumentParser) -> None:
    """Add a bunch of commonly used arguments to the parser.

    This is for hacking up quick, local scripts, and not intended to be kept
    when used as a skeleton for a permanent script.
    TODO(skeleton): Delete function.
    """
    parser.add_argument(
        "-b", "--board", "--build-target", help="Build target name."
    )
    parser.add_argument("--chroot", type="str_path", help="Chroot path.")
    parser.add_argument("--input", type="str_path", help="Input path.")
    parser.add_argument("--output", type="str_path", help="Output path.")
    parser.add_argument("-p", "--package", help="Package.")
    parser.add_argument(
        "--sdk", action="store_true", default=False, help="For the SDK."
    )
    parser.add_argument("--sysroot", type="str_path", help="Sysroot path.")

    parser.add_argument("packages", nargs="*", default=[])


def parse_arguments(argv: Optional[List[str]]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)

    opts.Freeze()
    return opts


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    # Uncomment for inside-only scripts.
    # TODO(skeleton) Delete or uncomment.
    # commandline.RunInsideChroot()

    opts = parse_arguments(argv)
    print(opts)
