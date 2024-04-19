# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the "cros cron" command."""

from pathlib import Path
from typing import List
from unittest import mock

from chromite.cli.cros import cros_cron
from chromite.lib import commandline
from chromite.lib import cros_sdk_lib


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


def test_cros_cron_run(tmp_path: Path) -> None:
    """Test the "cros cron run" command."""
    with mock.patch.object(cros_cron, "prefetch_sdks") as prefetch_sdks:
        _main(["run", "--cache-dir", str(tmp_path)])
        prefetch_sdks.assert_called_once_with(tmp_path)
