# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Package Info (CPV) parsing."""

from __future__ import annotations

import dataclasses
import functools
from pathlib import Path
import re
import string
from typing import Any, Optional, Union

from chromite.utils import pms


@dataclasses.dataclass(frozen=True)
class _PV:
    """Data type for holding a package version.

    Note: you shouldn't use this type directly.  Newer code should use
    PackageInfo (created by parse()).
    """

    pv: Optional[str]
    package: str
    version: Optional[str]
    version_no_rev: Optional[str]
    rev: Optional[str]


@dataclasses.dataclass(frozen=True)
class CPV(_PV):
    """Data type for holding category/package-version.

    See ebuild(5) man page for the field specs these fields are based on.
    Notably, cpv does not include the revision, cpf does.

    Note: you shouldn't use this type directly.  Newer code should use
    PackageInfo (created by parse()).
    """

    category: Optional[str]
    cp: Optional[str]
    cpv: Optional[str]
    cpf: Optional[str]

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, CPV):
            return False
        return dataclasses.astuple(self) < dataclasses.astuple(other)


# Package matching regexp, as dictated by package manager specification:
# https://www.gentoo.org/proj/en/qa/pms.xml
_pkg = r"(?P<package>[\w+][\w+-]*)"
_ver = (
    r"(?P<version>"
    r"(?P<version_no_rev>(\d+)((\.\d+)*)([a-z]?)"
    r"((_(pre|p|beta|alpha|rc)\d*)*))"
    r"(-(?P<rev>r(\d+)))?)"
)
_pvr_re = re.compile(r"^(?P<pv>%s-%s)$" % (_pkg, _ver), re.VERBOSE)


class Error(Exception):
    """Base error class for the module."""


class InvalidComparisonTypeError(Error, TypeError):
    """Known class compared to an unknown type that cannot be resolved."""


class ParseTypeError(Error, TypeError):
    """Attempted parse of a type that could not be handled."""


def _SplitPV(pv: str, strict: bool = True) -> Optional[_PV]:
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
        return _PV(
            pv=None,
            package=pv,
            version=None,
            version_no_rev=None,
            rev=None,
        )

    return _PV(
        pv=m["pv"],
        package=m["package"],
        version=m["version"],
        version_no_rev=m["version_no_rev"],
        rev=m["rev"],
    )


def SplitCPV(cpv: str, strict: bool = True) -> Optional[CPV]:
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
    chunks = cpv.split("/")
    if len(chunks) > 2:
        raise ValueError("Unexpected package format %s" % cpv)
    if len(chunks) == 1:
        category = None
    else:
        category = chunks[0]

    pv = _SplitPV(chunks[-1], strict=strict)
    if pv is None:
        return None
    if strict and category is None:
        return None

    # Gather parts and build each field. See ebuild(5) man page for spec.
    cp_fields = (category, pv.package)
    cp = "%s/%s" % cp_fields if all(cp_fields) else None

    cpv_fields = (cp, pv.version_no_rev)
    real_cpv = "%s-%s" % cpv_fields if all(cpv_fields) else None

    cpf_fields = (real_cpv, pv.rev)
    cpf = "%s-%s" % cpf_fields if all(cpf_fields) else real_cpv

    return CPV(
        category=category,
        cp=cp,
        cpv=real_cpv,
        cpf=cpf,
        pv=pv.pv,
        package=pv.package,
        version=pv.version,
        version_no_rev=pv.version_no_rev,
        rev=pv.rev,
    )


def parse(cpv: Union[str, Path, CPV, PackageInfo]) -> PackageInfo:
    """Parse a package to a PackageInfo object.

    Args:
        cpv: Any package type. This function can parse strings, translate CPVs
            to a PackageInfo instance, and will simply return the argument if
            given a PackageInfo instance.  If given a Path, this will treat the
            path as the path to an ebuild.

    Returns:
        PackageInfo
    """
    if isinstance(cpv, Path):
        if not cpv.suffix == ".ebuild":
            raise ParseTypeError(f"{cpv} must be a path to an ebuild")
        cpv = f"{cpv.parent.parent.name}/{cpv.stem}"
    if isinstance(cpv, PackageInfo):
        return cpv
    elif isinstance(cpv, CPV):
        parsed = cpv
    elif isinstance(cpv, str):
        parsed_cpv = SplitCPV(cpv, strict=False)
        if not parsed_cpv:
            raise ValueError(f"Unable to parse value as CPV: {cpv}")
        parsed = parsed_cpv
    else:
        raise ParseTypeError(f"Unable to parse type: {type(cpv)}")

    # Temporary measure. SplitCPV parses X-r1 with the revision as r1.
    # Once the SplitCPV function has been fully deprecated we can switch
    # the regex to exclude the r from what it parses as the revision instead.
    # TODO: Change the regex to parse the revision without the r.
    revision = parsed.rev.replace("r", "") if parsed.rev else None
    return PackageInfo(
        category=parsed.category,
        package=parsed.package,
        version=parsed.version_no_rev,
        revision=revision,
    )


