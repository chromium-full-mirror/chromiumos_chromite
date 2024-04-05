# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for update_chroot."""

import pytest

from chromite.lib import cros_build_lib
from chromite.scripts import update_chroot


def test_main(run_mock) -> None:  # pylint: disable=unused-argument
    """Smoke test."""
    result = update_chroot.main(["--force"])
    assert result == 0


def test_no_force() -> None:
    """Update chroot should fail without --force."""
    with pytest.raises(cros_build_lib.DieSystemExit):
        update_chroot.main([])
