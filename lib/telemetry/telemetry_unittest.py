# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the telemetry module."""

import os

from chromite.third_party.opentelemetry import trace as trace_api
from chromite.third_party.opentelemetry.sdk import trace as trace_sdk
import pytest

from chromite.lib import chromite_config
from chromite.lib import telemetry
from chromite.lib.telemetry import config
from chromite.lib.telemetry import trace
from chromite.utils import hostname_util


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

    telemetry.initialize(publish=False)

    assert len(processors) == 0


def test_initialize_to_display_notice_to_user_on_google_host(
    capsys, monkeypatch, telemetry_config
) -> None:
    """Test initialize display notice to user."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.delenv(trace.TRACEPARENT_ENVVAR, raising=False)

    # pylint: disable-next=protected-access
    telemetry._handle_notice(config.Config(telemetry_config))

    cfg = config.Config(telemetry_config)
    assert capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 9


def test_initialize_to_update_enabled_on_count_down_complete(
    capsys, monkeypatch, telemetry_config
) -> None:
    """Test initialize auto enable telemetry on countdown complete."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.delenv(trace.TRACEPARENT_ENVVAR, raising=False)

    cfg = config.Config(telemetry_config)
    cfg.root_config.update(notice_countdown=-1)
    cfg.flush()

    telemetry._handle_notice(cfg)  # pylint: disable=protected-access

    cfg = config.Config(telemetry_config)
    assert not capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "AUTO"


def test_initialize_to_skip_notice_when_trace_enabled_is_present(
    capsys, monkeypatch, telemetry_config
) -> None:
    """Test initialize to skip notice on enabled flag present."""
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=False, reason="USER")
    cfg.flush()

    telemetry._handle_notice(cfg)  # pylint: disable=protected-access

    cfg = config.Config(telemetry_config)
    assert not capsys.readouterr().err.startswith(telemetry.NOTICE)
    assert not cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"


@pytest.mark.skip(reason="Fails when run_tests is instrumented.")
def test_initialize_to_set_parent_from_traceparent_env(
    monkeypatch, telemetry_config
) -> None:
    parent = {
        "traceparent": "00-6e9d1daccc58d878b74c78b363ed2cf8-65d3ef7761438b6f-01"
    }
    monkeypatch.setattr(telemetry, "_INITIALIZED", False)
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(os, "environ", parent)

    cfg = config.Config(telemetry_config)
    cfg.trace_config.update(enabled=True, reason="USER")
    cfg.flush()

    telemetry.initialize(publish=False)

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

    # pylint: disable-next=protected-access
    telemetry._handle_notice(config.Config(telemetry_config))

    cfg = config.Config(telemetry_config)
    assert len(processors) == 0
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 10
