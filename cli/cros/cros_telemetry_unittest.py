# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the cros build command."""

from chromite.cli.cros import cros_telemetry
from chromite.lib import cros_test_lib
from chromite.lib.telemetry import config


# pylint: disable=protected-access


class TelemetryCommandTest(cros_test_lib.MockTempDirTestCase):
    """Test class for our TelemetryCommand class."""

    def testEnableTelemetry(self) -> None:
        """Test that telemetry is marked as enabled in cfg."""
        file = self.tempdir / "telemetry.cfg"

        cros_telemetry._enable(config.Config(path=file))

        cfg = config.Config(path=file)
        self.assertTrue(cfg.trace_config.has_enabled())
        self.assertTrue(cfg.trace_config.enabled)
        self.assertEqual("USER", cfg.trace_config.enabled_reason)

    def testDisableTelemetry(self) -> None:
        """Test that telemetry is marked as disabled in cfg."""
        file = self.tempdir / "telemetry.cfg"

        cros_telemetry._disable(config.Config(path=file))

        cfg = config.Config(path=file)
        self.assertTrue(cfg.trace_config.has_enabled())
        self.assertFalse(cfg.trace_config.enabled)
        self.assertEqual("USER", cfg.trace_config.enabled_reason)

    def testToggleDev(self) -> None:
        """Test toggling the development flag."""
        file = self.tempdir / "telemetry.cfg"

        # Off by default.
        cfg = config.Config(path=file)
        self.assertFalse(cfg.trace_config.dev_flag)

        # Enable.
        cros_telemetry._start_dev(config.Config(path=file))
        cfg = config.Config(path=file)
        self.assertTrue(cfg.trace_config.dev_flag)

        # Disable.
        cros_telemetry._stop_dev(config.Config(path=file))
        cfg = config.Config(path=file)
        self.assertFalse(cfg.trace_config.dev_flag)
