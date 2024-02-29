# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for dependency_lib."""

import os
from pathlib import Path

import pytest

from chromite.lib import dependency_lib
from chromite.lib import osutils


def test_parse_ebuild_cache_entry_md5_cache(tmp_path) -> None:
    """Verify parsing eclasses from md5 cache style files."""
    expected = [
        ("autotools", "d0e5375d47f4c809f406eb892e531513"),
        ("db-use", "9879c16e695a6adb640e428a40dfd26e"),
        ("eclass1", "abc123"),
        ("eclass2", "123abc"),
        ("cros-workon", "112233"),
        ("eclass3", "def789"),
    ]
    eclass_str = "\t".join("\t".join(x) for x in expected)
    contents = f"""
KEYWORDS=*
LICENSE=license
PROPERTIES=live
RDEPEND=>=foo/bar-0.0.1:= foo/baz:=
SLOT=0/0
_eclasses_={eclass_str}
_md5=123456
"""

    cache_file = os.path.join(tmp_path, "cache_file")
    osutils.WriteFile(cache_file, contents)

    # pylint: disable=protected-access
    result = dependency_lib._parse_ebuild_cache_entry(cache_file)

    assert set(expected) == set(result)


def test_parse_ebuild_cache_entry_edb_cache(tmp_path) -> None:
    """Verify parsing eclasses from edb cache style files."""
    expected = [
        ("eclass1", "abc123"),
        ("eclass2", "123abc"),
        ("eclass3", "def789"),
    ]
    eclass_str = "\t".join(
        "\t".join((c, "/some/path", d)) for (c, d) in expected
    )
    contents = f"""
KEYWORDS=*
LICENSE=license
PROPERTIES=live
RDEPEND=>=foo/bar-0.0.1:= foo/baz:=
SLOT=0/0
_eclasses_={eclass_str}
_md5=123456
"""

    cache_file = os.path.join(tmp_path, "cache_file")
    osutils.WriteFile(cache_file, contents)

    # pylint: disable=protected-access
    result = dependency_lib._parse_ebuild_cache_entry(cache_file)

    assert set(expected) == set(result)


def test_get_cache_file(tmp_path) -> None:
    """Verify parsing ebuild filenames to cache filenames."""
    # pylint: disable=protected-access
    with pytest.raises(dependency_lib.MissingCacheEntry):
        dependency_lib._get_cache_file(Path("/overlay/foo/bar/bar-1.ebuild"))

    ebuild = tmp_path / "overlay-o" / "cat" / "foo" / "foo-1.ebuild"
    cache = tmp_path / "overlay-o" / "metadata" / "md5-cache" / "cat" / "foo-1"
    cache.parent.mkdir(parents=True)
    cache.touch()
    assert dependency_lib._get_cache_file(ebuild) == cache
