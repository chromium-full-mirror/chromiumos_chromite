# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the telemetry module."""


from chromite.third_party.opentelemetry import trace
from chromite.third_party.opentelemetry.sdk import trace as trace_sdk
import pytest

from chromite.utils import telemetry
from chromite.utils.telemetry import config
from chromite.utils.telemetry import utils


def test_initialize_be_disabled_for_non_google_host(monkeypatch, tmp_path):
    """Test initialize to make no changes if not google host."""

    monkeypatch.setattr(utils, "is_google_host", lambda: False)
    config_file = tmp_path / "telemetry.cfg"

    telemetry.initialize(config_file)

    assert trace.get_tracer_provider().__class__ == trace.ProxyTracerProvider


def test_initialize_to_make_no_changes_for_google_host(monkeypatch, tmp_path):
    """Test initialize to make no changes if not google host."""

    monkeypatch.setattr(utils, "is_google_host", lambda: True)
    config_file = tmp_path / "telemetry.cfg"

    telemetry.initialize(config_file)

    assert trace.get_tracer_provider().__class__ == trace.ProxyTracerProvider


@pytest.mark.skip("(b/266131531): remove when ready for launch")
def test_initialize_to_display_notice_to_user(capsys, monkeypatch, tmp_path):
    """Test initialize display notice to user."""

    config_file = tmp_path / "telemetry.cfg"
    monkeypatch.setattr(utils, "is_google_host", lambda: True)

    telemetry.initialize(config_file)

    cfg = config.Config(config_file)
    assert trace.get_tracer_provider().__class__ == trace.ProxyTracerProvider
    assert capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.root_config.notice_countdown == 9


@pytest.mark.skip("(b/266131531): remove when ready for launch")
def test_initialize_to_update_enabled_on_count_down_complete(
    capsys, monkeypatch, tmp_path
):
    """Test initialize auto enable telemetry on countdown complete."""

    monkeypatch.setattr(utils, "is_google_host", lambda: True)

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.root_config.update(notice_countdown=0)
    cfg.flush()

    telemetry.initialize(config_file)

    cfg = config.Config(config_file)
    assert trace.get_tracer_provider().__class__ == trace_sdk.TracerProvider
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "AUTO"


@pytest.mark.skip("(b/266131531): remove when ready for launch")
def test_initialize_to_skip_notice_when_trace_enabled_is_present(
    capsys, monkeypatch, tmp_path
):
    """Test initialize to skip notice on enabled flag present."""

    monkeypatch.setattr(utils, "is_google_host", lambda: True)

    config_file = tmp_path / "telemetry.cfg"
    cfg = config.Config(config_file)
    cfg.trace_config.update(enabled=False, reason="USER")
    cfg.flush()

    telemetry.initialize(config_file)

    cfg = config.Config(config_file)
    assert trace.get_tracer_provider().__class__ == trace.ProxyTracerProvider
    assert not capsys.readouterr().out.startswith(telemetry.NOTICE)
    assert not cfg.trace_config.enabled
    assert cfg.trace_config.enabled_reason == "USER"
