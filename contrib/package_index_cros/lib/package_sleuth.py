# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to help with finding packages and their dependencies."""

import dataclasses
import json
import logging
from typing import Dict, List, Optional, Set

from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import portage_util
from chromite.lib.parser import package_info


@dataclasses.dataclass
class SupportedUnsupportedPackages:
    """Dataclass to hold supported and unsupported packages."""

    supported: List[package.Package]
    unsupported: List[str]


class PackageSleuth:
    """Handler for finding packages."""

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data
        self.overlays = portage_util.FindOverlays(
            overlay_type=portage_util.constants.BOTH_OVERLAYS,
            board=self.setup.board,
            buildroot=self.setup.cros_dir,
        )

    def list_packages(
        self, *, packages_names: Optional[List[str]] = None
    ) -> SupportedUnsupportedPackages:
        """Find all packages matching the given packages_names.

        Returns:
            If packages_names is given and non-empty, then a list of matching
            packages (including unsupported packages). Otherwise, a list of all
            available packages.
        """
        if packages_names is None:
            packages_names = []
        packages = self._list_packages_with_deps(packages_names)
        _filter_packages_dependencies(packages.supported)

        return packages

    def _list_packages_with_deps(
        self, package_names: List[str]
    ) -> SupportedUnsupportedPackages:
        """Return a list of supported packages and their transitive deps."""
        # _get_packages_dependencies() should return a dict with a key for each
        # transitive dependency of each package.
        package_to_dependencies = self._get_packages_dependencies(package_names)

        packages = SupportedUnsupportedPackages(supported=[], unsupported=[])
        ebuilds = self._list_ebuilds(list(package_to_dependencies))
        for ebuild in ebuilds:
            package_support = package.get_package_support(ebuild, self.setup)
            if package_support.is_supported():
                packages.supported.append(
                    package.Package(
                        self.setup,
                        ebuild,
                        package_to_dependencies[ebuild.package],
                    )
                )
            else:
                logging.warning(
                    "%s: Not supported: %s",
                    ebuild.package,
                    package_support.name,
                )
                packages.unsupported.append(ebuild.package)
        return packages

    def _list_ebuilds(self, packages_names: List[str]) -> portage_util.EBuild:
        """Return a list of ebuilds with the given names.

        If packages_names is None or empty, return all available ebuilds
        instead.

        The number of returned ebuilds may be less than the number of
        |packages_names|. For example, there can be a miss if a requested
        package is private and we're fetching only public packages, or if a
        requested package is out-of-scope for the given board.
        """
        looking_for_all_packages = not packages_names
        ebuilds = []
        for o in self.overlays:
            ebuilds += portage_util.GetOverlayEBuilds(
                o, use_all=looking_for_all_packages, packages=packages_names
            )
        return ebuilds

    def _get_packages_dependencies(
        self, packages_names: List[str]
    ) -> Dict[str, List[package.PackageDependency]]:
        """Return a dictionary mapping package names to their dependencies.

        The dictionary size is greater than the given |packages_names|.
        Dependencies are also mapped with depth = 1.
        """
        return self._get_packages_dependencies_depgraph(packages_names)

    def _get_packages_dependencies_depgraph(
        self, packages_names: List[str]
    ) -> Dict[str, List[package.PackageDependency]]:
        """Return a dictionary mapping packages names to their dependencies.

        The dictionary size is greater than given |packages_names|. Dependencies
        are also mapped with depth = 1.
        """
        deps_json = cros_sdk.CrosSdk(self.setup).generate_dependency_tree(
            packages_names
        )
        deps_tree = json.loads(deps_json)

        package_to_deps = {}
        for pkg in deps_tree:
            deps = deps_tree[pkg]["deps"]
            package_name = _extract_package_name(pkg)
            package_to_deps[package_name] = [
                package.PackageDependency(
                    name=_extract_package_name(d), types=deps[d]["deptypes"]
                )
                for d in deps
            ]

        # Check that all given packages have their deps fetched.
        packages_missing_deps = [
            pkg for pkg in packages_names if pkg not in package_to_deps
        ]
        if packages_missing_deps:
            raise ValueError(
                f"Some packages' deps are not fetched: {packages_missing_deps}"
            )

        return package_to_deps


def _filter_packages_dependencies(packages: List[package.Package]) -> None:
    supported_packages_names = set(p.full_name for p in packages)
    for pkg in packages:
        pkg.dependencies = _get_filter_dependencies(
            pkg, supported_packages_names
        )


def _get_filter_dependencies(
    pkg: package.Package, available_packages_names: Set[str]
) -> List[package.PackageDependency]:
    def is_supported_dependency(dep: package.PackageDependency) -> bool:
        # Filter package itself.
        if dep.name == pkg.full_name:
            return False

        # Filter unsupported or not queried dependencies.
        if dep.name not in available_packages_names:
            return False

        # Filter circular dependencies caused by PDEPEND.
        if len(dep.types) == 1 and "runtime_post" in dep.types:
            return False

        return True

    return [dep for dep in pkg.dependencies if is_supported_dependency(dep)]


def _extract_package_name(full_package_name: str) -> str:
    """Return the package's name in the format of category/name.

    Args:
        full_package_name: A simple or fully qualified package name, either
            with or without a version. For example:
            chromeos-base/some_package-0.0.1-r100

    Returns:
        The package's category and name. For example:
        chromeos-base/some_package
    """
    return package_info.parse(full_package_name).atom
