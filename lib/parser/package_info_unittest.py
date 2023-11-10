# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for CPV parsing module."""

import pytest

from chromite.lib.parser import package_info


def test_parse_cpf():
  """Validate parsing a full CPF."""
  cpf = 'foo/bar-1.0.0_alpha-r2'
  pkg = package_info.parse(cpf)
  assert pkg.category == 'foo'
  assert pkg.package == 'bar'
  assert pkg.version == '1.0.0_alpha'
  assert pkg.revision == 2
  assert pkg.cpf == cpf


def test_parse_pv():
  """Validate parsing a PV."""
  pkg = package_info.parse('bar-1.0.0')
  assert not pkg.category
  assert pkg.package == 'bar'
  assert pkg.version == '1.0.0'
  assert not pkg.revision


def test_parse_atom():
  """Validate parsing an atom."""
  pkg = package_info.parse('foo/bar')
  assert pkg.category == 'foo'
  assert pkg.package == 'bar'
  assert not pkg.version
  assert not pkg.revision


@pytest.mark.xfail(raises=ValueError)
def test_parse_invalid():
  """Invalid package format."""
  package_info.parse('invalid/package/format')


def test_package_info_eq():
  pkg = package_info.PackageInfo('foo', 'bar', 1, 2)
  pkg2 = package_info.PackageInfo('foo', 'bar', '1', '2')
  assert pkg == pkg2
  pkg = package_info.PackageInfo('foo', 'bar', 1)
  pkg2 = package_info.PackageInfo('foo', 'bar', '1', '0')
  pkg3 = package_info.PackageInfo('foo', 'bar', '1', 0)
  assert pkg == pkg2 == pkg3


def test_cpf():
  """Validate CPF handling."""
  pkg = package_info.PackageInfo('foo', 'bar', '1')
  pkg2 = package_info.PackageInfo('foo', 'bar', '1', '0')
  assert pkg.cpf == 'foo/bar-1'
  assert pkg2.cpf == pkg.cpf

  r1 = package_info.PackageInfo('foo', 'bar', '1', '1')
  assert r1.cpf == 'foo/bar-1-r1'


def test_relative_path():
  """Test the ebuild path method."""
  pkg = package_info.PackageInfo('foo', 'bar', '1', '0')
  assert pkg.relative_path == 'foo/bar/bar-1.ebuild'


def test_ebuild_name():
  """Test the ebuild name building."""
  pkg = package_info.PackageInfo('foo', 'bar', '1', '0')
  assert pkg.ebuild == 'bar-1.ebuild'
  pkg = package_info.PackageInfo('foo', 'bar', '1', '2')
  assert pkg.ebuild == 'bar-1-r2.ebuild'


def test_revision_bump():
  """Test the revision_bump method."""
  pkg = package_info.PackageInfo('foo', 'bar', '1')
  bumped = pkg.revision_bump()
  bumped2 = bumped.revision_bump()

  assert pkg.cpf == 'foo/bar-1'
  assert bumped.cpf == 'foo/bar-1-r1'
  assert bumped2.cpf == 'foo/bar-1-r2'


def test_with_version_no_revision():
  """Test the with_version method with no revision specified."""
  pkg = package_info.PackageInfo('foo', 'bar', '1')
  pkg2 = pkg.with_version('2')
  assert pkg.cpf == 'foo/bar-1'
  assert pkg2.cpf == 'foo/bar-2'


def test_with_version_with_revision():
  """Test the with_version method with a revision specified."""
  pkg = package_info.PackageInfo('foo', 'bar', '1', '1')
  pkg2 = pkg.with_version('2')
  assert pkg.cpf == 'foo/bar-1-r1'
  assert pkg2.cpf == 'foo/bar-2'
