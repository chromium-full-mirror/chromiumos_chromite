# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""CR and CQ +2 copybot project commits for downstreaming.

See go/copybot

For CHRE Downstreaming Rotation: go/cros-chre-downstreaming-guide
"""

from chromite.contrib import copybot_downstream
from chromite.contrib.copybot_downstream_config import downstream_argparser
from chromite.lib import constants


class ChreDownstream(copybot_downstream.CopybotDownstream):
    """Class for extending copybot downstreaming class for CHRE."""


def main(args) -> None:
    """Main entry point for CLI."""
    parser = downstream_argparser.generate_copybot_arg_parser(
        project="chre", gob_default=constants.INTERNAL_GOB_INSTANCE
    )
    opts = parser.parse_args(args)
    opts.freeze()
    ChreDownstream(opts).run(opts.cmd)
