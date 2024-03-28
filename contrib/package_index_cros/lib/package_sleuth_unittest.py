# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for package_sleuth.py."""

import copy
import json
from typing import Any, Dict, Iterable, List
from unittest import mock

import pytest

from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_sleuth
from chromite.contrib.package_index_cros.lib import setup
from chromite.contrib.package_index_cros.lib import testing_utils
from chromite.lib import portage_util


# pylint: disable=protected-access


def _create_deptree_stdout(
    package_name_to_deps: Dict[str, Iterable[package.PackageDependency]]
) -> str:
    """Generate a valid-looking dependency tree stdout.

    The output should resemble the stdout of the print_deps script, such as:
    {
        "category/key-from-input-dict": {
            "action": "merge"
            "deps": {
                "category/value-from-input-dict": {
                    "action": "merge",
                    "deps": {},
                    "deptypes": ["values-from-input-dict", ...],
                    "root": "/build/amd64-generic"
                },
                ...
            },
            "root": "/build/amd64-generic"
        },
        ...
    }
    """
    deptree_dict: Dict[str, Any] = {}
    blank_dep_object = {
        "action": "merge",
        "deps": {},
        "root": "/build/amd64-generic/",
    }
    for package_name, dependencies in package_name_to_deps.items():
        deptree_dict[package_name] = copy.deepcopy(blank_dep_object)
        for dependency in dependencies:
            dep_object = copy.deepcopy(blank_dep_object)
            dep_object["deptypes"] = dependency.types
            deptree_dict[package_name]["deps"][dependency.name] = dep_object
    return json.dumps(deptree_dict)


class ListEbuildsTestCase(testing_utils.TestCase):
    """Test cases for PackageSleuth._list_ebuilds()."""

    def test_find_ebuilds_for_one_package_in_multiple_overlays(self) -> None:
        """Test that we find both public and private ebuilds for one pkg."""
        public_ebuild = self._create_ebuild()
        private_ebuild = self._create_ebuild(private=True)
        ebuilds = self.package_sleuth._list_ebuilds(
            ["chromeos-base/my-package"]
        )
        ebuild_paths = [ebuild.ebuild_path for ebuild in ebuilds]
        self.assertCountEqual(
            ebuild_paths,
            [public_ebuild.ebuild_path, private_ebuild.ebuild_path],
        )

    def test_find_ebuilds_for_multiple_packages(self) -> None:
        """Test that we find ebuilds for all given packages."""
        pkg1_ebuild = self._create_ebuild(package_name="pkg1")
        pkg2_ebuild = self._create_ebuild(package_name="pkg2")
        ebuilds = self.package_sleuth._list_ebuilds(
            ["chromeos-base/pkg1", "chromeos-base/pkg2"]
        )
        ebuild_paths = [ebuild.ebuild_path for ebuild in ebuilds]
        self.assertCountEqual(
            ebuild_paths, [pkg1_ebuild.ebuild_path, pkg2_ebuild.ebuild_path]
        )

    def test_some_ebuilds_not_found(self) -> None:
        """Make sure it's OK if some packages' ebuilds aren't found."""
        pkg1_ebuild = self._create_ebuild(package_name="pkg1")
        ebuilds = self.package_sleuth._list_ebuilds(
            ["chromeos-base/pkg1", "chromeos-base/pkg2"]
        )
        ebuild_paths = [ebuild.ebuild_path for ebuild in ebuilds]
        self.assertCountEqual(ebuild_paths, [pkg1_ebuild.ebuild_path])


