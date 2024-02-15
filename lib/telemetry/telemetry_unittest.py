# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the telemetry module."""

import os

from chromite.third_party.opentelemetry import trace as trace_api
from chromite.third_party.opentelemetry.sdk import trace as trace_sdk
from chromite.third_party.opentelemetry.sdk.trace import export
import pytest

from chromite.lib import chromite_config
from chromite.lib import telemetry
from chromite.utils import hostname_util
from chromite.utils.telemetry import config
from chromite.utils.telemetry import exporter


def _spy_add_span_processor(processors):
    def inner(_self, processor) -> None:
        processors.append(processor)

    return inner


@pytest.fixture(name="processors")
def _processors(monkeypatch):
    processors = []
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )
    yield processors


@pytest.fixture(name="telemetry_config")
def _telemetry_config(monkeypatch, tmp_path):
    """Create empty telemetry config file and patch chromite_config constant."""
    config_file = tmp_path / "telemetry.cfg"
    monkeypatch.setattr(chromite_config, "TELEMETRY_CONFIG", config_file)
    yield config_file


def test_no_exporter_for_non_google_host(
    monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize to not add exporters on non google host."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: False)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=True, reason="USER")
    cfg.flush()

    telemetry.initialize()

    assert len(processors) == 0


def test_console_exporter_for_non_google_host_on_debug(
    monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize to print span to console on debug on non google host."""
    del telemetry_config
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: False)

    telemetry.initialize(log_traces=True)

    assert len(processors) == 1
    assert processors[0].span_exporter.__class__ == export.ConsoleSpanExporter


def test_console_exporter_for_google_host_on_debug(
    monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize to print span to console on debug."""
    del telemetry_config
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    telemetry.initialize(log_traces=True)

    assert len(processors) == 1
    assert processors[0].span_exporter.__class__ == export.ConsoleSpanExporter


def test_initialize_to_display_notice_to_user_on_google_host(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize display notice to user."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    telemetry.initialize()

    cfg = config.Config(telemetry_config)
    assert len(processors) == 0
    assert capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 9


def test_initialize_to_display_notice_and_print_spans_to_user_on_google_host(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize display notice to user and print span on debug."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    telemetry.initialize(log_traces=True)

    cfg = config.Config(telemetry_config)
    assert len(processors) == 1
    assert processors[0].span_exporter.__class__ == export.ConsoleSpanExporter
    assert capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 9


def test_initialize_to_update_enabled_on_count_down_complete(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize auto enable telemetry on countdown complete."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    cfg = config.Config(telemetry_config)
    cfg.root_config.update(notice_countdown=-1)
    cfg.flush()

    telemetry.initialize()

    cfg = config.Config(telemetry_config)
    assert len(processors) == 1
    assert (
        processors[0].span_exporter.__class__ == exporter.ClearcutSpanExporter
    )
    assert not capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "AUTO"


def test_initialize_to_skip_notice_when_trace_enabled_is_present(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize to skip notice on enabled flag present."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=False, reason="USER")
    cfg.flush()

    telemetry.initialize()

    cfg = config.Config(telemetry_config)
    assert len(processors) == 0
    assert not capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert not cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"


def test_initialize_to_enable_telemetry_based_on_optin(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize enable telemetry based on optin."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=False, reason="AUTO")
    cfg.flush()

    telemetry.initialize(enable=True)

    cfg = config.Config(telemetry_config)
    assert len(processors) == 1
    assert (
        processors[0].span_exporter.__class__ == exporter.ClearcutSpanExporter
    )
    assert not capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"


def test_initialize_to_disable_telemetry_based_on_optin(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize disable telemetry based on optin."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=True, reason="AUTO")
    cfg.flush()

    telemetry.initialize(enable=False)

    cfg = config.Config(telemetry_config)
    assert len(processors) == 0
    assert not capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert not cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"


def test_initialize_to_set_parent_from_traceparent_env(
    monkeypatch, telemetry_config
) -> None:
    parent = {
        "traceparent": "00-6e9d1daccc58d878b74c78b363ed2cf8-65d3ef7761438b6f-01"
    }
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(os, "environ", parent)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=False, reason="USER")
    cfg.flush()

    telemetry.initialize()

    with trace_api.get_tracer(__name__).start_as_current_span("test") as span:
        ctx = span.get_span_context()
        assert (
            trace_api.format_trace_id(ctx.trace_id)
            == "6e9d1daccc58d878b74c78b363ed2cf8"
        )
        assert (
            trace_api.format_span_id(span.parent.span_id) == "65d3ef7761438b6f"
        )


def test_initialize_to_skip_notice_if_tracecontext_present_in_env(
    capsys, monkeypatch, processors, telemetry_config
) -> None:
    """Test initialize to skip notice if run with tracecontext."""
    parent = {
        "traceparent": "00-6e9d1daccc58d878b74c78b363ed2cf8-65d3ef7761438b6f-01"
    }
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(os, "environ", parent)

    telemetry.initialize()

    cfg = config.Config(telemetry_config)
    assert len(processors) == 0
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 10
