# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for setup.py."""

import pytest

from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import constants


# Objects to use throughout setup.
BOARD = "amd64-generic"


def test_basic_setup() -> None:
    """Make sure we can initialize a basic Setup."""
    _setup = setup.Setup(BOARD)
    assert _setup.cros_dir == str(constants.SOURCE_ROOT)
    assert _setup.chroot.path == constants.DEFAULT_CHROOT_PATH


def test_with_chroot_dir() -> None:
    """Initialize a Setup with a custom chroot_dir."""
    chroot_path = "/path/to/chroot"
    _setup = setup.Setup(BOARD, chroot_dir=chroot_path)
    assert _setup.cros_dir == str(constants.SOURCE_ROOT)
    assert _setup.chroot.path == chroot_path
    assert _setup.chroot.out_path == constants.DEFAULT_OUT_PATH


def test_custom_chroot_dir_inside_source_root() -> None:
    """Make sure we can't set up a custom chroot dir inside the source root."""
    chroot_path = constants.SOURCE_ROOT / "other_chroot"
    with pytest.raises(ValueError):
        setup.Setup(BOARD, chroot_dir=chroot_path)


def test_custom_chroot_dir_is_default() -> None:
    """Custom chroot dir in the source root is OK if it's the default chroot."""
    chroot_path = constants.SOURCE_ROOT / constants.DEFAULT_CHROOT_DIR
    setup.Setup(BOARD, chroot_dir=chroot_path)
