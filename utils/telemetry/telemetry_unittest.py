# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the telemetry module."""

from chromite.third_party.opentelemetry.sdk import trace as trace_sdk
from chromite.third_party.opentelemetry.sdk.trace import export

from chromite.utils import hostname_util
from chromite.utils import telemetry
from chromite.utils.telemetry import config
from chromite.utils.telemetry import exporter


_ORIGINAL_ADD_SPAN_PROCESSOR = trace_sdk.TracerProvider.add_span_processor


def _spy_add_span_processor(processors):
    def inner(self, processor):
        processors.append(processor)
        _ORIGINAL_ADD_SPAN_PROCESSOR(self, processor)

    return inner


def test_no_exporter_for_non_google_host(monkeypatch, tmp_path):
    """Test initialize to not add exporters on non google host."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: False)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.trace_config.update(enabled=True, reason="USER")
    cfg.flush()

    telemetry.initialize(config_file, debug=False)

    assert len(processors) == 0


def test_console_exporter_for_non_google_host_on_debug(monkeypatch, tmp_path):
    """Test initialize to print span to console on debug on non google host."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: False)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )
    config_file = tmp_path / "telemetry.cfg"

    telemetry.initialize(config_file, debug=True)

    assert len(processors) == 1
    assert processors[0].span_exporter.__class__ == export.ConsoleSpanExporter


def test_console_exporter_for_google_host_on_debug(monkeypatch, tmp_path):
    """Test initialize to print span to console on debug."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )
    config_file = tmp_path / "telemetry.cfg"

    telemetry.initialize(config_file, debug=True)

    assert len(processors) == 1
    assert processors[0].span_exporter.__class__ == export.ConsoleSpanExporter


def test_initialize_to_display_notice_to_user_on_google_host(
    capsys, monkeypatch, tmp_path
):
    """Test initialize display notice to user."""

    config_file = tmp_path / "telemetry.cfg"
    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    telemetry.initialize(config_file, debug=False)

    cfg = config.Config(config_file)
    assert len(processors) == 0
    assert capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 9


def test_initialize_to_display_notice_and_print_spans_to_user_on_google_host(
    capsys, monkeypatch, tmp_path
):
    """Test initialize display notice to user and print span on debug."""

    config_file = tmp_path / "telemetry.cfg"
    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    telemetry.initialize(config_file, debug=True)

    cfg = config.Config(config_file)
    assert len(processors) == 1
    assert processors[0].span_exporter.__class__ == export.ConsoleSpanExporter
    assert capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 9


def test_initialize_to_update_enabled_on_count_down_complete(
    capsys, monkeypatch, tmp_path
):
    """Test initialize auto enable telemetry on countdown complete."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.root_config.update(notice_countdown=-1)
    cfg.flush()

    telemetry.initialize(config_file, debug=False)

    cfg = config.Config(config_file)
    assert len(processors) == 1
    assert (
        processors[0].span_exporter.__class__ == exporter.ClearcutSpanExporter
    )
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "AUTO"


def test_initialize_to_skip_notice_when_trace_enabled_is_present(
    capsys, monkeypatch, tmp_path
):
    """Test initialize to skip notice on enabled flag present."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.trace_config.update(enabled=False, reason="USER")
    cfg.flush()

    telemetry.initialize(config_file, debug=False)

    cfg = config.Config(config_file)
    assert len(processors) == 0
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert not cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"


def test_initialize_to_enable_telemetry_based_on_optin(
    capsys, monkeypatch, tmp_path
):
    """Test initialize enable telemetry based on optin."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.trace_config.update(enabled=False, reason="AUTO")
    cfg.flush()

    telemetry.initialize(config_file, enable=True)

    cfg = config.Config(config_file)
    assert len(processors) == 1
    assert (
        processors[0].span_exporter.__class__ == exporter.ClearcutSpanExporter
    )
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"


def test_initialize_to_disable_telemetry_based_on_optin(
    capsys, monkeypatch, tmp_path
):
    """Test initialize disable telemetry based on optin."""

    processors = []
    monkeypatch.setattr(hostname_util, "is_google_host", lambda: True)
    monkeypatch.setattr(
        trace_sdk.TracerProvider,
        "add_span_processor",
        _spy_add_span_processor(processors),
    )

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.trace_config.update(enabled=True, reason="AUTO")
    cfg.flush()

    telemetry.initialize(config_file, enable=False)

    cfg = config.Config(config_file)
    assert len(processors) == 0
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert not cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"