class GetPackagesDependenciesTestCase(testing_utils.TestCase):
    """Test cases for PackageSleuth._get_packages_dependencies()."""

    def mock_generate_dependency_tree_stdout(
        self,
        package_name_to_dependencies: Dict[str, package.PackageDependency],
    ) -> mock.Mock:
        """Mock out the response from cros_sdk.generate_dependency_tree()."""
        stdout = _create_deptree_stdout(package_name_to_dependencies)
        return self.PatchObject(
            cros_sdk.CrosSdk, "generate_dependency_tree", return_value=stdout
        )

    def test_multiple_packages(self) -> None:
        """Test getting the depgraph for a few packages.

        This test creates some package dependencies, and mocks the stdout of
        cros_sdk.CrosSdk.generate_dependency_tree() to return that output. Then
        we expect PackageSleuth._get_packages_dependencies() to reconstruct the
        dependencies from that stdout.
        """
        # We'll only pass pkg1 and pkg2 into the function. Since the depgraph is
        # recursive, the print_deps script should also contain their
        # dependencies (in this case pkg3). Then, _get_packages_dependencies()
        # should parse them into the return value.
        original_pkg_to_deps = {
            "chromeos-base/pkg1": [
                package.PackageDependency("chromeos-base/pkg2", ["runtime"]),
                package.PackageDependency("chromeos-base/pkg3", ["buildtime"]),
            ],
            "chromeos-base/pkg2": [
                package.PackageDependency(
                    "chromeos-base/pkg3", ["buildtime, runtime"]
                )
            ],
            "chromeos-base/pkg3": [],
        }
        self.mock_generate_dependency_tree_stdout(original_pkg_to_deps)
        returned_pkg_to_deps = self.package_sleuth._get_packages_dependencies(
            ["chromeos-base/pkg1", "chromeos-base/pkg2"]
        )
        self.assertEqual(returned_pkg_to_deps, original_pkg_to_deps)

    def test_some_packages_missing_deps(self) -> None:
        """Test a case where some packages are missing their deps."""
        self.mock_generate_dependency_tree_stdout({"chromeos-base/pkg1": []})
        with self.assertRaises(ValueError):
            self.package_sleuth._get_packages_dependencies(
                ["chromeos-base/pkg1", "chromeos-base/pkg2"]
            )


class ListPackagesWithDepsTestCase(testing_utils.TestCase):
    """Test cases for PackageSleuth._list_packages_with_deps()."""

    def _mock_get_package_support(
        self, supported_package_names: List[str]
    ) -> mock.Mock:
        """Mock out which packages will be considered supported/unsupported.

        Any packages not listed in `supported_package_names` will be considered
        unsupported.
        """

        def get_package_support(
            ebuild: portage_util.EBuild,
            setup_data: setup.Setup,
        ) -> package.PackageSupport:
            """Mock version of package.get_package_support()."""
            del setup_data  # Unused.
            if ebuild.package in supported_package_names:
                return package.PackageSupport.SUPPORTED
            return package.PackageSupport.NO_GN_BUILD

        return self.PatchObject(
            package, "get_package_support", side_effect=get_package_support
        )

    def test_no_packages(self) -> None:
        """Test a basic case where an empty list is provided.

        This scenario isn't expected in practice, but it's a useful smoke test.
        """
        self.PatchObject(
            package_sleuth.PackageSleuth,
            "_get_packages_dependencies",
            return_value={},
        )
        self.assertEqual(
            self.package_sleuth._list_packages_with_deps([]),
            package_sleuth.SupportedUnsupportedPackages(
                supported=[], unsupported=[]
            ),
        )

    def test_sort_supported_unsupported(self) -> None:
        """Test sorting the supported packages from the unsupported ones."""
        # "chromeos-base/main-package" is the package we'll feed into
        # _list_packages_with_deps. It will be considered Supported, and it will
        # depend on "chromeos-base/supported" and "chromeos-base/unsupported".
        self._create_ebuild(package_name="main-package")
        self._create_ebuild(package_name="supported")
        self._create_ebuild(package_name="unsupported")
        self._mock_get_package_support(
            ["chromeos-base/main-package", "chromeos-base/supported"]
        )
        self.PatchObject(
            package_sleuth.PackageSleuth,
            "_get_packages_dependencies",
            return_value={
                "chromeos-base/main-package": [
                    package.PackageDependency(
                        "chromeos-base/supported", ["runtime"]
                    ),
                    package.PackageDependency(
                        "chromeos-base/unsupported", ["runtime"]
                    ),
                ],
                "chromeos-base/supported": [],
                "chromeos-base/unsupported": [],
            },
        )
        supported_unsupported = self.package_sleuth._list_packages_with_deps(
            ["chromeos-base/main-package"]
        )
        self.assertCountEqual(
            [pkg.full_name for pkg in supported_unsupported.supported],
            ["chromeos-base/supported", "chromeos-base/main-package"],
        )
        self.assertEqual(
            supported_unsupported.unsupported, ["chromeos-base/unsupported"]
        )


