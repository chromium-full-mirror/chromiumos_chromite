# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for CPV parsing module."""

from pathlib import Path

import pytest

from chromite.lib.parser import package_info


def test_parse_cpf() -> None:
    """Validate parsing a full CPF."""
    cpf = "foo/bar-1.0.0_alpha-r2"
    pkg = package_info.parse(cpf)
    assert pkg.category == "foo"
    assert pkg.package == "bar"
    assert pkg.version == "1.0.0_alpha"
    assert pkg.revision == 2
    assert pkg.cpf == cpf


def test_parse_pv() -> None:
    """Validate parsing a PV."""
    pkg = package_info.parse("bar-1.2.3_rc1-r5")
    assert not pkg.category
    assert pkg.package == "bar"
    assert pkg.version == "1.2.3_rc1"
    assert pkg.revision == 5


def test_parse_atom() -> None:
    """Validate parsing an atom."""
    pkg = package_info.parse("foo/bar")
    assert pkg.category == "foo"
    assert pkg.package == "bar"
    assert not pkg.version
    assert not pkg.revision


def test_parse_path() -> None:
    """Validate that parsing an ebuild Path."""
    pkg = package_info.parse(Path("foo/bar/bar-1.2.3-r3.ebuild"))
    assert pkg.category == "foo"
    assert pkg.package == "bar"
    assert pkg.version == "1.2.3"
    assert pkg.revision == 3


def test_parse_bad_path() -> None:
    with pytest.raises(package_info.ParseTypeError):
        package_info.parse(Path("not/an/ebuild.txt"))


def test_parse_invalid() -> None:
    """Invalid package format."""
    with pytest.raises(ValueError):
        package_info.parse("invalid/package/format")


def test_parse_cpv() -> None:
    """Verify CPV instance parsing."""
    cpv = package_info.SplitCPV("foo/bar-1.2.3-r3")
    assert cpv
    parsed = package_info.parse("foo/bar-1.2.3-r3")
    parsed_cpv = package_info.parse(cpv)
    assert parsed == parsed_cpv


def test_parse_pkg_info() -> None:
    """Verify PackageInfo instance parsing."""
    pkg = package_info.parse("foo/bar-1.2.3-r3")
    pkg2 = package_info.parse(pkg)
    assert pkg == pkg2


def test_package_info_eq() -> None:
    """Test __eq__ method."""
    pkg = package_info.PackageInfo("foo", "bar", 1, 2)
    pkg2 = package_info.PackageInfo("foo", "bar", "1", "2")
    assert pkg == pkg2
    pkg = package_info.PackageInfo("foo", "bar", 1)
    pkg2 = package_info.PackageInfo("foo", "bar", "1", "0")
    pkg3 = package_info.PackageInfo("foo", "bar", "1", 0)
    assert pkg == pkg2 == pkg3


def test_package_info_eq_valid_types() -> None:
    """Test __eq__ method with different, valid types."""
    pkg = package_info.PackageInfo("foo", "bar", 1, 2)
    pkg2 = "foo/bar-1-r2"
    assert pkg == pkg2
    pkg2cpv = package_info.SplitCPV(pkg2)
    assert pkg == pkg2cpv


def test_package_info_eq_invalid_types() -> None:
    """Test __eq__ method with invalid types."""

    class Foo:
        """Empty class for test."""

    pkg = package_info.PackageInfo("foo", "bar", 1, 2)
    pkg2 = Foo()
    # pylint: disable=unneeded-not
    assert not pkg == pkg2
    assert pkg != pkg2


def _compare_unequal_packages(lesser: str, greater: str) -> None:
    """Execute all comparison operators for the two given package strings."""
    b_str = greater
    b_cpv = package_info.SplitCPV(b_str)
    a = package_info.parse(lesser)
    b = package_info.parse(b_str)

    # __lt__.
    assert a < b
    # __le__.
    assert a <= b
    # __gt__.
    assert b > a
    # __ge__.
    assert b >= a
    # __eq__.
    assert a != b
    assert a != b_cpv
    assert a != b_str


