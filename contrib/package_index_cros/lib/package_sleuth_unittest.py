# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for package_sleuth.py."""

import pytest

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_sleuth
from chromite.contrib.package_index_cros.lib import testing_utils


# pylint: disable=protected-access


class ListEbuildsTestCase(testing_utils.TestCase):
    """Test cases for package_sleuth._list_ebuilds()."""

    @property
    def package_sleuth(self) -> package_sleuth.PackageSleuth:
        """Return a PackageSleuth object for testing."""
        return package_sleuth.PackageSleuth(self.setup)

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


class FilterPackagesDependenciesTestCase(testing_utils.TestCase):
    """Test cases for package_sleuth._filter_packages_dependencies()."""

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