class PackageInfo:
    """Read-only class to hold and format commonly used package information."""

    def __init__(
        self,
        category: Optional[str] = None,
        package: Optional[str] = None,
        version: Optional[Union[str, int]] = None,
        revision: Optional[Union[str, int]] = None,
    ) -> None:
        # Private attributes to enforce read-only. Particularly to allow use of
        # lru_cache for formatting.
        self._category = category
        self._package = package or ""
        self._version = str(version) if version is not None else ""
        self._revision = int(revision) if revision else 0

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, PackageInfo):
            try:
                return self == parse(other)
            except ParseTypeError:
                return False

        # Simple comparisons for category, package, and revision. Do manual
        # revision comparison to avoid recursion with the LRU Cache when
        # comparing the `.vr`s.
        if (
            self.category != other.category
            or self.package != other.package
            or self.revision != other.revision
        ):
            # Early return to skip version logic when possible.
            return False

        if self.version and other.version:
            return pms.version_eq(self.version, other.version)
        else:
            return self.version == other.version

    def __ge__(self, other: Any) -> bool:
        return bool(self == other or self > other)

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, PackageInfo):
            raise InvalidComparisonTypeError(
                f"'>' not supported between '{type(self)}' and '{type(other)}'."
            )

        # Compare as much of the "category/package" as we have.
        if self.atom and other.atom and self.atom != other.atom:
            return self.atom > other.atom
        elif self.category != other.category:
            return (self.category or "") > (other.category or "")
        elif self.package != other.package:
            return self.package > other.package

        if self.vr and other.vr:
            # Both have versions, do full comparison.
            return pms.version_gt(self.vr, other.vr)
        else:
            # Simple compare since only one or neither has a version.
            return self.vr > other.vr

    def __le__(self, other: Any) -> bool:
        return bool(self == other or self < other)

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, PackageInfo):
            # x < y == y > x, so just do that when we can.
            return other > self
        else:
            raise InvalidComparisonTypeError(
                f"'<' not supported between '{type(self)}' and '{type(other)}'."
            )

    def __hash__(self) -> int:
        return hash(
            (self._category, self._package, self._version, self._revision)
        )

    def __repr__(self) -> str:
        return f"PackageInfo<{str(self)}>"

    def __str__(self) -> str:
        return self.cpvr or self.atom or self.pvr or self.package

    @functools.lru_cache()
    def __format__(self, format_spec: str) -> str:
        """Formatter function.

        The format |spec| is a format string containing any combination of:
        {c}, {p}, {v}, or {r} for the package's category, package name, version,
        or revision, respectively, or any of the class' {attribute}s.
        e.g. {c}/{p} or {atom} for a package's atom (i.e.
        category/package_name).
        """
        if not format_spec:
            # f"{pkg_info}" calls pkg_info.format with an empty format spec.
            # Since we wouldn't be otherwise calling format like that, just
            # redirect to __str__ instead.
            return str(self)

        fmtter = string.Formatter()
        base_dict = {
            "c": self.category,
            "p": self.package,
            "v": self.version,
            # Force 'r' to be None when we have 0 to avoid -r0 suffixes.
            "r": self.revision or None,
        }
        fields = (x for _, x, _, _ in fmtter.parse(format_spec) if x)
        # Setting base_dict.get(x) as the default value for getattr allows it to
        # fall back to valid, falsey values in the base_dict rather than
        # overwriting them with None, i.e. 0 for version or revision.
        fmt_dict = {x: getattr(self, x, base_dict.get(x)) for x in fields}

        # We can almost do `if all(fmt_dict.values()):` to just check for falsey
        # values here, but 0 is a valid version value.
        if any(v in ("", None) for v in fmt_dict.values()):
            return ""

        return format_spec.format(**fmt_dict)

    @property
    def category(self) -> Optional[str]:
        return self._category

    @property
    def package(self) -> str:
        return self._package

    @property
    def version(self) -> str:
        return self._version

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def cpv(self) -> str:
        return format(self, "{c}/{p}-{v}")

    @property
    def cpvr(self) -> str:
        return format(self, "{cpv}-r{r}") or self.cpv

    @property
    def cpf(self) -> str:
        """CPF is the portage name for cpvr, provided to simplify transition."""
        return self.cpvr

    @property
    def atom(self) -> str:
        return format(self, "{c}/{p}")

    @property
    def cp(self) -> str:
        return self.atom

    @property
    def pv(self) -> str:
        return format(self, "{p}-{v}")

    @property
    def pvr(self) -> str:
        """This is PF in Gentoo variable definitions.

        From Gentoo docs: PF - Full package name. e.g. 'vim-6.3-r1' or
            'vim-6.3'.
        """
        return format(self, "{pv}-r{r}") or self.pv

    @property
    def vr(self) -> str:
        """This is PVR in Gentoo variable definitions.

        From Gentoo docs: PVR - Package version and revision (if any). e.g.
            '6.3' or '6.3-r1'.
        """
        return format(self, "{v}-r{r}") or self.version

    @property
    def ebuild(self) -> str:
        return format(self, "{pvr}.ebuild")

    @property
    def relative_path(self) -> str:
        """Path of the ebuild relative to its overlay."""
        return format(self, "{c}/{p}/{ebuild}")

    def revision_bump(self) -> PackageInfo:
        """Get a PackageInfo instance with an incremented revision."""
        return self.with_version(self.version, self.revision + 1)

    def with_version(self, version: str, revision: int = 0) -> PackageInfo:
        """Get a PackageInfo instance with the new, specified version."""
        return PackageInfo(self.category, self.package, version, revision)

    def with_rev0(self) -> PackageInfo:
        """Get a -r0 instance of the package."""
        return self.with_version(self.version) if self.revision else self

    def to_cpv(self) -> Optional[CPV]:
        """Get a CPV instance of this PackageInfo.

        This method is provided only to allow compatibility with functions that
        have not yet been converted to use PackageInfo objects. This function
        will be removed when the CPV dataclass is removed.
        """
        return SplitCPV(self.cpvr)
