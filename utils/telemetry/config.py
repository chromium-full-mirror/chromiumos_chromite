# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides telemetry configuration utilities."""

import configparser
import os


ROOT_SECTION_KEY = "root"
NOTICE_COUNT_KEY = "notice_count"
ENABLED_KEY = "enabled"
TRACE_SECTION_KEY = "trace"
DEFAULT_CONFIG = {
    ROOT_SECTION_KEY: {NOTICE_COUNT_KEY: 10},
    TRACE_SECTION_KEY: {ENABLED_KEY: True},
}


class TraceConfig:
    """Tracing specific config in Telemetry config."""

    def __init__(self, config):
        self._config = config

    def update(self, enabled: bool):
        self._config.set(TRACE_SECTION_KEY, ENABLED_KEY, str(enabled))

    @property
    def enabled(self) -> bool:
        """Value of trace.enabled property in telemetry.cfg."""

        return self._config[TRACE_SECTION_KEY].getboolean(ENABLED_KEY, True)


class RootConfig:
    """Root configs in Telemetry config."""

    def __init__(self, config):
        self._config = config

    def update(self, notice_count: int):
        self._config.set(ROOT_SECTION_KEY, NOTICE_COUNT_KEY, str(notice_count))

    @property
    def notice_count(self) -> int:
        """Value for root.notice_count property in telemetry.cfg."""

        return self._config[ROOT_SECTION_KEY].getint(NOTICE_COUNT_KEY, 10)


class Config:
    """Telemetry configuration."""

    def __init__(self, path: os.PathLike):
        self._path = path
        self._config = configparser.ConfigParser()

        self._config.read_dict(DEFAULT_CONFIG)
        if not os.path.exists(path):
            self.flush()
        else:
            with open(path, "r", encoding="utf-8") as configfile:
                self._config.read_file(configfile)

        self._trace_config = TraceConfig(self._config)
        self._root_config = RootConfig(self._config)

    def flush(self):
        """Flushes the current config to confi file."""
        with open(self._path, "w", encoding="utf-8") as configfile:
            self._config.write(configfile)

    @property
    def root_config(self) -> RootConfig:
        """The root config in telemetry."""

        return self._root_config

    @property
    def trace_config(self) -> TraceConfig:
        """The trace config in telemetry."""

        return self._trace_config
