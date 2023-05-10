# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the telemetry config."""


import configparser

from chromite.lib import cros_test_lib
from chromite.utils.telemetry import config


class ConfigTest(cros_test_lib.TempDirTestCase):
    """Test Config class."""

    def test_create_missing_config_file(self):
        """Test Config to create missing config file."""

        path = self.tempdir / "telemetry.cfg"
        cfg = config.Config(path)

        self.assertFileContents(
            path, "[consent]\nrecorded = False\n\n[trace]\nenabled = False\n\n"
        )
        self.assertFalse(cfg.trace_config.enabled)
        self.assertFalse(cfg.consent_config.recorded)

    def test_load_config_file(self):
        """Test Config to load config file."""

        path = "telemetry.cfg"
        self.WriteTempFile(
            path, "[consent]\nrecorded = True\n\n[trace]\nenabled = True\n\n"
        )

        path = self.tempdir / path
        cfg = config.Config(path)

        self.assertTrue(cfg.trace_config.enabled)
        self.assertTrue(cfg.consent_config.recorded)


def test_default_trace_config():
    """Test TraceConfig to load default values."""
    cfg = configparser.ConfigParser()
    cfg["a"] = {}
    trace_config = config.TraceConfig(cfg["a"])

    assert not trace_config.enabled


def test_trace_config():
    """Test TraceConfig to instantiate from passed dict."""
    cfg = configparser.ConfigParser()
    cfg[config.TRACE_SECTION_KEY] = {config.ENABLED_KEY: True}
    trace_config = config.TraceConfig(cfg[config.TRACE_SECTION_KEY])

    assert trace_config.enabled
