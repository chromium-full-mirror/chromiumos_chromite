# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for update_chroot."""

import pytest

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.scripts import update_chroot


def test_main(run_mock) -> None:  # pylint: disable=unused-argument
    """Smoke test."""
    run_mock.AddCmdResult(
        [
            constants.CHROMITE_BIN_DIR / "cros_setup_toolchains",
            "--show-packages",
            "host",
        ],
        stdout="a/b\nc/d\n",
    )
    result = update_chroot.main(["--force"])
    assert result == 0


def test_no_force() -> None:
    """Update chroot should fail without --force."""
    with pytest.raises(cros_build_lib.DieSystemExit):
        update_chroot.main([])
