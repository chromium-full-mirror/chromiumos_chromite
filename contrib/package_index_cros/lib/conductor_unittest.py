# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for conductor.py."""

import itertools
import shutil

from chromite.contrib.package_index_cros.lib import conductor
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_sleuth
from chromite.contrib.package_index_cros.lib import testing_utils


class PrepareTestCase(testing_utils.TestCase):
    """Test cases for Conductor.Prepare()."""

    def test_board_not_set_up(self) -> None:
        """Test that we require the board dir to exist."""
        shutil.rmtree(self.setup.board_dir)
        with self.assertRaises(FileNotFoundError):
            self.conductor.prepare(["chromeos-base/some-package"])

    def test_no_supported_packages(self) -> None:
        """Test failing if we don't find any supported packages to work on."""
        self.PatchObject(
            package_sleuth.PackageSleuth,
            "list_packages",
            return_value=package_sleuth.SupportedUnsupportedPackages(
                supported=[], unsupported=["chromeos-base/unsupported-package"]
            ),
        )
        with self.assertRaises(conductor.NoSupportedPackagesException):
            self.conductor.prepare(["chromeos-base/some-package"])

    def test_duplicate_packages(self) -> None:
        """Test failing if we find duplicate packages to work on."""
        # pkg1 and pkg2 have the same category and package name.
        pkg1 = self.new_package()
        pkg2 = self.new_package(private=True)
        self.PatchObject(
            package_sleuth.PackageSleuth,
            "list_packages",
            return_value=package_sleuth.SupportedUnsupportedPackages(
                supported=[pkg1, pkg2],
                unsupported=[],
            ),
        )
        with self.assertRaises(conductor.DuplicatePackagesException):
            self.conductor.prepare(["chromeos-base/some-package"])

    def test_success(self) -> None:
        """Test a normal, successful prepare call."""
        pkg1 = self.new_package(package_name="package1")
        pkg2 = self.new_package(package_name="package2")
        self.PatchObject(
            package_sleuth.PackageSleuth,
            "list_packages",
            return_value=package_sleuth.SupportedUnsupportedPackages(
                supported=[pkg1, pkg2],
                unsupported=[],
            ),
        )
        get_sorted_packages_mock = self.PatchObject(
            conductor, "_get_sorted_packages", side_effect=lambda pkgs: pkgs
        )
        _conductor = self.conductor
        _conductor.prepare(["chromeos-base/some-package"])
        self.assertEqual(_conductor.packages, [pkg1, pkg2])
        get_sorted_packages_mock.assert_called_with([pkg1, pkg2])


# pylint: disable=protected-access
class GetSortedPackagesTestCase(testing_utils.TestCase):
    """Test cases for conductor._get_sorted_packages()."""

    def test_circular_dependencies(self) -> None:
        """Test failing if we have circular dependencies."""
        pkg1 = self.new_package(
            package_name="pkg1",
            dependencies=[
                package.PackageDependency(name="chromeos-base/pkg2", types=[])
            ],
        )
        pkg2 = self.new_package(
            package_name="pkg2",
            dependencies=[
                package.PackageDependency(name="chromeos-base/pkg1", types=[])
            ],
        )
        with self.assertRaises(ValueError):
            conductor._get_sorted_packages([pkg1, pkg2])

    def test_missing_dependencies(self) -> None:
        """Test failing if some packages' dependencies aren't provided."""
        pkg = self.new_package(
            dependencies=[
                package.PackageDependency(
                    name="chromeos-base/some-pkg", types=[]
                )
            ]
        )
        with self.assertRaises(Exception):
            conductor._get_sorted_packages([pkg])

    def test_sort(self) -> None:
        """Test sorting the most independent packages first."""
        independent_pkg = self.new_package(package_name="independent")
        lower_middle_pkg = self.new_package(
            package_name="lower-middle",
            dependencies=[
                package.PackageDependency(
                    name=independent_pkg.full_name, types=[]
                )
            ],
        )
        upper_middle_pkg = self.new_package(
            package_name="upper-middle",
            dependencies=[
                package.PackageDependency(
                    name=lower_middle_pkg.full_name, types=[]
                ),
                package.PackageDependency(
                    name=independent_pkg.full_name, types=[]
                ),
            ],
        )
        most_dependent_pkg = self.new_package(
            package_name="most-dependent",
            dependencies=[
                package.PackageDependency(
                    name=upper_middle_pkg.full_name, types=[]
                )
            ],
        )
        expected_sorted_packages = [
            independent_pkg,
            lower_middle_pkg,
            upper_middle_pkg,
            most_dependent_pkg,
        ]
        for permutation in itertools.permutations(expected_sorted_packages):
            result = conductor._get_sorted_packages(permutation)
            self.assertEqual(result, expected_sorted_packages)
