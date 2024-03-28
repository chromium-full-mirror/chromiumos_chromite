# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for conductor.py."""

import shutil

from chromite.contrib.package_index_cros.lib import conductor
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
