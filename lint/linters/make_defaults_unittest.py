# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the make_defaults module."""

import pytest

from chromite.lint.linters import make_defaults
from chromite.lint.linters import portage_layout_conf


# pylint: disable=protected-access


@pytest.mark.parametrize(
    "data",
    (
        """
BOARD_COMPILER_FLAGS="-march=x86-64-v2"
USE=" march_x86-64-v2"
""",
    ),
)
def test_good(data) -> None:
    """Verify matching flags are accepted."""
    assert make_defaults.Data(data) == []


@pytest.mark.parametrize(
    "data",
    (
        """
BOARD_COMPILER_FLAGS="-march=znver3"
USE=" march_bdver4"
""",
    ),
)
def test_mismatch(data) -> None:
    """Verify mismatched flags are rejected."""
    ret = portage_layout_conf.Data(data)
    assert ret


@pytest.mark.parametrize(
    "data",
    (
        """
BOARD_COMPILER_FLAGS=""
USE=" march_bdver4"
""",
    ),
)
def test_missing_compiler_march(data) -> None:
    """Verify missing compiler -march is rejected."""
    ret = portage_layout_conf.Data(data)
    assert ret


@pytest.mark.parametrize(
    "data",
    (
        """
BOARD_COMPILER_FLAGS="-march=x86-64-v2"
USE=""
""",
    ),
)
def test_missing_use_march(data) -> None:
    """Verify missing USE march_ is rejected."""
    ret = portage_layout_conf.Data(data)
    assert ret


@pytest.mark.parametrize(
    "data",
    (
        """
USE=" march_bdver4"
""",
    ),
)
def test_missing_board_compiler_flags(data) -> None:
    """Verify missing BOARD_COMPILER_FLAGS is accepted."""
    assert make_defaults.Data(data) == []


@pytest.mark.parametrize(
    "data",
    (
        """
BOARD_COMPILER_FLAGS="-march=x86-64-v2"
""",
    ),
)
def test_missing_use(data) -> None:
    """Verify missing USE is rejected."""
    ret = portage_layout_conf.Data(data)
    assert ret


@pytest.mark.parametrize(
    "data",
    (
        """
BOARD_COMPILER_FLAGS="-march=x86-64-v2"
USE="-march_goldmont march_x86-64-v2"
""",
    ),
)
def test_ignore_removed_use_march(data) -> None:
    """Verify missing USE is rejected."""
    ret = portage_layout_conf.Data(data)
    assert ret
