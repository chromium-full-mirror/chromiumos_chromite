# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for dependency_lib."""

from pathlib import Path

import pytest

from chromite.lib import dependency_lib


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
