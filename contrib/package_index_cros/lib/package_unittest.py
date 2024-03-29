# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for package.py."""

import os

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import testing_utils
from chromite.lib import portage_util


def test_package_support_enum() -> None:
    """Tests for PackageSupport.is_supported() and .is_unsupported()."""
    for package_support, expect_supported in (
        (package.PackageSupport.SUPPORTED, True),
        (package.PackageSupport.NO_LOCAL_SOURCE, False),
        (package.PackageSupport.NO_GN_BUILD, False),
        (package.PackageSupport.TEMP_NO_SUPPORT, False),
    ):
        assert package_support.is_supported() == expect_supported
        assert package_support.is_unsupported() != expect_supported


class GetPackageSupportTestCase(testing_utils.TestCase):
    """Tests for get_package_support()."""

    def test_supported_package(self) -> None:
        ebuild = self._create_ebuild()
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support.is_supported()
        assert package_support == package.PackageSupport.SUPPORTED

    def test_virtual_package(self) -> None:
        """Make sure virtual packages are always supported."""
        ebuild = self._create_ebuild(
            category="virtual",
            # No GN build should mean no support.
            cros_workon_subtrees=("no gn build",),
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support.is_supported()
        assert package_support == package.PackageSupport.SUPPORTED

    def test_no_gn_subtrees(self) -> None:
        """Make sure we cna't build packages where no subtrees use GN."""
        ebuild = self._create_ebuild(
            cros_workon_subtrees=("common-mk some-source-dir",),
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support == package.PackageSupport.NO_GN_BUILD
        assert package_support.is_unsupported()

    def test_some_gn_subtrees(self) -> None:
        """Make sure we can build packages where only some subtrees use GN."""
        ebuild = self._create_ebuild(
            cros_workon_localnames=("platform2", "another_project"),
            cros_workon_projects=("chromiumos/platform2", "some/other/project"),
            cros_workon_commits=("deadb33f", "f33bdaed"),
            cros_workon_subtrees=("this one uses gn .gn", "this one doesn't"),
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support.is_supported()
        assert package_support == package.PackageSupport.SUPPORTED

    def test_with_rust_subdir(self) -> None:
        """Make sure we don't support packages that use Rust."""
        ebuild = self._create_ebuild(
            additional_ebuild_contents='CROS_RUST_SUBDIR="foobar"',
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support == package.PackageSupport.NO_GN_BUILD
        assert package_support.is_unsupported()


# pylint: disable=protected-access
class GetTempDirTestCase(testing_utils.TestCase):
    """Test cases for Package._get_ordered_version_suffixes()."""

    def _get_expected_temp_dir(
        self,
        ebuild: portage_util.EBuild,
        version_suffix: str,
    ) -> str:
        """Return the expected temp dir for the given ebuild/version."""
        return os.path.join(
            self.setup.board_dir,
            "tmp",
            "portage",
            ebuild.category,
            f"{ebuild.pkgname}-{version_suffix}",
            "work",
        )

    def test_find_9999(self) -> None:
        """Test finding the 9999 tempdir, even if others exist."""
        ebuild = self._create_ebuild()
        os.makedirs(self._get_expected_temp_dir(ebuild, "9999"))
        os.makedirs(self._get_expected_temp_dir(ebuild, ebuild.version))
        os.makedirs(self._get_expected_temp_dir(ebuild, ebuild.version_no_rev))
        pkg = package.Package(self.setup, ebuild, [])
        self.assertEqual(
            pkg._get_temp_dir(), self._get_expected_temp_dir(ebuild, "9999")
        )

    def test_find_version(self) -> None:
        """Test finding the stable ebuild with the revision suffix."""
        ebuild = self._create_ebuild()
        os.makedirs(self._get_expected_temp_dir(ebuild, ebuild.version))
        os.makedirs(self._get_expected_temp_dir(ebuild, ebuild.version_no_rev))
        pkg = package.Package(self.setup, ebuild, [])
        self.assertEqual(
            pkg._get_temp_dir(),
            self._get_expected_temp_dir(ebuild, ebuild.version),
        )

    def test_find_version_no_rev(self) -> None:
        """Test finding the stable ebuild without the revision suffix."""
        ebuild = self._create_ebuild()
        os.makedirs(self._get_expected_temp_dir(ebuild, ebuild.version_no_rev))
        pkg = package.Package(self.setup, ebuild, [])
        self.assertEqual(
            pkg._get_temp_dir(),
            self._get_expected_temp_dir(ebuild, ebuild.version_no_rev),
        )

    def test_no_temp_dir_found(self) -> None:
        """Test failing to find any temp dir."""
        ebuild = self._create_ebuild()
        pkg = package.Package(self.setup, ebuild, [])
        with self.assertRaises(package.DirsException):
            pkg._get_temp_dir()


# pylint: disable=protected-access
class GetBuildDirTestCase(testing_utils.TestCase):
    """Test cases for Package._get_build_dir()."""

    def _get_expected_var_cache_build_dir(
        self, ebuild: portage_util.EBuild
    ) -> None:
        """Return the expected build dir in ${BOARD_DIR}/var/cache/..."""
        return os.path.join(
            self.setup.board_dir,
            "var",
            "cache",
            "portage",
            ebuild.category,
            ebuild.pkgname,
            "out",
            "Default",
        )

    def _get_expected_temp_build_dir(self, ebuild: portage_util.EBuild) -> None:
        """Return the expected build dir in ${BOARD_DIR}/build/out/Default/."""
        return os.path.join(
            self.setup.board_dir,
            "tmp",
            "portage",
            ebuild.category,
            f"{ebuild.pkgname}-9999",
            "work",
            "build",
            "out",
            "Default",
        )

    def _create_pkg_temp_dir(self, pkg: package.Package) -> None:
        """Make sure the package's temp_dir exists."""
        temp_dir = os.path.join(
            self.setup.board_dir,
            "tmp",
            "portage",
            pkg.ebuild.category,
            f"{pkg.ebuild.pkgname}-9999",
            "work",
        )
        os.makedirs(temp_dir)
        pkg._temp_dir = temp_dir

    def test_find_var_cache_build_dir(self) -> None:
        """Test finding the build dir in ${BOARD_DIR}/var/cache/..."""
        ebuild = self._create_ebuild()
        pkg = package.Package(self.setup, ebuild, [])
        self._create_pkg_temp_dir(pkg)
        var_cache_build_dir = self._get_expected_var_cache_build_dir(ebuild)
        temp_build_dir = self._get_expected_temp_build_dir(ebuild)
        for build_dir in (var_cache_build_dir, temp_build_dir):
            os.makedirs(build_dir)
            self.touch(os.path.join(build_dir, "args.gn"))
        self.assertEqual(pkg._get_build_dir(), var_cache_build_dir)

    def test_find_temp_build_dir(self) -> None:
        """Test finding the build dir inside the package's temp dir."""
        ebuild = self._create_ebuild()
        pkg = package.Package(self.setup, ebuild, [])
        self._create_pkg_temp_dir(pkg)
        temp_build_dir = self._get_expected_temp_build_dir(ebuild)
        os.makedirs(temp_build_dir)
        self.touch(os.path.join(temp_build_dir, "args.gn"))
        self.assertEqual(pkg._get_build_dir(), temp_build_dir)

    def test_no_build_dirs_exist(self) -> None:
        """Test a scenario where no build dir can be found on the filesystem."""
        ebuild = self._create_ebuild()
        pkg = package.Package(self.setup, ebuild, [])
        self._create_pkg_temp_dir(pkg)
        with self.assertRaises(package.DirsException):
            pkg._get_build_dir()

    def test_no_args_gn(self) -> None:
        """Make sure args.gn is required to find a build dir."""
        ebuild = self._create_ebuild()
        pkg = package.Package(self.setup, ebuild, [])
        self._create_pkg_temp_dir(pkg)
        var_cache_build_dir = self._get_expected_var_cache_build_dir(ebuild)
        os.makedirs(var_cache_build_dir)
        with self.assertRaises(package.DirsException):
            pkg._get_build_dir()
        self.touch(os.path.join(var_cache_build_dir, "args.gn"))
        self.assertEqual(pkg._get_build_dir(), var_cache_build_dir)
