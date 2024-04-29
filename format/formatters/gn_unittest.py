# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the gn module."""

import pytest

from chromite.format import formatters


# None means input is already formatted to avoid having to repeat.
@pytest.mark.parametrize(
    "data,exp",
    (
        ("", None),
        ('f="bar"', 'f = "bar"\n'),
    ),
)
def test_check_format(data, exp) -> None:
    """Verify inputs match expected outputs."""
    if exp is None:
        exp = data
    assert exp == formatters.gn.Data(data)


@pytest.mark.parametrize(
    "data",
    ("{",),
)
def test_format_failures(data) -> None:
    """Verify inputs raise ParseErrors as expected."""
    with pytest.raises(formatters.ParseError):
        formatters.gn.Data(data)
