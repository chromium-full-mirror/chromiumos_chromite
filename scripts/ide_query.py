# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provide build information for language support in Cider G."""

from pathlib import Path
from typing import List

from chromite.lib import commandline
from chromite.lib import cros_build_lib


def parse_args(argv: List[str]) -> commandline.ArgumentParser:
    """Parse command-line args."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_bool_argument(
        "--perform-build",
        default=False,
        enabled_desc="Actually perform the build, including any generated "
        "prerequisite files.",
        disabled_desc="Return the GeneratedFile results for a previously "
        "completed build, even if those results are stale.",
    )
    parser.add_argument(
        "--build-target",
        "-b",
        required=True,
        help="The build target to generate references for.",
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Output directory, relative to the repository root, into which "
        "generated files will be copied.",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> None:
    cros_build_lib.AssertOutsideChroot()
    args = parse_args(argv)
    raise NotImplementedError(args)
