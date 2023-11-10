# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Package Info (CPV) parsing."""

from __future__ import print_function

import collections
import functools
import re
import string

# Define data structures for holding PV and CPV objects.
_PV_FIELDS = ['pv', 'package', 'version', 'version_no_rev', 'rev']
PV = collections.namedtuple('PV', _PV_FIELDS)
# See ebuild(5) man page for the field specs these fields are based on.
# Notably, cpv does not include the revision, cpf does.
_CPV_FIELDS = ['category', 'cp', 'cpv', 'cpf'] + _PV_FIELDS
CPV = collections.namedtuple('CPV', _CPV_FIELDS)

# Package matching regexp, as dictated by package manager specification:
# https://www.gentoo.org/proj/en/qa/pms.xml
_pkg = r'(?P<package>' + r'[\w+][\w+-]*)'
_ver = (r'(?P<version>'
        r'(?P<version_no_rev>(\d+)((\.\d+)*)([a-z]?)'
        r'((_(pre|p|beta|alpha|rc)\d*)*))'
        r'(-(?P<rev>r(\d+)))?)')
_pvr_re = re.compile(r'^(?P<pv>%s-%s)$' % (_pkg, _ver), re.VERBOSE)


def SplitPV(pv, strict=True):
  """Takes a PV value and splits it into individual components.

  Deprecated, use parse() instead.

  Args:
    pv: Package name and version.
    strict: If True, returns None if version or package name is missing.
      Otherwise, only package name is mandatory.

  Returns:
    A collection with named members:
      pv, package, version, version_no_rev, rev
  """
  m = _pvr_re.match(pv)

  if m is None and strict:
    return None

  if m is None:
    return PV(**{'pv': None, 'package': pv, 'version': None,
                 'version_no_rev': None, 'rev': None})

  return PV(**m.groupdict())


def SplitCPV(cpv, strict=True):
  """Splits a CPV value into components.

  Deprecated, use parse() instead.

  Args:
    cpv: Category, package name, and version of a package.
    strict: If True, returns None if any of the components is missing.
      Otherwise, only package name is mandatory.

  Returns:
    A collection with named members:
      category, pv, package, version, version_no_rev, rev
  """
  chunks = cpv.split('/')
  if len(chunks) > 2:
    raise ValueError('Unexpected package format %s' % cpv)
  if len(chunks) == 1:
    category = None
  else:
    category = chunks[0]

  m = SplitPV(chunks[-1], strict=strict)
  if strict and (category is None or m is None):
    return None

  # Gather parts and build each field. See ebuild(5) man page for spec.
  cp_fields = (category, m.package)
  cp = '%s/%s' % cp_fields if all(cp_fields) else None

  cpv_fields = (cp, m.version_no_rev)
  real_cpv = '%s-%s' % cpv_fields if all(cpv_fields) else None

  cpf_fields = (real_cpv, m.rev)
  cpf = '%s-%s' % cpf_fields if all(cpf_fields) else real_cpv

  return CPV(category=category, cp=cp, cpv=real_cpv, cpf=cpf, **m._asdict())


def parse(cpv):
  """Parse a CPV string as a PackageInfo object."""
  parsed = SplitCPV(cpv, strict=False)
  # Temporary measure. SplitCPV parses X-r1 with the revision as r1.
  # Once the SplitCPV function has been fully deprecated we can switch
  # the regex to exclude the r from what it parses as the revision instead.
  # TODO: Change the regex to parse the revision without the r.
  revision = parsed.rev.replace('r', '') if parsed.rev else None
  return PackageInfo(
      category=parsed.category,
      package=parsed.package,
      version=parsed.version_no_rev,
      revision=revision)


class PackageInfo(object):
  """Read-only class to hold and format commonly used package information."""

  def __init__(self, category=None, package=None, version=None, revision=None):
    # Private attributes to enforce read-only. Particularly to allow use of
    # lru_cache for formatting.
    self._category = category
    self._package = package
    self._version = version
    self._revision = int(revision) if revision else 0

  def __eq__(self, other):
    try:
      return (self.category == other.category and
              self.package == other.package and
              str(self.version) == str(other.version) and
              str(self.revision) == str(other.revision))
    except AttributeError:
      return False

  def __hash__(self):
    return hash((self._category, self._package, self._version, self._revision))

  @functools.lru_cache()
  def __format__(self, format_spec):
    """Formatter function.

    The format |spec| is a format string containing any combination of:
    {c}, {p}, {v}, or {r} for the package's category, package name, version,
    or revision, respectively, or any of the class' {attribute}s.
    e.g. {c}/{p} or {atom} for a package's atom (i.e. category/package_name).
    """
    fmtter = string.Formatter()
    base_dict = {
        'c': self.category,
        'p': self.package,
        'v': self.version,
        # Force 'r' to be None when we have 0 to avoid -r0 suffixes.
        'r': self.revision or None,
    }
    fields = (x for _, x, _, _ in fmtter.parse(format_spec) if x)
    # Setting base_dict.get(x) as the default value for getattr allows it to
    # fall back to valid, falsey values in the base_dict rather than
    # overwriting them with None, i.e. 0 for version or revision.
    fmt_dict = {x: getattr(self, x, base_dict.get(x)) for x in fields}

    # We can almost do `if all(fmt_dict.values()):` to just check for falsey
    # values here, but 0 is a valid version value.
    if any(v in ('', None) for v in fmt_dict.values()):
      return ''

    return format_spec.format(**fmt_dict)

  @property
  def category(self):
    return self._category

  @property
  def package(self):
    return self._package

  @property
  def version(self):
    return self._version

  @property
  def revision(self):
    return self._revision

  @property
  def cpv(self):
    return format(self, '{c}/{p}-{v}')

  @property
  def cpvr(self):
    return format(self, '{cpv}-r{r}') or self.cpv

  @property
  def cpf(self):
    """CPF is the portage name for cpvr, provided to simplify transition."""
    return self.cpvr

  @property
  def atom(self):
    return format(self, '{c}/{p}')

  @property
  def cp(self):
    return self.atom

  @property
  def pv(self):
    return format(self, '{p}-{v}')

  @property
  def pvr(self):
    return format(self, '{pv}-r{r}') or self.pv

  @property
  def vr(self):
    return format(self, '{v}-r{r}') or self.version

  @property
  def ebuild(self):
    return format(self, '{pvr}.ebuild')

  @property
  def relative_path(self):
    """Path of the ebuild relative to its overlay."""
    return format(self, '{c}/{p}/{ebuild}')

  def revision_bump(self):
    """Get a PackageInfo instance with an incremented revision."""
    return PackageInfo(self.category, self.package, self.version,
                       self.revision + 1)

  def with_version(self, version):
    """Get a PackageInfo instance with the new, specified version."""
    return PackageInfo(self.category, self.package, version)
