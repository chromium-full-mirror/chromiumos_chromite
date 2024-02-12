# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The chromite telemetry library."""

import os
import sys
from typing import Optional


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
    log_traces: bool = False,
    enable: Optional[bool] = None,
    publish: bool = False,
) -> None:
    """Initialize chromite telemetry.

    The function accepts a config path and handles the initialization of
    chromite telemetry. It also handles the user enrollment. A notice is
    displayed to the user if no selection is made regarding telemetry enrollment
    until the countdown runs out and the user is auto enrolled.

    Examples:
        opts = parse_args(argv)
        telemetry.initialize(opts.log_telemetry)

    Args:
        log_traces: Indicates if the traces should be exported to console.
        enable: Indicates if the traces should be enabled.
        publish: Fork background process to publish telemetry.
    """
    # Importing this inside the function to avoid performance overhead from the
    # global package import.
    from chromite.lib import chromite_config
    from chromite.lib.telemetry import config
    from chromite.lib.telemetry import trace

    chromite_config.initialize()
    cfg = config.Config(chromite_config.TELEMETRY_CONFIG)
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

    if cfg.trace_config.enabled:
        cfg.trace_config.gen_id()
        cfg.flush()

    # Publish pending telemetry in a background process.
    if publish:
        _fork_and_publish()

    trace.initialize(
        enabled=cfg.trace_config.enabled,
        log_traces=log_traces,
        development_mode=cfg.trace_config.dev_flag,
        user_uuid=cfg.trace_config.user_uuid(),
        batch=cfg.trace_config.batch,
    )


def _fork_and_publish():
    """Fork a (short-lived) daemon publishing process."""
    if os.fork():
        # Parent, return to other tasks.
        return

    from chromite.lib import constants

    # Use a safe cwd.
    os.chdir(constants.SOURCE_ROOT)
    # Clear session id to clear controlling TTY.
    os.setsid()
    # Make sure we have access to all files it creates.
    os.umask(0)

    # Second fork to make sure we can't get a controlling TTY.
    if os.fork():
        sys.exit()

    import datetime

    from chromite.lib import osutils
    from chromite.lib import path_util

    # Set up a log file. Timestamp with millisecond precision.
    now = datetime.datetime.now().isoformat()
    log_file = path_util.get_log_dir() / "telemetry" / ".publisher_logs" / now
    osutils.SafeMakedirsNonRoot(log_file.parent)

    # Get rid of stdin, we don't need it anymore.
    with open("/dev/null", "r", encoding="utf-8") as dev_null:
        os.dup2(dev_null.fileno(), sys.stdin.fileno())

    # Redirect stdout and stderr to the log file. Start with stderr so errors
    # changing stdout go to the log file.
    sys.stderr.flush()
    sys.stdout.flush()
    # It's probably unique, but append just in case.
    with log_file.open("a+", encoding="utf-8") as f:
        os.dup2(f.fileno(), sys.stderr.fileno())
        os.dup2(f.fileno(), sys.stdout.fileno())

    # Now we publish.
    os.execvp("cros", ["cros", "telemetry", "--publish", "--debug"])
