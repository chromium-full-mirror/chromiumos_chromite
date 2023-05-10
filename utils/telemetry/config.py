# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides telemetry configuration utilities."""

import configparser
import os


CONSENT_SECTION_KEY = "consent"
RECORDED_KEY = "recorded"
ENABLED_KEY = "enabled"
TRACE_SECTION_KEY = "trace"
DEFAULT_CONFIG = {
    CONSENT_SECTION_KEY: {RECORDED_KEY: False},
    TRACE_SECTION_KEY: {ENABLED_KEY: False},
}


class TraceConfig:
    """Tracing specific config in Telemetry config."""

    def __init__(self, config):
        self._enabled = config.getboolean(ENABLED_KEY, False)

    @property
    def enabled(self) -> bool:
        """Value of trace.enabled property in telemetry.cfg."""

        return self._enabled


class ConsentConfig:
    """Consent specific config in Telemetry config."""

    def __init__(self, config):
        self._recorded = config.getboolean(RECORDED_KEY, False)

    @property
    def recorded(self) -> bool:
        """Value for consent.recorded property in telemetry.cfg."""

        return self._recorded


class Config:
    """Telemetry configuration."""

    def __init__(self, path: os.PathLike):
        self._config = configparser.ConfigParser()

        self._config.read_dict(DEFAULT_CONFIG)
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as configfile:
                self._config.write(configfile)
        else:
            with open(path, "r", encoding="utf-8") as configfile:
                self._config.read_file(configfile)

        self._trace_config = TraceConfig(self._config[TRACE_SECTION_KEY])
        self._consent_config = ConsentConfig(self._config[CONSENT_SECTION_KEY])

    @property
    def consent_config(self) -> ConsentConfig:
        """The consent config in telemetry."""

        return self._consent_config

    @property
    def trace_config(self) -> TraceConfig:
        """The trace config in telemetry."""

        return self._trace_config
