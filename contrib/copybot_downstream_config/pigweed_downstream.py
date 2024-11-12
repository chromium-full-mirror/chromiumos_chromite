# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""CR and CQ +2 copybot project commits for downstreaming.

See go/copybot

For Pigweed Downstreaming Rotation: go/pigweed-downstreaming-guide
"""

from chromite.contrib import copybot_downstream
from chromite.contrib.copybot_downstream_config import downstream_argparser


class PigweedDownstream(copybot_downstream.CopybotDownstream):
    """Class for extending copybot downstreaming class for pigweed."""


def main(args) -> None:
    """Main entry point for CLI."""
    parser = downstream_argparser.generate_copybot_arg_parser("pigweed")
    opts = parser.parse_args(args)
    PigweedDownstream(opts).run(opts.cmd)
