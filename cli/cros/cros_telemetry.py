# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros telemetry: Manage telemetry options."""

import logging

from chromite.cli import command
from chromite.lib import chromite_config
from chromite.lib.telemetry import config
from chromite.lib.telemetry import trace


tracer = trace.get_tracer(__name__)


@command.command_decorator("telemetry")
class TelemetryCommand(command.CliCommand):
    """Manage telemetry related options."""

    EPILOG = """
Telemetry Overview:

The CrOS Build Team collects telemetry to help understand how our tooling is
being used, where there might be performance or usability issues, and to get
stronger signals and information about bugs developers might be experiencing.
Data is only collected from Googlers.

The telemetry is not used to track things like individual user "productivity".
Data that identifies the user is anonymized, e.g. /home/ldap -> /home/<user>.
We do generate and collect a generated UUID for each user, but it is not able to
identify specific users, just identify commands as being run by the same user.
It is automatically cycled weekly, and helps us to understand overall workflows.
For example, it allows us to understand which commands are used together and the
latency between commands. This helps to understand things like which commands
are part of tight development workflows, and which ones might be prompting
context switching.

What we collect:
* Chromite commands run and the arguments passed.
* Performance data.
* Error details, e.g. messages and tracebacks.
* Data about the ChromiumOS checkout itself.
* Machine specs, e.g. CPU count, amount of memory.
"""

    @classmethod
    def AddParser(cls, parser) -> None:
        super(cls, TelemetryCommand).AddParser(parser)
        actions = parser.add_mutually_exclusive_group(required=True)
        actions.add_argument(
            "--enable",
            action="store_true",
            help="Enable telemetry collection.",
        )
        actions.add_argument(
            "--disable",
            action="store_true",
            help="Disable telemetry collection.",
        )
        actions.add_argument(
            "--show",
            action="store_true",
            help="Show telemetry related information.",
        )
        actions.add_argument(
            "--start-dev",
            "--enable-dev",
            action="store_true",
            dest="start_dev",
            help="Set the development attribute for all spans. Allows tagging "
            "spans as in development so they can be easily filtered out. This "
            "is intended to be used by devs working on telemetry itself.",
        )
        actions.add_argument(
            "--stop-dev",
            "--disable-dev",
            action="store_true",
            dest="stop_dev",
            help="Stop setting the development attribute.",
        )
        actions.add_argument(
            "--regen-ids",
            action="store_true",
            help="Regenerate UUIDs.",
        )

    @staticmethod
    def _show_telemetry(cfg: config.Config) -> None:
        if cfg.trace_config.has_enabled():
            print(f"{config.ENABLED_KEY} = {cfg.trace_config.enabled}")
            print(
                f"{config.ENABLED_REASON_KEY} = "
                f"{cfg.trace_config.enabled_reason}"
            )
            if cfg.trace_config.dev_flag:
                print(f"{config.KEY_DEV} = True")
        else:
            print(f"notice_countdown = {cfg.root_config.notice_countdown}")

    def Run(self) -> None:
        """Run cros telemetry."""
        self._do_run()

    @tracer.start_as_current_span("cli.cros.cros_telemetry.main")
    def _do_run(self) -> None:
        span = trace.get_current_span()
        chromite_config.initialize()
        cfg = config.Config(chromite_config.TELEMETRY_CONFIG)
        if self.options.enable:
            span.set_attribute("enable", True)
            _enable(cfg)
        elif self.options.disable:
            span.set_attribute("disable", True)
            _disable(cfg)
        elif self.options.show:
            self._show_telemetry(cfg)
        elif self.options.start_dev:
            _start_dev(cfg)
        elif self.options.stop_dev:
            _stop_dev(cfg)
        elif self.options.regen_ids:
            span.set_attribute("regen_ids", True)
            _regen_ids(cfg)


def _disable(cfg) -> None:
    """Disable telemetry."""
    cfg.trace_config.update(enabled=False, reason="USER")
    cfg.flush()
    logging.notice("Telemetry disabled successfully.")


def _enable(cfg) -> None:
    """Enable telemetry."""
    cfg.trace_config.update(enabled=True, reason="USER")
    cfg.flush()
    logging.notice("Telemetry enabled successfully.")


def _regen_ids(cfg) -> None:
    """Regen UUID(s)."""
    cfg.trace_config.gen_id(regen=True)
    cfg.flush()
    logging.notice("Regenerated IDs.")


def _start_dev(cfg) -> None:
    """Enable telemetry development flag (spans ignored in queries)."""
    cfg.trace_config.set_dev(True)
    cfg.flush()
    logging.notice("Development flag enabled successfully.")


def _stop_dev(cfg) -> None:
    """Disable telemetry development flag."""
    cfg.trace_config.set_dev(False)
    cfg.flush()
    logging.notice("Development flag disabled successfully.")
