# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This script emerges packages and retrieves their lints.

Currently support is provided for both general and differential linting of C++
with Clang Tidy and Rust with Cargo Clippy for all packages within platform2.
"""

import json
import os
from pathlib import Path
import sys
from typing import List, Text

from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import portage_util
from chromite.lib import terminal
from chromite.lib import workon_helper
from chromite.lib.parser import package_info
from chromite.service import toolchain
from chromite.utils import file_util


def parse_packages(
    build_target: build_target_lib.BuildTarget, packages: List[str]
) -> List[package_info.PackageInfo]:
    """Parse packages and insert the category if none is given.

    Args:
        build_target: build_target to find ebuild for
        packages: user input package names to parse

    Returns:
        A list of parsed PackageInfo objects
    """
    package_infos: List[package_info.PackageInfo] = []
    for package in packages:
        parsed = package_info.parse(package)
        if not parsed.category:
            # If a category is not specified, get it from the ebuild path.
            if build_target.is_host():
                ebuild_path = portage_util.FindEbuildForPackage(
                    package, build_target.root
                )
            else:
                ebuild_path = portage_util.FindEbuildForBoardPackage(
                    package, build_target.name, build_target.root
                )
            ebuild_data = portage_util.EBuild(ebuild_path)
            parsed = package_info.parse(ebuild_data.package)
        package_infos.append(parsed)
    return package_infos


def make_relative_to_cros(file_path: str) -> Path:
    """removes /mnt/host/source from file_paths if present."""
    path = Path(file_path)
    try:
        return path.relative_to(constants.CHROOT_SOURCE_ROOT)
    except ValueError:
        return path


def format_lint(lint: toolchain.LinterFinding) -> Text:
    """Formats a lint for human-readable printing.

    Example output:
    [ClangTidy] In 'path/to/file.c' on line 36:
        Also in 'path/to/file.c' on line 40:
        Also in 'path/to/file.c' on lines 50-53:
      You did something bad, don't do it.

    Args:
        lint: A linter finding from the toolchain service.

    Returns:
        A correctly formatted string ready to be displayed to the user.
    """

    color = terminal.Color(True)
    lines = []
    linter_prefix = color.Color(
        terminal.Color.YELLOW,
        f"[{lint.linter}]",
        background_color=terminal.Color.BLACK,
    )
    for loc in lint.locations:
        filepath = make_relative_to_cros(loc.filepath)
        if not lines:
            location_prefix = f"\n{linter_prefix} In"
        else:
            location_prefix = "   and in"
        if loc.line_start != loc.line_end:
            lines.append(
                f"{location_prefix} '{filepath}' "
                f"lines {loc.line_start}-{loc.line_end}:"
            )
        else:
            lines.append(
                f"{location_prefix} '{filepath}' line {loc.line_start}:"
            )
    message_lines = lint.message.split("\n")
    for line in message_lines:
        lines.append(f"  {line}")
    lines.append("")
    return "\n".join(lines)


def json_format_lint(lint: toolchain.LinterFinding) -> Text:
    """Formats a lint in json for machine parsing.

    Args:
        lint: A linter finding from the toolchain service.

    Returns:
        A correctly formatted json string ready to be displayed to the user.
    """

    def _dictify(original):
        """Turns namedtuple's to dictionaries recursively."""
        # Handle namedtuples
        if isinstance(original, tuple) and hasattr(original, "_asdict"):
            return _dictify(original._asdict())
        # Handle collection types
        elif hasattr(original, "__iter__"):
            # Handle strings
            if isinstance(original, (str, bytes)):
                return original
            # Handle dictionaries
            elif isinstance(original, dict):
                return {k: _dictify(v) for k, v in original.items()}
            # Handle lists, sets, etc.
            else:
                return [_dictify(x) for x in original]
        # Handle PackageInfo objects
        elif isinstance(original, package_info.PackageInfo):
            return original.atom
        # Handle everything else
        return original

    return json.dumps(_dictify(lint))


