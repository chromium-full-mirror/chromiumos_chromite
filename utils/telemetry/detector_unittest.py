# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The tests for resource detector classes."""

import getpass
import os
from pathlib import Path
import platform

from opentelemetry.sdk import resources
import psutil

from chromite.utils.telemetry import detector


def mock_exists(path: os.PathLike, val: bool):
    """Mock Path.exists for specified path."""

    exists = Path.exists

    def _mock_exists(*args, **kwargs):
        if args[0] == path:
            return val
        return exists(*args, **kwargs)

    return _mock_exists


def mock_read_text(path: os.PathLike, val: str):
    """Mock Path.read_text for specified path."""

    real_read_text = Path.read_text

    def _mock_read_text(*args, **kwargs):
        if args[0] == path:
            return val
        return real_read_text(*args, **kwargs)

    return _mock_read_text


def test_process_info_capture():
    """Test that ProcessDetector captures correct process info."""
    p = psutil.Process()
    env_var = list(p.environ().keys())[0]

    d = detector.ProcessDetector(allowed_env=[env_var])
    attrs = d.detect().attributes

    assert attrs[resources.PROCESS_PID] == p.pid
    assert attrs[detector.PROCESS_CWD] == os.getcwd()
    assert attrs[resources.PROCESS_COMMAND] == p.cmdline()[0]
    assert attrs[resources.PROCESS_COMMAND_ARGS] == tuple(p.cmdline()[1:])
    assert attrs[resources.PROCESS_EXECUTABLE_NAME] == p.name()
    assert attrs[resources.PROCESS_EXECUTABLE_PATH] == p.exe()
    assert attrs[f"process.env.{env_var}"] == p.environ()[env_var]


def test_system_info_captured(monkeypatch):
    """Test that SystemDetector captures the correct system info."""

    monkeypatch.setattr(getpass, "getuser", lambda: "someuser")
    monkeypatch.setattr(Path, "exists", mock_exists(detector.DMI_PATH, True))
    monkeypatch.setattr(
        Path,
        "read_text",
        mock_read_text(detector.DMI_PATH, detector.GCE_DMI),
    )

    d = detector.SystemDetector()
    attrs = d.detect().attributes

    assert attrs[detector.CPU_COUNT] == psutil.cpu_count()
    assert attrs[detector.HOST_TYPE] == "Google Compute Engine"
    assert attrs[detector.MEMORY_TOTAL] == psutil.virtual_memory().total
    assert attrs[detector.MEMORY_SWAP_TOTAL] == psutil.swap_memory().total
    assert attrs[detector.OS_NAME] == os.name
    assert attrs[resources.OS_TYPE] == platform.system()
    assert attrs[resources.OS_DESCRIPTION] == platform.platform()
    assert attrs[detector.CPU_ARCHITECTURE] == platform.machine()
    assert attrs[detector.CPU_NAME] == platform.processor()


def test_system_info_to_capture_host_type_bot(monkeypatch):
    """Test that SystemDetector captures host type as chromeos-bot."""

    monkeypatch.setattr(getpass, "getuser", lambda: "chromeos-bot")
    monkeypatch.setattr(Path, "exists", mock_exists(detector.DMI_PATH, True))
    monkeypatch.setattr(
        Path,
        "read_text",
        mock_read_text(detector.DMI_PATH, detector.GCE_DMI),
    )

    d = detector.SystemDetector()
    attrs = d.detect().attributes

    assert attrs[detector.CPU_COUNT] == psutil.cpu_count()
    assert attrs[detector.HOST_TYPE] == "chromeos-bot"
    assert attrs[detector.MEMORY_TOTAL] == psutil.virtual_memory().total
    assert attrs[detector.MEMORY_SWAP_TOTAL] == psutil.swap_memory().total
    assert attrs[detector.OS_NAME] == os.name
    assert attrs[resources.OS_TYPE] == platform.system()
    assert attrs[resources.OS_DESCRIPTION] == platform.platform()
    assert attrs[detector.CPU_ARCHITECTURE] == platform.machine()
    assert attrs[detector.CPU_NAME] == platform.processor()


def test_system_info_to_capture_host_type_from_dmi(monkeypatch):
    """Test that SystemDetector captures dmi product name as host type."""

    monkeypatch.setattr(getpass, "getuser", lambda: "someuser")
    monkeypatch.setattr(Path, "exists", mock_exists(detector.DMI_PATH, True))
    monkeypatch.setattr(
        Path, "read_text", mock_read_text(detector.DMI_PATH, "SomeId")
    )

    d = detector.SystemDetector()
    attrs = d.detect().attributes

    assert attrs[detector.CPU_COUNT] == psutil.cpu_count()
    assert attrs[detector.HOST_TYPE] == "SomeId"
    assert attrs[detector.MEMORY_TOTAL] == psutil.virtual_memory().total
    assert attrs[detector.MEMORY_SWAP_TOTAL] == psutil.swap_memory().total
    assert attrs[detector.OS_NAME] == os.name
    assert attrs[resources.OS_TYPE] == platform.system()
    assert attrs[resources.OS_DESCRIPTION] == platform.platform()
    assert attrs[detector.CPU_ARCHITECTURE] == platform.machine()
    assert attrs[detector.CPU_NAME] == platform.processor()


def test_system_info_to_capture_host_type_unknown(monkeypatch):
    """Test that SystemDetector captures host type as UNKNOWN."""

    monkeypatch.setattr(Path, "exists", mock_exists(detector.DMI_PATH, False))

    d = detector.SystemDetector()
    attrs = d.detect().attributes

    assert attrs[detector.CPU_COUNT] == psutil.cpu_count()
    assert attrs[detector.HOST_TYPE] == "UNKNOWN"
    assert attrs[detector.MEMORY_TOTAL] == psutil.virtual_memory().total
    assert attrs[detector.MEMORY_SWAP_TOTAL] == psutil.swap_memory().total
    assert attrs[detector.OS_NAME] == os.name
    assert attrs[resources.OS_TYPE] == platform.system()
    assert attrs[resources.OS_DESCRIPTION] == platform.platform()
    assert attrs[detector.CPU_ARCHITECTURE] == platform.machine()
    assert attrs[detector.CPU_NAME] == platform.processor()
