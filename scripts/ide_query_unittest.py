# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for ide_query."""

from pathlib import Path
from typing import Any, Dict, List

import pytest

from chromite.lib import cros_build_lib
from chromite.scripts import ide_query


@pytest.mark.parametrize(
    "argv", (["-b", "arm64-generic"], ["--out-dir", "foo/"])
)
def test_parse_invalid_args(argv: List[str]) -> None:
    """Test parse_args() with invalid inputs."""
    with pytest.raises(SystemExit):
        ide_query.parse_args(argv)


@pytest.mark.parametrize(
    "argv, expected_args",
    (
        (
            ["-b", "arm64-generic", "--out-dir", "foo/"],
            {"build_target": "arm64-generic", "out_dir": Path("foo")},
        ),
        (
            ["--build-target", "arm64-generic", "--out-dir", "foo/"],
            {"build_target": "arm64-generic", "out_dir": Path("foo")},
        ),
    ),
)
def test_parse_valid_args(
    argv: List[str],
    expected_args: Dict[str, Any],
) -> None:
    """Test parse_args() with valid inputs."""
    args = ide_query.parse_args(argv)
    for arg_name, arg_value in expected_args.items():
        assert getattr(args, arg_name) == arg_value


def test_main_inside_chroot() -> None:
    """Make sure the script fails when run inside the chroot."""
    with pytest.raises(cros_build_lib.DieSystemExit):
        ide_query.main(["-b", "arm64-generic", "--out-dir", "foo/"])


def test_main_outside_chroot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test running main() from outside the chroot."""
    monkeypatch.setattr(cros_build_lib, "IsInsideChroot", lambda: False)
    with pytest.raises(NotImplementedError):
        ide_query.main(["-b", "arm64-generic", "--out-dir", "foo/"])
