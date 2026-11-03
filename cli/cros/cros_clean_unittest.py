# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the `cros clean` command."""

import logging
from pathlib import Path
from unittest import mock

import pytest

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.scripts import cros


_DEFAULT_CHROOT = constants.DEFAULT_CHROOT_PATH
_DEFAULT_OUT = constants.DEFAULT_OUT_PATH
_CITC_CHROOT = Path("/citc/state/chroot")
_CITC_OUT = Path("/citc/state/out")
_CUSTOM_CHROOT = "/custom/chroot"
_CUSTOM_OUT = Path("/custom/out")
_CUSTOM_ARGS = [f"--sdk-path={_CUSTOM_CHROOT}", f"--out-path={_CUSTOM_OUT}"]


@pytest.mark.parametrize(
    ("is_citc", "extra_args", "expected_sdk_path", "expected_out_path"),
    [
        (False, [], _DEFAULT_CHROOT, _DEFAULT_OUT),
        (True, [], str(_CITC_CHROOT), _CITC_OUT),
        (False, _CUSTOM_ARGS, _CUSTOM_CHROOT, _CUSTOM_OUT),
        (True, _CUSTOM_ARGS, _CUSTOM_CHROOT, _CUSTOM_OUT),
    ],
)
def test_clean_sdk_and_out_paths(
    monkeypatch: pytest.MonkeyPatch,
    is_citc: bool,
    extra_args: list[str],
    expected_sdk_path: str,
    expected_out_path: Path,
) -> None:
    """Verify default and custom SDK/out paths used by `cros clean`."""
    monkeypatch.setattr(cros_build_lib, "IsInsideChroot", lambda: False)
    monkeypatch.setattr(path_util, "is_citc_checkout", lambda: is_citc)
    monkeypatch.setattr(path_util, "get_citc_chroot_path", lambda: _CITC_CHROOT)
    monkeypatch.setattr(path_util, "get_citc_out_path", lambda: _CITC_OUT)
    notice_mock = mock.MagicMock()
    monkeypatch.setattr(logging, "notice", notice_mock)
    empty_dir_mock = mock.MagicMock()
    monkeypatch.setattr(osutils, "EmptyDir", empty_dir_mock)

    assert cros.main(["clean", "--chroot", "--dry-run", *extra_args]) == 0
    notice_mock.assert_called_once_with(
        "would have cleaned: %s", expected_sdk_path
    )

    assert cros.main(["clean", "--chroot-tmp", *extra_args]) == 0
    empty_dir_mock.assert_called_once_with(
        str(expected_out_path / "tmp"),
        ignore_missing=True,
        sudo=True,
    )
