# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to help with finding packages and their dependencies."""

import json
from typing import Dict, List, NamedTuple, Optional, Set

from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import logger
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import portage_util
from chromite.lib.parser import package_info


class SupportedUnsupportedPackages(NamedTuple):
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

    def ListPackages(
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
        packages = self._ListPackagesWithDeps(packages_names)
        PackageSleuth._FilterPackagesDependencies(packages.supported)

        return packages

    def _ListPackagesWithDeps(
        self, packages_names: List[str]
    ) -> SupportedUnsupportedPackages:
        """Return a list of packages and their transitive dependencies."""
        packages = SupportedUnsupportedPackages([], [])

        ebuilds = self._ListEbuilds(packages_names)
        dependencies = self._GetPackagesDependencies(
            [
                e.package
                for e in ebuilds
                if package.GetPackageSupport(e, self.setup).is_supported()
            ]
        )

        # packages_to_list is a list of package names to list, taken from
        # current dependencies that don't have corresponding ebuilds yet.
        listed_packages = set(e.package for e in ebuilds)
        packages_to_list = [
            package_name
            for package_name in dependencies
            if package_name not in listed_packages
        ]

        # Repeating while we have packages without ebuilds and newly found
        # dependencies without corresponding ebuild.
        while packages_to_list:
            # It's not necessary that |new_ebuilds| == |packages_to_list|.
            # new_ebuilds can be less, or even empty.
            new_ebuilds = self._ListEbuilds(packages_to_list)
            if not new_ebuilds:
                break

            # TODO: Some packages need specific USE flag for emerge (e.g.
            # arc-base needs USE=arcpp or USE=arcvm). Without them emerge fails
            # and cros-sdk raises an exception.
            new_dependencies = self._GetPackagesDependencies(
                [
                    e.package
                    for e in ebuilds
                    if package.GetPackageSupport(e, self.setup).is_supported()
                ]
            )

            ebuilds += new_ebuilds
            dependencies.update(new_dependencies)
            listed_packages.update([e.package for e in new_ebuilds])

            packages_to_list = [
                package_name
                for package_name in new_dependencies
                if package_name not in listed_packages
            ]

        for ebuild in ebuilds:
            package_supported = package.GetPackageSupport(ebuild, self.setup)
            if package_supported.is_unsupported():
                logger.g_logger.warning(
                    "%s: Not supported: %s",
                    ebuild.package,
                    package_supported.name,
                )
                packages.unsupported.append(ebuild.package)
            else:
                packages.supported.append(
                    package.Package(
                        self.setup, ebuild, dependencies[ebuild.package]
                    )
                )

        return packages

    def _ListEbuilds(self, packages_names: List[str]) -> portage_util.EBuild:
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

    def _GetPackagesDependencies(
        self, packages_names: List[str]
    ) -> Dict[str, List[package.PackageDependency]]:
        """Return a dictionary mapping package names to their dependencies.

        The dictionary size is greater than the given |packages_names|.
        Dependencies are also mapped with depth = 1.
        """
        return self._GetPackagesDependenciesDepgraph(packages_names)

    def _GetPackagesDependenciesDepgraph(
        self, packages_names: List[str]
    ) -> Dict[str, List[package.PackageDependency]]:
        """Return a dictionary mapping packages names to their dependencies.

        The dictionary size is greater than given |packages_names|. Dependencies
        are also mapped with depth = 1.
        """
        deps_json = cros_sdk.CrosSdk(self.setup).GenerateDependencyTree(
            packages_names
        )
        deps_tree = json.loads(deps_json)

        package_to_deps = {}
        for pkg in deps_tree:
            deps = deps_tree[pkg]["deps"]
            package_name = PackageSleuth._ExtractPackageName(pkg)
            package_to_deps[package_name] = [
                package.PackageDependency(
                    PackageSleuth._ExtractPackageName(d), deps[d]["deptypes"]
                )
                for d in deps
            ]

        # Check that all given packages have their deps fetched.
        assert not [
            package_name
            for package_name in packages_names
            if package_name not in package_to_deps
        ]

        return package_to_deps

    @staticmethod
    def _FilterPackagesDependencies(packages: List[package.Package]) -> None:
        supported_packages_names = set(p.full_name for p in packages)
        for pkg in packages:
            pkg.dependencies = PackageSleuth._GetFilterDependencies(
                pkg, supported_packages_names
            )

    @staticmethod
    def _GetFilterDependencies(
        pkg: package.Package, available_packages_names: Set[str]
    ) -> List[package.PackageDependency]:
        def IsSupportedDependency(dep: package.PackageDependency) -> bool:
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

        return [dep for dep in pkg.dependencies if IsSupportedDependency(dep)]

    @staticmethod
    def _ExtractPackageName(full_package_name: str) -> str:
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
