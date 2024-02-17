# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros telemetry: Manage telemetry options."""

import logging

from chromite.cli import command
from chromite.lib import chromite_config
from chromite.lib import telemetry
from chromite.lib import telemetry_publisher
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
            help="Enable telemetry collection.",
            action="store_true",
        )
        actions.add_argument(
            "--disable",
            help="Disable telemetry collection.",
            action="store_true",
        )
        actions.add_argument(
            "--show",
            help="Show telemetry related information.",
            action="store_true",
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
        actions.add_argument(
            "--publish", action="store_true", help="Publish pending telemetry."
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
        telemetry.initialize(log_traces=self.options.log_telemetry)
        self._do_run()

    @tracer.start_as_current_span("cli.cros.cros_telemetry.main")
    def _do_run(self) -> None:
        span = trace.get_current_span()
        cfg = config.Config(chromite_config.TELEMETRY_CONFIG)
        if self.options.enable:
            span.set_attribute("enable", True)
            cfg.trace_config.update(enabled=True, reason="USER")
            logging.notice("Telemetry enabled successfully.")
        elif self.options.disable:
            span.set_attribute("disable", True)
            cfg.trace_config.update(enabled=False, reason="USER")
            logging.notice("Telemetry disabled successfully.")
        elif self.options.show:
            self._show_telemetry(cfg)
        elif self.options.start_dev:
            cfg.trace_config.set_dev(True)
            logging.notice("Development flag enabled successfully.")
        elif self.options.stop_dev:
            cfg.trace_config.set_dev(False)
            logging.notice("Development flag disabled successfully.")
        elif self.options.regen_ids:
            span.set_attribute("regen_ids", True)
            cfg.trace_config.gen_id(regen=True)
        elif self.options.publish:
            span.set_attribute("publish", True)
            telemetry_publisher.publish()

        cfg.flush()
