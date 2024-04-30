# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The chromite telemetry library."""

import logging
import os
import sys
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from chromite.lib.telemetry import config


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

_INITIALIZED = False


def initialize(publish: bool = True) -> None:
    """Initialize chromite telemetry.

    The function accepts a config path and handles the initialization of
    chromite telemetry. It also handles the user enrollment. A notice is
    displayed to the user if no selection is made regarding telemetry enrollment
    until the countdown runs out and the user is auto enrolled.

    Examples:
        opts = parse_args(argv)
        telemetry.initialize()

    Args:
        publish: Fork background process to publish telemetry.
    """
    global _INITIALIZED  # pylint: disable=global-statement
    if _INITIALIZED:
        return
    _INITIALIZED = True

    # Importing this inside the function to avoid performance overhead from the
    # global package import.
    from chromite.lib import chromite_config
    from chromite.lib.telemetry import config
    from chromite.lib.telemetry import trace
    from chromite.utils import hostname_util

    if not hostname_util.is_google_host():
        return

    if not chromite_config.initialize():
        # Error initializing as non-root user, e.g. b/327285178.
        # This is weird, bail, we're probably not losing out on much anyway.
        # TODO(build): Figure out root cause and document/handle cases.
        logging.debug("Skipping telemetry initialization.")
        return

    cfg = config.Config(chromite_config.TELEMETRY_CONFIG)

    _handle_notice(cfg)
    _refresh_configs(cfg)

    # Publish pending telemetry in a background process.
    if publish:
        _fork_and_publish()

    trace.initialize(
        enabled=cfg.trace_config.enabled,
        development_mode=cfg.trace_config.dev_flag,
        user_uuid=cfg.trace_config.user_uuid(),
    )


def _handle_notice(cfg: "config.Config") -> None:
    """Print the telemetry notice and update counter as needed."""
    from chromite.lib.telemetry import trace

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


def _refresh_configs(cfg: "config.Config") -> None:
    """Do config updates and flush."""
    if cfg.trace_config.gen_id():
        cfg.flush()


def _fork_and_publish() -> None:
    """Fork a (short-lived) daemon publishing process."""
    if os.environ.get("CHROMITE_INSIDE_PYTEST") == "1":
        # Skip in tests.
        return

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
    script = constants.CHROMITE_SCRIPTS_DIR / "publish_telemetry"
    os.execv(script, [script, "--debug"])
