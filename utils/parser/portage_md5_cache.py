# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parser for Portage md5-cache files."""

import dataclasses
import functools
from pathlib import Path
from typing import Dict, List, Optional, Set

from chromite.utils.parser import pms_dependency


@dataclasses.dataclass(frozen=True)
class Eclass:
    """An eclass entry."""

    name: str
    digest: str


class Md5Cache:
    """Ebuild md5-cache file."""

    def __init__(
        self,
        data: Optional[str] = None,
        path: Optional[Path] = None,
        missing_ok: bool = True,
    ) -> None:
        """Initialize.

        Args:
            data: The cache content if already available.
            path: The path to the cache file.  If |data| is given, this is more
                for diagnostics, otherwise content will be loaded from this.
            missing_ok: If |path| does not exist, return stub data.
        """
        if data is None and path is None:
            raise ValueError("Need data or path")
        self._data = data
        self._path = path
        self.missing_ok = missing_ok

    @property
    def data(self) -> str:
        """Delay loading file data.

        This way we can construct cache objects backed by a file, but not read
        the file until its actually used.
        """
        if self._data is None:
            try:
                self._data = self._path.read_text(encoding="utf-8")
            except FileNotFoundError:
                if not self.missing_ok:
                    raise
                self._data = ""

        return self._data

    @functools.cached_property
    def vars(self) -> Dict[str, str]:
        """The raw variables from the md5-cache file."""
        result = {}
        for line in self.data.splitlines():
            key, _, value = line.partition("=")
            result[key] = value
        return result

    @property
    def description(self) -> str:
        """Package description."""
        return self.vars.get("DESCRIPTION", "").strip()

    @property
    def homepage(self) -> List[str]:
        """All homepages."""
        return self.vars.get("HOMEPAGE", "").split()

    @property
    def slot(self) -> str:
        """Package slot."""
        return self.vars.get("SLOT", "0").strip()

    @property
    def eapi(self) -> int:
        """The EAPI for the package."""
        return int(self.vars.get("EAPI", 0))

    @property
    def defined_phases(self) -> Set[str]:
        """All known phases the ebuild runs."""
        return set(self.vars.get("DEFINED_PHASES", "").split())

    @property
    def depend(self) -> pms_dependency.RootNode:
        """The DEPEND of this package."""
        return pms_dependency.parse(self.vars.get("DEPEND", ""))

    @property
    def bdepend(self) -> pms_dependency.RootNode:
        """The BDEPEND of this package."""
        return pms_dependency.parse(self.vars.get("BDEPEND", ""))

    @property
    def pdepend(self) -> pms_dependency.RootNode:
        """The PDEPEND of this package."""
        return pms_dependency.parse(self.vars.get("PDEPEND", ""))

    @property
    def rdepend(self) -> pms_dependency.RootNode:
        """The RDEPEND of this package."""
        return pms_dependency.parse(self.vars.get("RDEPEND", ""))

    @property
    def iuse(self) -> Set[str]:
        """A set of the flags in IUSE."""
        iuse = self.vars.get("IUSE")
        if not iuse:
            return set()
        result = set()
        for var in iuse.split(" "):
            if var[0] in "-+":
                var = var[1:]
            result.add(var)
        return result

    @property
    def iuse_default(self) -> Set[str]:
        """A set of the flags enabled by default in IUSE."""
        iuse = self.vars.get("IUSE", "")
        result = set()
        for var in iuse.split(" "):
            if var.startswith("+"):
                var = var[1:]
                result.add(var)
        return result

    @property
    def eclasses(self) -> List[Eclass]:
        """A list of the eclasses inherited by this package and its eclasses."""
        eclasses = self.vars.get("_eclasses_")
        if not eclasses:
            return []
        # The md5-cache format is:
        # <name1>\t<digest1>\t<name2>\t<digest2>
        # The edb format is:
        # <name1>\t<path1>\t<digest1>\t<name2>\t<path2>\t<digest2>
        # Since the path is the only thing that would have a /, we can filter
        # those out
        elements = [x for x in eclasses.split("\t") if not x.startswith("/")]
        return [Eclass(*x) for x in zip(elements[::2], elements[1::2])]

    @property
    def keywords(self) -> List[str]:
        """The KEYWORDS of this package."""
        return self.vars.get("KEYWORDS", "").split()

    @property
    def properties(self) -> Set[str]:
        """The PROPERTIES of this package."""
        return set(self.vars.get("PROPERTIES", "").split())

    @property
    def restrict(self) -> pms_dependency.RootNode:
        """The RESTRICT of this package."""
        return pms_dependency.parse(self.vars.get("RESTRICT", ""))
