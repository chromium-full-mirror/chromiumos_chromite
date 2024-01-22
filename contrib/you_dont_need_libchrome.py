# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Scan a sysroot for packages which don't require libchrome/libbrillo."""

import re
from typing import List, Optional, Set

from chromite.lib import commandline
from chromite.lib import portage_util
from chromite.lib.parser import package_info


# Get c/pvr from a dependency
_CPVR_RE = re.compile(r"[^A-Za-z]*([A-Za-z0-9./-]+)[^A-Za-z0-9./-]?.*")


def get_dependencies(package: portage_util.InstalledPackage) -> Set[str]:
    """Get the dependencies for a package.

    We don't care about being super precise here as this is just contrib-sorta
    code for checking libchrome/libbrillo, so don't go copying this
    implementation as perfect.
    """
    result = set()
    for pms_dep_node in (package.depend, package.rdepend):
        for dependency in pms_dep_node.reduce(use_flags=package.use):
            if dependency.startswith("!"):
                # Don't care about blockers.
                continue
            match = _CPVR_RE.fullmatch(dependency)
            if not match:
                print(dependency)
            pinfo = package_info.parse(match.group(1))
            result.add(pinfo.atom)
    return result


def get_linked_libs(package: portage_util.InstalledPackage) -> Set[str]:
    """Get the libraries a package links to (via REQUIRES)."""
    result = set()
    for libs in package.requires.values():
        result.update(libs)
    return result


def get_parser() -> commandline.ArgumentParser:
    """Get an argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sysroot",
        type="dir_exists",
        help="Sysroot with installed packages to search.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """The main function."""
    parser = get_parser()
    opts = parser.parse_args(argv)

    portage_db = portage_util.PortageDB(root=opts.sysroot)
    for package in portage_db.InstalledPackages():
        deps = get_dependencies(package)
        libs = get_linked_libs(package)
        for atom, lib in [
            ("chromeos-base/libchrome", "libbase-core.so"),
            ("chromeos-base/libbrillo", "libbrillo-core.so"),
        ]:
            if atom in deps and lib not in libs:
                print(
                    f"{package.package_info.atom} depends on {atom}, but "
                    f"doesn't link to {lib}"
                )