class FilterPackagesDependenciesTestCase(testing_utils.TestCase):
    """Test cases for PackageSleuth._filter_packages_dependencies()."""

    def test_update_dependencies(self):
        """Make sure each package's dependencies are updated in-place."""
        # main_package will start by depending on both itself and other_package.
        # However, its self-dependency should get filtered out.
        other_package = self.new_package(package_name="other-package")
        main_package = self.new_package(package_name="main-package")

        dependency_on_self = package.PackageDependency(
            name=main_package.full_name, types=["runtime"]
        )
        dependency_on_other = package.PackageDependency(
            name=other_package.full_name, types=["runtime"]
        )
        main_package.dependencies = [dependency_on_self, dependency_on_other]

        package_sleuth._filter_packages_dependencies(
            [main_package, other_package]
        )
        self.assertEqual(main_package.dependencies, [dependency_on_other])


class GetFilterDependenciesTestCase(testing_utils.TestCase):
    """Test cases for package_sleuth._get_filter_dependencies()."""

    def test_exclude_self(self) -> None:
        """Test that the package itself is excluded."""
        main_package = self.new_package(package_name="main-package")
        other_package = self.new_package(package_name="other-package")

        dependency_on_self = package.PackageDependency(
            name=main_package.full_name, types=["runtime"]
        )
        dependency_on_other = package.PackageDependency(
            name=other_package.full_name, types=["runtime"]
        )
        main_package.dependencies = [dependency_on_self, dependency_on_other]

        response = package_sleuth._get_filter_dependencies(
            main_package,
            {main_package.full_name, other_package.full_name},
        )
        self.assertEqual(response, [dependency_on_other])

    def test_exclude_unavailable_packages(self) -> None:
        """Test that we exclude any package not listed as available."""
        available_package = self.new_package(package_name="available-pkg")
        unavailable_package = self.new_package(package_name="unavailable-pkg")

        available_dependency = package.PackageDependency(
            name=available_package.full_name, types=["runtime"]
        )
        unavailable_dependency = package.PackageDependency(
            name=unavailable_package.full_name, types=["runtime"]
        )

        main_package = self.new_package(
            package_name="main-package",
            dependencies=[available_dependency, unavailable_dependency],
        )

        response = package_sleuth._get_filter_dependencies(
            main_package, {available_package.full_name}
        )
        self.assertEqual(response, [available_dependency])

    def test_exclude_pdepend(self) -> None:
        """Test that we exclude dependencies with only PDEPEND."""
        pdepend_package = self.new_package(package_name="pdepend")
        rdepend_package = self.new_package(package_name="rdepend")
        pdepend_and_rdepend_package = self.new_package(package_name="both")

        pdepend_dependency = package.PackageDependency(
            name=pdepend_package.full_name, types=["runtime_post"]
        )
        rdepend_dependency = package.PackageDependency(
            name=rdepend_package.full_name, types=["runtime"]
        )
        pdepend_and_rdepend_dependency = package.PackageDependency(
            name=pdepend_and_rdepend_package.full_name,
            types=["runtime", "runtime_post"],
        )

        main_package = self.new_package(
            package_name="main-package",
            dependencies=[
                pdepend_dependency,
                rdepend_dependency,
                pdepend_and_rdepend_dependency,
            ],
        )

        response = package_sleuth._get_filter_dependencies(
            main_package,
            {
                pdepend_package.full_name,
                rdepend_package.full_name,
                pdepend_and_rdepend_package.full_name,
            },
        )
        self.assertEqual(
            response, [rdepend_dependency, pdepend_and_rdepend_dependency]
        )


@pytest.mark.parametrize(
    "full_package_name,expected_response",
    (
        ("chromeos-base/my-package", "chromeos-base/my-package"),
        ("chromeos-base/my-package-9999", "chromeos-base/my-package"),
        ("chromeos-base/my-package-1.0.0-r3", "chromeos-base/my-package"),
    ),
)
def test_extract_package_name(
    full_package_name: str, expected_response: str
) -> None:
    """Test case for package_sleuth._extract_package_name()."""
    response = package_sleuth._extract_package_name(full_package_name)
    assert response == expected_response
