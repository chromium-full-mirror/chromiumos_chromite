# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the xml module."""

import pytest

from chromite.format.formatters import xml


# None means input is already formatted to avoid having to repeat.
@pytest.mark.parametrize(
    "data,exp",
    (
        # Treated as plain XML.
        ("<foo/>", "<foo/>\n"),
        ("<foo/>\n\n\n", "<foo/>\n"),
        ("""<manifest version="1.0"/>""", """<manifest version="1.0"/>\n"""),
        # Treated as repo manifest.  Full repo manifest tests are in
        # repo_manifest_unittest.py instead.
        (
            "<manifest/>\n",
            """<?xml version="1.0" encoding="UTF-8"?>\n<manifest/>\n""",
        ),
    ),
)
def test_check_format(data: str, exp: str | None) -> None:
    """Verify inputs match expected outputs."""
    if exp is None:
        exp = data
    assert exp == xml.Data(data)
