# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for cdb.py."""

from chromite.contrib.package_index_cros.lib import cdb
from chromite.contrib.package_index_cros.lib import testing_utils


class GetFixedDirectoryTestCase(testing_utils.TestCase):
    """Test cases for cdb._get_fixed_directory()."""

    def test_no_directory(self) -> None:
        """Test a call where the cdb entry doesn't contain 'directory'."""
        cdb_entry = {
            "arguments": ["/usr/bin/clang++", "-Irelative", "etc"],
            "file": "file.cc",
        }
        cdb_data = [cdb_entry]
        _cdb = cdb.Cdb(cdb_data, self.new_package(), self.setup, {})
        with self.assertRaises(ValueError):
            # pylint: disable-next=protected-access
            _cdb._get_fixed_directory(cdb_entry)

    def test_not_build_dir(self) -> None:
        """Test a call where the directory doesn't point to pkg.build_dir."""
        # Use a path that's similar to the build_dir. If we instead passed in a
        # totally bogus path, like "/some/path", then we might not catch certain
        # bugs -- for example, if we incorrectly permitted directories that look
        # like build dirs but don't actually match this package.
        package_1 = self.new_package(package_name="package-1")
        package_2 = self.new_package(package_name="package-2")
        cdb_entry = {
            "directory": self.setup.chroot.chroot_path(package_1.build_dir),
            "arguments": ["/usr/bin/clang++", "-Irelative", "etc"],
            "file": "file.cc",
        }
        cdb_data = [cdb_entry]
        _cdb = cdb.Cdb(cdb_data, package_2, self.setup, {})
        with self.assertRaises(cdb.DirectoryFieldException):
            # pylint: disable-next=protected-access
            _cdb._get_fixed_directory(cdb_entry)

    def test_success(self) -> None:
        """Test a basic, correct call."""
        pkg = self.new_package()
        cdb_entry = {
            "directory": self.setup.chroot.chroot_path(pkg.build_dir),
            "arguments": ["/usr/bin/clang++", "-Irelative", "etc"],
            "file": "file.cc",
        }
        cdb_data = [cdb_entry]
        _cdb = cdb.Cdb(cdb_data, pkg, self.setup, {})
        # pylint: disable-next=protected-access
        fixed = _cdb._get_fixed_directory(cdb_entry)
        self.assertEqual(fixed, pkg.build_dir)
