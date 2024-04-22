# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the "cros cron" command."""

import functools
from pathlib import Path
from typing import List
from unittest import mock

import pytest

from chromite.cli.cros import cros_cron
from chromite.lib import commandline
from chromite.lib import cros_sdk_lib
from chromite.lib import path_util


# pylint is unaware of pytest fixtures.
# pylint: disable=redefined-outer-name

FAKE_REPO_CHECKOUT = path_util.CheckoutInfo(
    path_util.CheckoutType.REPO, "/path/to/source", ""
)
FAKE_CITC_CHECKOUT = path_util.CheckoutInfo(
    path_util.CheckoutType.CITC, "/path/to/source", ""
)


def test_prefetch_repo(run_mock) -> None:
    """Test the prefetch_repo function."""
    cros_cron.prefetch_repo(FAKE_REPO_CHECKOUT)
    run_mock.assertCommandCalled(
        [
            Path("/path/to/source/.repo/repo/repo"),
            "sync",
            "--optimized-fetch",
            "--network-only",
        ],
        cwd="/path/to/source",
    )


def test_prefetch_sdks(tmp_path: Path) -> None:
    """Test the prefetch_sdks function."""
    prefetch_versions = {"1.2.3", "4.5.6"}
    with mock.patch.object(
        cros_sdk_lib,
        "get_prefetch_sdk_versions",
        return_value=prefetch_versions,
    ), mock.patch.object(
        cros_sdk_lib, "fetch_remote_tarballs"
    ) as fetch_remote_tarballs:
        cros_cron.prefetch_sdks(tmp_path)
        fetch_remote_tarballs.assert_any_call(
            tmp_path / "sdks",
            [cros_sdk_lib.get_sdk_tarball_url("1.2.3")],
            prefetch_versions=prefetch_versions,
        )
        fetch_remote_tarballs.assert_any_call(
            tmp_path / "sdks",
            [cros_sdk_lib.get_sdk_tarball_url("4.5.6")],
            prefetch_versions=prefetch_versions,
        )


def _main(args: List[str]) -> int:
    """Helper to call cros cron with options."""
    parser = commandline.ArgumentParser()
    cros_cron.CronCommand.AddParser(parser)
    try:
        opts = parser.parse_args(args)
    except SystemExit as e:
        return e.code or 0
    cros_cron.CronCommand.ProcessOptions(parser, opts)
    opts.Freeze()
    cmd = cros_cron.CronCommand(opts)
    try:
        return cmd.Run() or 0
    except SystemExit as e:
        return e.code or 0


def test_cros_cron_run(tmp_path: Path, outside_sdk) -> None:
    """Test the "cros cron run" command."""
    del outside_sdk
    with mock.patch.object(
        path_util, "DetermineCheckout", return_value=FAKE_REPO_CHECKOUT
    ), mock.patch.object(
        cros_cron, "prefetch_repo"
    ) as prefetch_repo, mock.patch.object(
        cros_cron, "prefetch_sdks"
    ) as prefetch_sdks:
        _main(["run", "--cache-dir", str(tmp_path)])
        prefetch_repo.assert_called_once_with(FAKE_REPO_CHECKOUT)
        prefetch_sdks.assert_called_once_with(tmp_path)


def test_cros_cron_run_citc(tmp_path: Path, outside_sdk) -> None:
    """Test the "cros cron run" command for a CitC checkout."""
    del outside_sdk
    with mock.patch.object(
        path_util, "DetermineCheckout", return_value=FAKE_CITC_CHECKOUT
    ), mock.patch.object(
        cros_cron, "prefetch_repo"
    ) as prefetch_repo, mock.patch.object(
        cros_cron, "prefetch_sdks"
    ) as prefetch_sdks:
        _main(["run", "--cache-dir", str(tmp_path)])
        prefetch_repo.assert_not_called()
        prefetch_sdks.assert_called_once_with(tmp_path)


@pytest.fixture
def has_systemd(monkeypatch: pytest.MonkeyPatch):
    """Fixture which mocks out the system having/not having systemd."""

    def factory(enable_systemd: bool) -> None:
        monkeypatch.setattr(
            cros_cron,
            "detect_systemd",
            functools.partial(lambda x: x, enable_systemd),
        )

    return factory


def test_cros_cron_enable(run_mock, has_systemd, outside_sdk):
    """Test the "cros cron enable" command."""
    del outside_sdk
    has_systemd(True)
    _main(["enable"])
    timer_unit, service_unit = cros_cron.get_systemd_units()
    run_mock.assertCommandCalled(["systemctl", "enable", "--user", timer_unit])
    run_mock.assertCommandCalled(["systemctl", "start", "--user", timer_unit])
    run_mock.assertCommandCalled(["systemctl", "start", "--user", service_unit])
    run_mock.assertCommandCalled(["loginctl", "enable-linger"])


def test_cros_cron_disable(run_mock, has_systemd, outside_sdk):
    """Test the "cros cron disable" command."""
    del outside_sdk
    has_systemd(True)
    _main(["disable"])
    timer_unit, _ = cros_cron.get_systemd_units()
    run_mock.assertCommandCalled(["systemctl", "disable", "--user", timer_unit])
    run_mock.assertCommandCalled(["systemctl", "stop", "--user", timer_unit])


def test_cros_cron_status(run_mock, has_systemd, outside_sdk):
    """Test the "cros cron status" command."""
    del outside_sdk
    has_systemd(True)
    _main(["status"])
    timer_unit, service_unit = cros_cron.get_systemd_units()
    run_mock.assertCommandCalled(
        ["systemctl", "status", "--user", timer_unit, service_unit],
        check=False,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["enable"],
        ["disable"],
        ["status"],
    ],
)
def test_cros_cron_no_systemd(has_systemd, args, outside_sdk):
    """Test commands that should fail without systemd."""
    del outside_sdk
    has_systemd(False)
    assert _main(args) != 0
