# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for portage_md5_cache.py."""

from pathlib import Path

import pytest

from chromite.utils.parser import portage_md5_cache


def test_delayed_read(tmp_path: Path) -> None:
    """Verify file loads are delayed."""
    path = tmp_path / "foo"
    # Should not read the file at construction time.
    cache = portage_md5_cache.Md5Cache(path=path, missing_ok=False)
    with pytest.raises(FileNotFoundError):
        _ = cache.eapi
    path.write_text("EAPI=3", encoding="utf-8")
    assert cache.eapi == 3


def test_missing_ok(tmp_path: Path) -> None:
    """Verify missing files."""
    path = tmp_path / "foo"
    cache = portage_md5_cache.Md5Cache(path=path, missing_ok=True)
    assert cache.eapi == 0


def test_data_no_file(tmp_path: Path) -> None:
    """Explicit data should not read files."""
    path = tmp_path / "foo"
    cache = portage_md5_cache.Md5Cache(
        data="EAPI=3", path=path, missing_ok=False
    )
    assert cache.eapi == 3


def test_defaults_empty() -> None:
    """Check default values when keys are missing."""
    cache = portage_md5_cache.Md5Cache(data="")
    assert cache.description == ""
    assert cache.homepage == []
    assert cache.slot == "0"
    assert cache.eapi == 0
    assert cache.defined_phases == set()
    assert cache.iuse == set()
    assert cache.iuse_default == set()
    assert cache.eclasses == []
    assert cache.keywords == []
    assert cache.properties == set()


def test_defaults_blank() -> None:
    """Check default values when keys are set with no value."""
    cache = portage_md5_cache.Md5Cache(
        data="""
DESCRIPTION=
HOMEPAGE=
SLOT=
DEFINED_PHASES=
IUSE=
_eclasses_=
KEYWORDS=
PROPERTIES=
"""
    )
    assert cache.description == ""
    assert cache.homepage == []
    assert cache.slot == ""
    assert cache.eapi == 0
    assert cache.defined_phases == set()
    assert cache.iuse == set()
    assert cache.iuse_default == set()
    assert cache.eclasses == []
    assert cache.keywords == []
    assert cache.properties == set()


def test_basic_fields() -> None:
    """Check basic fields."""
    digest1 = "b0a38a01d6c4a3b9cac9f99bef930dcc"
    digest2 = "e221f20e27d5c771e27b925a464ba675"
    cache = portage_md5_cache.Md5Cache(
        data=f"""
DESCRIPTION=Blah desc
HOMEPAGE=https://example.com https://wiki.example.com
SLOT=0/124.0.6340.0_rc-r1
EAPI=3
DEFINED_PHASES=compile configure
IUSE=a +b -c d
_eclasses_=eutils\t{digest1}\tblah\t{digest2}
KEYWORDS=-* amd64 ~arm
PROPERTIES=live
"""
    )
    assert cache.description == "Blah desc"
    assert cache.homepage == ["https://example.com", "https://wiki.example.com"]
    assert cache.slot == "0/124.0.6340.0_rc-r1"
    assert cache.eapi == 3
    assert cache.defined_phases == {"compile", "configure"}
    assert cache.iuse == {"a", "b", "c", "d"}
    assert cache.iuse_default == {"b"}
    assert cache.eclasses == [
        portage_md5_cache.Eclass("eutils", digest1),
        portage_md5_cache.Eclass("blah", digest2),
    ]
    assert cache.keywords == ["-*", "amd64", "~arm"]
    assert cache.properties == {"live"}


def test_edb_eclass_field() -> None:
    """Check eclass field in edb files."""
    digest1 = "b0a38a01d6c4a3b9cac9f99bef930dcc"
    digest2 = "e221f20e27d5c771e27b925a464ba675"
    cache = portage_md5_cache.Md5Cache(
        data=f"""
_eclasses_=eutils\t/foo/eclass\t{digest1}\tblah\t/ok/eclass\t{digest2}
"""
    )
    assert cache.eclasses == [
        portage_md5_cache.Eclass("eutils", digest1),
        portage_md5_cache.Eclass("blah", digest2),
    ]