def get_all_sysroots() -> List[Text]:
    """Gets all available sysroots for both host and boards."""
    host_root = Path(build_target_lib.BuildTarget(None).root)
    roots = [str(host_root)]
    build_dir = host_root / "build"
    for board in os.listdir(build_dir):
        if board != "bin":
            board_root = build_dir / board
            if board_root.is_dir():
                roots.append(str(board_root))
    return roots


def get_arg_parser() -> commandline.ArgumentParser:
    """Creates an argument parser for this script."""
    default_board = cros_build_lib.GetDefaultBoard()
    parser = commandline.ArgumentParser(description=__doc__)

    board_group = parser.add_mutually_exclusive_group()
    board_group.add_argument(
        "-b",
        "--board",
        "--build-target",
        dest="board",
        default=default_board,
        help="The board to emerge packages for",
    )
    board_group.add_argument(
        "--host", action="store_true", help="emerge for host instead of board."
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Fetch lints from previous run without resetting or calling "
        "emerge.",
    )
    parser.add_argument(
        "--differential",
        action="store_true",
        help="only lint lines touched by the last commit",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=sys.stdout,
        help="File to use instead of stdout.",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output lints in JSON format."
    )
    parser.add_argument(
        "--no-clippy",
        dest="clippy",
        action="store_false",
        help="Disable cargo clippy linter.",
    )
    parser.add_argument(
        "--no-tidy",
        dest="tidy",
        action="store_false",
        help="Disable clang tidy linter.",
    )
    parser.add_argument(
        "--no-golint",
        dest="golint",
        action="store_false",
        help="Disable golint linter.",
    )
    parser.add_argument(
        "--iwyu",
        action="store_true",
        help="Enable include-what-you-use linter.",
    )
    parser.add_argument(
        "packages",
        nargs="*",
        help="package(s) to emerge and retrieve lints for",
    )
    return parser


def parse_args(argv: List[str]):
    """Parses arguments in argv and returns the options."""
    parser = get_arg_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()

    # A package must be specified unless we are in fetch-only mode
    if not (opts.fetch_only or opts.packages):
        parser.error("Emerge mode requires specified package(s).")
    if opts.fetch_only and opts.packages:
        parser.error("Cannot specify packages for fetch-only mode.")

    # A board must be specified unless we are in fetch-only mode
    if not (opts.fetch_only or opts.board or opts.host):
        parser.error("Emerge mode requires either --board or --host.")

    return opts


def main(argv: List[str]) -> None:
    cros_build_lib.AssertInsideChroot()
    opts = parse_args(argv)

    if opts.host:
        # BuildTarget interprets None as host target
        build_target = build_target_lib.BuildTarget(None)
    else:
        build_target = build_target_lib.BuildTarget(opts.board)
    packages = parse_packages(build_target, opts.packages)
    package_atoms = [x.atom for x in packages]

    with workon_helper.WorkonScope(build_target, package_atoms):
        build_linter = toolchain.BuildLinter(
            packages, build_target.root, opts.differential
        )
        if opts.fetch_only:
            if opts.host or opts.board:
                roots = [build_target.root]
            else:
                roots = get_all_sysroots()
            lints = []
            for root in roots:
                build_linter.sysroot = root
                lints.extend(
                    build_linter.fetch_findings(
                        use_clippy=opts.clippy,
                        use_tidy=opts.tidy,
                        use_golint=opts.golint,
                        use_iwyu=opts.iwyu,
                    )
                )
        else:
            lints = build_linter.emerge_with_linting(
                use_clippy=opts.clippy,
                use_tidy=opts.tidy,
                use_golint=opts.golint,
                use_iwyu=opts.iwyu,
            )

    if opts.json:
        formatted_output_inner = ",\n".join(json_format_lint(l) for l in lints)
        formatted_output = f"[{formatted_output_inner}]"
    else:
        formatted_output = "\n".join(format_lint(l) for l in lints)

    with file_util.Open(opts.output, "w") as output_file:
        output_file.write(formatted_output)
        if not opts.json:
            output_file.write(f"\nFound {len(lints)} lints.")
        output_file.write("\n")
