# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the utils.compat library.

No need to get too intensive with testing here, especially if you just
copy-pasted the function from cpython/Lib.
"""

from pathlib import Path

import pytest

from chromite.utils import compat


@pytest.mark.parametrize(
    ("inner", "outer", "expected_result"),
    [
        (Path("/"), Path("/"), True),
        (Path("/etc/env.d"), Path("/etc"), True),
        (Path("/etc/env.d"), Path("/usr"), False),
        (Path("a"), Path("a"), True),
        (Path("a"), Path("b"), False),
        (Path("a/b"), Path("a"), True),
    ],
)
def test_path_is_relative_to(
    inner: Path, outer: Path, expected_result: bool
) -> None:
    """Test comapt.path_is_relative_to()."""
    assert compat.path_is_relative_to(inner, outer) == expected_result
