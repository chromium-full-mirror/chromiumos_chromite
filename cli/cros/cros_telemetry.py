# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros telemetry: Manage telemetry options."""

import logging

from chromite.cli import command
from chromite.lib import chromite_config
from chromite.utils.telemetry import config


@command.command_decorator("telemetry")
class TelemetryCommand(command.CliCommand):
    """Manage telemetry related options."""

    @classmethod
    def AddParser(cls, parser):
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
            action="store_true",
            help="Set the development attribute for all spans. Allows tagging "
            "spans as in development so they can be easily filtered out.",
        )
        actions.add_argument(
            "--stop-dev",
            action="store_true",
            help="Stop setting the development attribute.",
        )
        actions.add_argument(
            "--regen-ids",
            action="store_true",
            help="Regenerate UUIDs.",
        )

    @staticmethod
    def _show_telemetry(cfg: config.Config):
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

    def Run(self):
        """Run cros telemetry."""
        chromite_config.initialize()
        cfg = config.Config(chromite_config.TELEMETRY_CONFIG)

        if self.options.enable:
            cfg.trace_config.update(enabled=True, reason="USER")
            logging.notice("Telemetry enabled successfully.")
        elif self.options.disable:
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
            cfg.trace_config.gen_id(regen=True)

        cfg.flush()
