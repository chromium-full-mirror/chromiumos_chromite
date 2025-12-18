# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the ebuild_manifest.py module."""

import pytest

from chromite.utils.parser import ebuild_manifest


def test_parse_basic() -> None:
    """Verify basic parsing."""
    obj = ebuild_manifest.parse(
        """
# Comment.
DIST foo.tar 1234 SHA256 abc BLAKE2B y
DIST bar.zip 5 SHA512 efd BLAKE2B x
"""
    )
    assert len(obj.dist) == 2

    dist = obj.dist["foo.tar"]
    assert dist.name == "foo.tar"
    assert dist.size == 1234
    assert dist.hashes["SHA256"] == "abc"
    assert dist.hashes["BLAKE2B"] == "y"

    dist = obj.dist["bar.zip"]
    assert dist.name == "bar.zip"
    assert dist.size == 5
    assert dist.hashes["SHA512"] == "efd"
    assert dist.hashes["BLAKE2B"] == "x"

    assert (
        obj.to_string()
        == """\
DIST bar.zip 5 BLAKE2B x SHA512 efd
DIST foo.tar 1234 BLAKE2B y SHA256 abc
"""
    )


TEST_CASES_INVALID = (
    # Unknown content.
    "BLAH",
    # Bad capitalization.
    "dist foo.tar 1234 SHA256 abc",
    # Missing digests.
    "DIST foo.tar 1234",
    # Malformed digests.
    "DIST foo.tar 1234 SHA256",
    # Duplicated entries.
    """DIST foo.tar 1234 SHA256 abc
DIST foo.tar 1234 SHA256 abc""",
)


@pytest.mark.parametrize("test", TEST_CASES_INVALID)
def test_parse_invalid(test) -> None:
    """Check invalid values."""
    with pytest.raises(ValueError):
        ebuild_manifest.parse(test)
