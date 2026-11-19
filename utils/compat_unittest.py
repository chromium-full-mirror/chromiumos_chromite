# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the utils.compat library.

No need to get too intensive with testing here, especially if you just
copy-pasted the function from cpython/Lib.
"""

import warnings

import pytest

import chromite
from chromite.utils import compat


# pylint: disable=protected-access


def test_available_in_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _available_in() warns when MIN_PYTHON_VERSION is high enough."""
    monkeypatch.setattr(chromite, "MIN_PYTHON_VERSION", (3, 9))

    @compat._available_in((3, 9), "stdlib.func")
    def my_func(x: int) -> int:
        return x + 1

    with pytest.warns(
        DeprecationWarning,
        match=r"my_func is now available in the Python standard library\."
        r"  Please use stdlib\.func instead\.",
    ):
        assert my_func(1) == 2


def test_available_in_no_warn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _available_in() does not warn for newer Python versions."""
    monkeypatch.setattr(chromite, "MIN_PYTHON_VERSION", (3, 9))

    @compat._available_in((3, 10), "stdlib.func")
    def my_func(x: int) -> int:
        return x + 1

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert my_func(1) == 2
