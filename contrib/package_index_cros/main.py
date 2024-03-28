# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Main entrypoint for the package_index_cros tool.

For usage instructions, see README.md.
"""

import argparse
import os
import textwrap
from typing import List, Optional

from chromite.contrib.package_index_cros.lib import conductor
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import commandline


def _build_parser():
    parser = commandline.ArgumentParser(
        usage="%(prog)s [options] package [package...]",
        description=textwrap.dedent(
            "Generate compile commands for given packages in current or given"
            "directory."
        ),
        epilog=textwrap.dedent(
            """\
        If you don't want build artifacts, run: cros clean

        WARNING: Be careful with header files. There are still some include
        paths in chroot (like dbus, or standard library, or something else
        yet to be discovered). You might end up changing a chroot file instead
        of the actual one.

        WARNING: --build-dir flag removes existing build dir if any."""
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "--with-tests",
        "--with_tests",
        action="store_true",
        default=False,
        dest="with_tests",
        help=textwrap.dedent(
            """\
    Build tests alongside packages before generating.
    This assumes --with-build is set."""
        ),
    )

    parser.add_argument(
        "--board",
        "-b",
        type=str,
        default="amd64-generic",
        dest="board",
        help="Board to setup and build packages",
    )

    parser.add_argument(
        "--fail-fast",
        "--fail_fast",
        default=False,
        dest="fail_fast",
        help="""\
    If set, stops on first failed package.""",
    )

    parser.add_argument(
        "--chroot",
        type=str,
        default="",
        dest="chroot_dir",
        help=textwrap.dedent(
            """\
    Set custom chroot path instead of default one.
    WARNING: Only works with chroot paths outside of checkout. Paths inside
    checkout are currently ignored and always resolved as
    '/cros_checkout/chroot'."""
        ),
    )

    parser.add_argument(
        "--chroot-out",
        type=str,
        default="",
        dest="chroot_out_dir",
        help=textwrap.dedent(
            """\
  Set custom chroot output path instead of default one."""
        ),
    )

    compile_commands_args = parser.add_mutually_exclusive_group()
    compile_commands_args.add_argument(
        "--compile-commands",
        "--compile_commands",
        "-c",
        type=str,
        dest="compile_commands_file",
        default=None,
        help=textwrap.dedent(
            """\
    Output file for compile commands json.
    Default: compile_commands.json in current directory.
    If --build-dir is specified, paths will refer to this
    directory."""
        ),
    )

    build_dir_args = parser.add_mutually_exclusive_group()
    build_dir_args.add_argument(
        "--build-dir",
        "--build_dir",
        "-o",
        type=str,
        dest="build_dir",
        default=None,
        help=textwrap.dedent(
            """\
    WARNING: existing dir if any will be completely
    removed.

    Directory to store build artifacts from out/Default
    packages dirs.
    If --build-dir is specified, paths will refer to this
    directory."""
        ),
    )

    parser.add_argument(
        "packages", type=str, nargs="+", help="List of packages to generate"
    )

    return parser


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.compile_commands_file:
        args.compile_commands_file = os.path.abspath(args.compile_commands_file)

    if args.build_dir:
        args.build_dir = os.path.abspath(args.build_dir)

    _setup = setup.Setup(
        args.board,
        with_tests=args.with_tests,
        chroot_dir=args.chroot_dir,
        chroot_out_dir=args.chroot_out_dir,
    )

    _conductor = conductor.Conductor(_setup)
    _conductor.prepare(package_names=args.packages)
    _conductor.do_magic(
        cdb_output_file=args.compile_commands_file,
        build_output_dir=args.build_dir,
        fail_fast=args.fail_fast,
    )
    return 0
