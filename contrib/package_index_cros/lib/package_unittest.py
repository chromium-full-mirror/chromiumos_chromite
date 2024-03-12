# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for package.py."""

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import testing_utils


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
