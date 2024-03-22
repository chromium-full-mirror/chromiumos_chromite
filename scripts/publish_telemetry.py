# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Publish telemetry."""

from typing import List, Optional

from chromite.lib import commandline
from chromite.lib import telemetry
from chromite.lib import telemetry_publisher


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)

    return parser


def parse_arguments(argv: Optional[List[str]]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)

    opts.Freeze()
    return opts


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    # We still want --help and the logging options.
    parse_arguments(argv)

    if not telemetry_publisher.can_publish():
        # Early return to allow initializing telemetry only when publishing.
        return

    # Enable telemetry here so the telemetry is limited to actual publishes.
    # This is largely just a QOL improvement for browsing telemetry locally
    # when every command is generating telemetry.
    # Disable publish to prevent fork bomb.
    telemetry.initialize(publish=False)
    telemetry_publisher.publish()
