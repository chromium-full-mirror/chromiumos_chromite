# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The chromite telemetry library."""

import os
import sys
from typing import Optional

from chromite.utils.telemetry import config
from chromite.utils.telemetry import trace


NOTICE = """
To help improve the quality of this product, we collect de-identified usage data
and stacktraces (when crashes are encountered). You may choose to opt out of this
collection at any time by running the following command

                cros telemetry --disable

In order to opt-in, please run `cros telemetry --enable`. The telemetry will be
automatically enabled after the notice has been displayed for 10 times.
"""

SERVICE_NAME = "chromite"
# The version keeps track of telemetry changes in chromite. Update this each
# time there are changes to `chromite.utils.telemetry` or telemetry collection
# changes in chromite.
TELEMETRY_VERSION = "3"


def initialize(
    config_file: os.PathLike, debug: bool = False, enable: Optional[bool] = None
):
    """Initialize chromite telemetry.

    The function accepts a config path and handles the initialization of
    chromite telemetry. It also handles the user enrollment. A notice is
    displayed to the user if no selection is made regarding telemetry enrollment
    until the countdown runs out and the user is auto enrolled.

    Examples:
        from chromite.lib import chromite_config

        opts = parse_args(argv)
        chromite_config.initialize()
        telemetry.initialize(chromite_config.TELEMETRY_CONFIG, opts.debug)

    Args:
        config_file: The path to the telemetry cfg to load for initializing
        the telemetry.
        debug: Indicates if the traces should be exported to console.
        enable: Indicates if the traces should be enabled.
    """
    cfg = config.Config(config_file)
    if enable is not None:
        cfg.trace_config.update(enabled=enable, reason="USER")
        cfg.flush()

    if (
        not cfg.trace_config.has_enabled()
        and trace.TRACEPARENT_ENVVAR not in os.environ
    ):
        if cfg.root_config.notice_countdown > -1:
            print(NOTICE, file=sys.stderr)
            cfg.root_config.update(
                notice_countdown=cfg.root_config.notice_countdown - 1
            )
        else:
            cfg.trace_config.update(enabled=True, reason="AUTO")

        cfg.flush()

    trace.initialize(enabled=cfg.trace_config.enabled, debug=debug)
