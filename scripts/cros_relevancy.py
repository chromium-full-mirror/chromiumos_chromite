# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A simple CLI for querying build relevancy based on file paths.

This is intended for debugging and developement of the relevancy checker.  Bots
don't actually call this command, they instead go through the
chromite.api.Relevancy/GetRelevantBuildTargets Build API endpoint.
"""

import logging
from pathlib import Path
from typing import Iterator, List, Optional

from chromite.lib import build_query
from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.service import relevancy


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)

    return parser


def parse_arguments(argv: List[str]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()
    return opts


def _get_all_build_targets() -> Iterator[build_target_lib.BuildTarget]:
    """Get all build targets."""
    for board in build_query.Board.find_all():
        yield build_target_lib.BuildTarget(board.name, public=False)


def main(argv: Optional[List[str]]) -> Optional[int]:
    """Main."""
    opts = parse_arguments(argv)
    paths = [x.resolve().relative_to(constants.SOURCE_ROOT) for x in opts.paths]
    for build_target, reason in relevancy.get_relevant_build_targets(
        _get_all_build_targets(), paths
    ):
        logging.info("%s (Reason: %s)", build_target.board, reason)