def test_package_info_comparisons_category_diff() -> None:
    """Test comparison methods with different categories."""
    _compare_unequal_packages("a/pkg-1", "b/pkg-1")


def test_package_info_comparisons_package_diff() -> None:
    """Test comparison methods with different packages."""
    _compare_unequal_packages("cat/a-1", "cat/b-1")


def test_package_info_comparisons_simple_version_diff() -> None:
    """Test comparison methods with simple version difference."""
    _compare_unequal_packages("cat/pkg-1", "cat/pkg-2")


def test_package_info_comparisons_multi_part_version_diff() -> None:
    """Test comparison methods with a multiple part version difference."""
    _compare_unequal_packages("cat/pkg-1.2.3.4", "cat/pkg-1.2.3.8")


def test_package_info_comparisons_revision_diff() -> None:
    """Test comparison methods with a revision difference."""
    _compare_unequal_packages("cat/pkg-1.2.3-r1", "cat/pkg-1.2.3-r2")


def test_package_info_comparisons_invalid_type() -> None:
    """Test comparison methods with invalid types."""

    class Foo:
        """Empty class for test."""

    a = package_info.PackageInfo("cat", "pkg", "1.2.3", 1)
    b = Foo()

    # pylint: disable=pointless-statement
    with pytest.raises(package_info.InvalidComparisonTypeError):
        a > b
    with pytest.raises(package_info.InvalidComparisonTypeError):
        a >= b
    with pytest.raises(package_info.InvalidComparisonTypeError):
        a < b
    with pytest.raises(package_info.InvalidComparisonTypeError):
        a <= b


def test_cpf() -> None:
    """Validate CPF handling."""
    pkg = package_info.PackageInfo("foo", "bar", "1")
    pkg2 = package_info.PackageInfo("foo", "bar", "1", "0")
    assert pkg.cpf == "foo/bar-1"
    assert pkg2.cpf == pkg.cpf

    r1 = package_info.PackageInfo("foo", "bar", "1", "1")
    assert r1.cpf == "foo/bar-1-r1"


def test_relative_path() -> None:
    """Test the ebuild path method."""
    pkg = package_info.PackageInfo("foo", "bar", "1", "0")
    assert pkg.relative_path == "foo/bar/bar-1.ebuild"


def test_ebuild_name() -> None:
    """Test the ebuild name building."""
    pkg = package_info.PackageInfo("foo", "bar", "1", "0")
    assert pkg.ebuild == "bar-1.ebuild"
    pkg = package_info.PackageInfo("foo", "bar", "1", "2")
    assert pkg.ebuild == "bar-1-r2.ebuild"


def test_revision_bump() -> None:
    """Test the revision_bump method."""
    pkg = package_info.PackageInfo("foo", "bar", "1")
    bumped = pkg.revision_bump()
    bumped2 = bumped.revision_bump()

    assert pkg.cpf == "foo/bar-1"
    assert bumped.cpf == "foo/bar-1-r1"
    assert bumped2.cpf == "foo/bar-1-r2"


def test_with_version_no_revision() -> None:
    """Test the with_version method with no revision specified."""
    pkg = package_info.PackageInfo("foo", "bar", "1")
    pkg2 = pkg.with_version("2")
    assert pkg.cpf == "foo/bar-1"
    assert pkg2.cpf == "foo/bar-2"


def test_with_version_with_revision() -> None:
    """Test the with_version method with a revision specified."""
    pkg = package_info.PackageInfo("foo", "bar", "1", "1")
    pkg2 = pkg.with_version("2")
    assert pkg.cpf == "foo/bar-1-r1"
    assert pkg2.cpf == "foo/bar-2"


def test_with_version_with_specified_revision() -> None:
    """Test the with_version method with a revision arg specified."""
    pkg = package_info.PackageInfo("foo", "bar", "1", "1")
    pkg2 = pkg.with_version("2", revision=3)
    assert pkg.cpf == "foo/bar-1-r1"
    assert pkg2.cpf == "foo/bar-2-r3"
