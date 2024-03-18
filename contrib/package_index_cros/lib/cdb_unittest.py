# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for cdb.py."""

import os
from typing import Optional

import pytest

from chromite.contrib.package_index_cros.lib import cdb
from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import testing_utils


# pylint: disable=protected-access


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
        fixed = _cdb._get_fixed_directory(cdb_entry)
        self.assertEqual(fixed, pkg.build_dir)


@pytest.mark.parametrize(
    ("input_compiler", "expected_return", "expected_exception"),
    (
        ("clang++", "clang++", None),
        ("/path/to/clang++", "clang++", None),
        ("/path/to/clang", "clang", None),
        ("/path/to/clang/lib", "", NotImplementedError),
        ("/path/to/gcc", "", NotImplementedError),
    ),
)
def test_fix_arguments_compiler(
    input_compiler: str,
    expected_return: str,
    expected_exception: Optional[Exception],
) -> None:
    assert bool(expected_return) ^ bool(
        expected_exception
    ), "Test case must expect either return value or exception, but not both."
    if expected_return:
        assert cdb._fix_arguments_compiler(input_compiler) == expected_return
    else:
        with pytest.raises(expected_exception):
            cdb._fix_arguments_compiler(input_compiler)


class GetFixedArgumentsTestCase(testing_utils.TestCase):
    """Test cases for cdb._get_fixed_arguments()."""

    def test_require_arguments_or_command(self) -> None:
        """Test failing if the entry has neither arguments nor commands."""
        entry_with_arguments = {"arguments": ["clang", "args"]}
        entry_with_command = {"command": "clang command"}
        entry_with_both = {
            "arguments": ["clang", "args"],
            "command": "clang command",
        }
        entry_with_neither = {}
        cdb_data = [
            entry_with_arguments,
            entry_with_command,
            entry_with_both,
            entry_with_neither,
        ]
        _cdb = cdb.Cdb(cdb_data, self.new_package(), self.setup, {})

        # This test case passes in bogus args/commands that won't be modified,
        # besides adding the standard "-stdlib=libc++".
        self.assertEqual(
            _cdb._get_fixed_arguments(entry_with_arguments),
            ["clang", "args", "-stdlib=libc++"],
        )
        # If `command` is used, it should be converted to a list.
        self.assertEqual(
            _cdb._get_fixed_arguments(entry_with_command),
            ["clang", "command", "-stdlib=libc++"],
        )
        # If both `arguments` and `command` are present, `arguments` should be
        # prioritized.
        self.assertEqual(
            _cdb._get_fixed_arguments(entry_with_both),
            ["clang", "args", "-stdlib=libc++"],
        )
        with self.assertRaises(ValueError):
            _cdb._get_fixed_arguments(entry_with_neither)

    def test_fix_compiler(self) -> None:
        """Make sure we're fixing the first arg as a compiler."""
        cdb_entry = {
            "arguments": [
                "/path/to/clang++",
            ]
        }
        _cdb = cdb.Cdb([cdb_entry], self.new_package(), self.setup, {})
        self.assertEqual(
            _cdb._get_fixed_arguments(cdb_entry),
            ["clang++", "-stdlib=libc++"],
        )

    def test_ignore_highly_volatile(self) -> None:
        """Make sure we ignore highly volatile failures when fixing arg paths.

        This test logic is mostly cribbed from path_handler_unittest.py::
        FixPathWithIgnoresTestCase::test_ignore_highly_volatile().
        """
        pkg = self.new_package()
        self.PatchObject(constants, "HIGHLY_VOLATILE_PACKAGES", pkg.full_name)

        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        cdb_build_dir = self.tempdir / "cdb_build_dir"
        cdb_entry = {"arguments": ["/path/to/clang++", f"-I{inside_path}"]}
        _cdb = cdb.Cdb(
            [cdb_entry],
            pkg,
            self.setup,
            {},
            result_build_dir=str(cdb_build_dir),
        )

        # The fixed filepath needs to be in an expected location that we can
        # categorize as local, generated, or chroot. In this case, we put it in
        # the cdb's build_dir so that it gets categorized as a generated file.
        dichotomy = self.add_src_dir_match(
            pkg, "a/b/c", actual_path="cdb_build_dir/foo", make_actual_dir=True
        )
        expected_fixed_path = os.path.join(dichotomy.actual, "file.txt")

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # When we use ignore_highly_volatile, it should instead check the file's
        # basedir, which does have a src_dir_match.
        self.assertEqual(
            _cdb._get_fixed_arguments(cdb_entry),
            ["clang++", "-stdlib=libc++", f"-I{expected_fixed_path}"],
        )

    def test_ignore_generated(self) -> None:
        """Make sure we ignore generated file failures when fixing arg paths.

        This test logic is mostly cribbed from path_handler_unittest.py::
        FixPathWithIgnoresTestCase::test_ignore_generated().
        """
        pkg = self.new_package()
        # No need to make the outside file, since ignore_generated=True is very
        # permissive.
        outside_path = os.path.join(pkg.build_dir, "a/b/c/file.txt")
        inside_path = self.setup.chroot.chroot_path(outside_path)

        cdb_build_dir = self.tempdir / "cdb_build_dir"
        cdb_entry = {"arguments": ["/path/to/clang++", f"-I{inside_path}"]}
        _cdb = cdb.Cdb(
            [cdb_entry],
            pkg,
            self.setup,
            {},
            result_build_dir=str(cdb_build_dir),
        )

        # Normally we expect fixing to fail, since the original path doesn't
        # exist on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # But since we're using ignore_generated=True, and the input path is
        # inside the package's build_dir, path_handler.fix_path_with_ignores()
        # will permit all failures and return the original path unchanged.
        # Then, _cdb._get_fixed_arguments() will move the path from the
        # package's build_dir to the cdb's build_dir.
        expected_fixed_path = cdb_build_dir / "a/b/c/file.txt"
        self.assertEqual(
            _cdb._get_fixed_arguments(cdb_entry),
            ["clang++", "-stdlib=libc++", f"-I{expected_fixed_path}"],
        )

    def test_ignore_stable(self) -> None:
        """Make sure we ignore stable package failures when fixing arg paths.

        This test logic is mostly cribbed from path_handler_unittest.py::
        FixPathWithIgnoresTestCase::test_ignore_highly_volatile().
        """
        pkg = self.new_package(
            additional_ebuild_contents="CROS_WORKON_OUTOFTREE_BUILD=1",
            create_9999_ebuild=False,
        )

        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        cdb_build_dir = self.tempdir / "cdb_build_dir"
        cdb_entry = {"arguments": ["/path/to/clang++", f"-I{inside_path}"]}
        _cdb = cdb.Cdb(
            [cdb_entry],
            pkg,
            self.setup,
            {},
            result_build_dir=str(cdb_build_dir),
        )

        # The fixed filepath needs to be in an expected location that we can
        # categorize as local, generated, or chroot. In this case, we put it in
        # the cdb's build_dir so that it gets categorized as a generated file.
        dichotomy = self.add_src_dir_match(
            pkg, "a/b/c", actual_path="cdb_build_dir/foo", make_actual_dir=True
        )
        expected_fixed_path = os.path.join(dichotomy.actual, "file.txt")

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # When we use ignore_stable, it should instead check the file's basedir,
        # which does have a src_dir_match.
        self.assertEqual(
            _cdb._get_fixed_arguments(cdb_entry),
            ["clang++", "-stdlib=libc++", f"-I{expected_fixed_path}"],
        )

    def test_ignorable_dirs(self) -> None:
        """Make sure we use setup.ignorable_dirs when fixing arg paths.

        This test logic is mostly cribbed from path_handler_unittest.py::
        FixPathWithIgnoresTestCase::test_ignore_highly_volatile().
        """
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        cdb_build_dir = self.tempdir / "cdb_build_dir"
        cdb_entry = {"arguments": ["/path/to/clang++", f"-I{inside_path}"]}
        _cdb = cdb.Cdb(
            [cdb_entry],
            pkg,
            self.setup,
            {},
            result_build_dir=str(cdb_build_dir),
        )

        # The fixed filepath needs to be in an expected location that we can
        # categorize as local, generated, or chroot. In this case, we put it in
        # the cdb's build_dir so that it gets categorized as a generated file.
        dichotomy = self.add_src_dir_match(
            pkg, "a", actual_path="cdb_build_dir/foo", make_actual_dir=True
        )

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # When we use ignorable_dirs, it should walk up the filetree until it
        # finds the src_dir_match at a/.
        # The ignorable_dirs should come from _cdb.setup.
        self.setup.ignorable_dirs = [dichotomy.temp]
        expected_fixed_path = os.path.join(dichotomy.actual, "b/c/file.txt")
        self.assertEqual(
            _cdb._get_fixed_arguments(cdb_entry),
            ["clang++", "-stdlib=libc++", f"-I{expected_fixed_path}"],
        )

    def _include_arg_with_generated_path(self) -> str:
        """Return a '-I/some/path' arg for a generated path."""
        path = os.path.join(self.setup.src_dir, "some-generated-path")
        return f"-I{path}"

    @staticmethod
    def _include_arg_with_local_path(pkg: package.Package) -> str:
        """Return a '-I/some/path' arg for a local path."""
        path = os.path.join(pkg.build_dir, "some-local-path")
        return f"-I{path}"

    def _include_arg_with_chroot_path(self) -> str:
        """Return a '-I/some/path' arg for a chroot path."""
        path = os.path.join(self.setup.chroot.path, "some-chroot-path")
        return f"-I{path}"

    def _include_arg_with_chroot_out_path(self) -> str:
        """Return a '-I/some/path' arg for a chroot path in the out/ dir."""
        path = os.path.join(
            str(self.setup.chroot.out_path), "some-chroot-out-path"
        )
        return f"-I{path}"

    def test_update_package_to_include_args(self) -> None:
        """Make sure we update package_to_include_args with our -I args.

        We should add local and generated include args, but not chroot include
        args. We also shouldn't add package dependencies' include args.
        """
        # Set up two packages: main_package and depended_package.
        # main_package depends on depended_package.
        depended_package = self.new_package(package_name="depended-package")
        main_package = self.new_package(
            dependencies=[
                package.PackageDependency(
                    name=depended_package.full_name, types=["buildtime"]
                )
            ]
        )

        # Make it look like we've already worked on depended_package.
        depended_package_include_args = cdb._IncludePathOrder(
            local={"-I/depended/local/one", "-I/depended/local/two"},
            generated={"-I/depended/gen/one", "-I/depended/gen/two"},
            chroot={"-I/depended/chroot/one", "-I/depended/chroot/two"},
        )
        package_to_include_args = {
            depended_package.full_name: depended_package_include_args,
        }

        # Mock out the fixed include paths we'll find, since this test case
        # doesn't cover the arg-fixing logic.
        generated_include_path = os.path.join(main_package.build_dir, "foo")
        local_include_path = os.path.join(self.setup.src_dir, "bar")
        chroot_include_path = os.path.join(self.setup.chroot.path, "baz")
        chroot_out_include_path = os.path.join(
            str(self.setup.chroot.out_path), "quux"
        )
        self.PatchObject(
            path_handler,
            "fix_path_in_argument",
            side_effect=[
                ("--not-an-include-arg=", "/some/other/path"),
                ("-I", chroot_include_path),
                ("-I", chroot_out_include_path),
                ("-I", local_include_path),
                ("-I", generated_include_path),
            ],
        )

        # Mock out the cdb_entry we'll try to fix.
        # The actual arguments don't matter (besides clang++). What's important
        # is that we call it enough times to get all the mock return values.
        cdb_entry = {"arguments": ["/path/to/clang++", "a", "b", "c", "d", "e"]}
        _cdb = cdb.Cdb(
            [cdb_entry], main_package, self.setup, package_to_include_args
        )
        _cdb._get_fixed_arguments(cdb_entry)

        self.assertEqual(
            package_to_include_args[main_package.full_name].local,
            {f"-I{local_include_path}"},
        )
        self.assertEqual(
            package_to_include_args[main_package.full_name].generated,
            {f"-I{generated_include_path}"},
        )
        # For whatever reason chroot_args are not saved.
        self.assertEqual(
            package_to_include_args[main_package.full_name].chroot, set()
        )

        # depended_package should not be changed.
        self.assertEqual(
            package_to_include_args[depended_package.full_name],
            depended_package_include_args,
        )

    def test_reorder_include_args(self) -> None:
        """Make sure we're reordering include (-I) args as expected.

        The expected fixed argument order is:
        1.  The compiler.
        2.  Non-include args.
        3.  Generic clang args.
        4.  Local include args, including package dependencies' local include
            args.
        5.  Generated include args, including package dependencies' generated
            include args.
        6.  Chroot include args, but NOT the dependencies' chroot include args.
        """
        # Set up two packages: main_package and depended_package.
        # main_package depends on depended_package.
        depended_package = self.new_package(package_name="depended-package")
        main_package = self.new_package(
            dependencies=[
                package.PackageDependency(
                    name=depended_package.full_name, types=["buildtime"]
                )
            ]
        )

        # Make it look like we've already worked on depended_package.
        depended_package_include_args = cdb._IncludePathOrder(
            local={"-I/depended/local/path"},
            generated={"-I/depended/generated/path"},
            chroot={"-I/depended/chroot/path"},
        )
        package_to_include_args = {
            depended_package.full_name: depended_package_include_args,
        }

        # Mock out the fixed include paths we'll find, since this test case
        # doesn't cover the arg-fixing logic.
        generated_include_path = os.path.join(main_package.build_dir, "foo")
        local_include_path = os.path.join(self.setup.src_dir, "bar")
        chroot_include_path = os.path.join(self.setup.chroot.path, "baz")
        self.PatchObject(
            path_handler,
            "fix_path_in_argument",
            side_effect=[
                ("--not-an-include-arg=", "/some/other/path"),
                ("--not-a-path-arg=", "something"),
                ("-I", chroot_include_path),
                ("-I", generated_include_path),
                ("-I", local_include_path),
            ],
        )

        # Mock out the cdb_entry we'll try to fix.
        # The actual arguments don't matter (besides clang++). What's important
        # is that we call it enough times to get all the mock return values.
        cdb_entry = {"arguments": ["/path/to/clang++", "a", "b", "c", "d", "e"]}
        _cdb = cdb.Cdb(
            [cdb_entry], main_package, self.setup, package_to_include_args
        )

        self.assertEqual(
            _cdb._get_fixed_arguments(cdb_entry),
            [
                "clang++",
                "--not-an-include-arg=/some/other/path",
                "--not-a-path-arg=something",
                "-stdlib=libc++",
                "-I/depended/local/path",
                f"-I{local_include_path}",
                "-I/depended/generated/path",
                f"-I{generated_include_path}",
                f"-I{chroot_include_path}",
            ],
        )

    def test_unexpected_include_arg(self) -> None:
        """Make sure we fail if we can't categorize an include path."""
        main_package = self.new_package()
        self.PatchObject(
            path_handler,
            "fix_path_in_argument",
            side_effect=[("-I", "/some/random/path")],
        )
        cdb_entry = {"arguments": ["/path/to/clang++", "/some/unfixed/path"]}
        _cdb = cdb.Cdb([cdb_entry], main_package, self.setup, {})
        with self.assertRaises(NotImplementedError):
            _cdb._get_fixed_arguments(cdb_entry)


class FixPathTestCase(testing_utils.TestCase):
    """Test cases for Cdb._fix_path()."""

    def test_forward_ignore_args(self) -> None:
        """Test that we forward ignore args to fix_path_with_ignores.

        In this case, we're using the `ignorable_dirs` kwarg, so most of the
        test logic is cribbed from path_handler_unittest.py::
        FixPathWithIgnoresTestCase::test_ignorable_dirs.
        """
        pkg = self.new_package()
        _cdb = cdb.Cdb([], pkg, self.setup, {})

        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)
        dichotomy = self.add_src_dir_match(pkg, "a", make_actual_dir=True)

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            _cdb._fix_path(inside_path)

        # When we use ignorable_dirs, it should walk up the filetree until it
        # finds the src_dir_match at a/.
        self.assertEqual(
            _cdb._fix_path(inside_path, ignorable_dirs=[dichotomy.temp]),
            path_handler.FixedPath(
                original=outside_path,
                actual=os.path.join(dichotomy.actual, "b/c/file.txt"),
            ),
        )

    def test_forward_file_conflicts(self) -> None:
        """Test that we forward self.file_conflicts to fix_path_with_ignores.

        Most of the test logic is cribbed from path_handler_unittest.py::
        FixPathTestCase::test_fix_conflicting_path.
        """
        inside_path = "/usr/foo.txt"
        outside_path = self.setup.chroot.full_path(inside_path)
        self.touch(outside_path)

        expected_fixed_path = self.setup.chroot.full_path("another/path.txt")
        # If expected_fixed_path doesn't exist, fix_path() will raise an error.
        self.touch(expected_fixed_path)

        pkg = self.new_package()
        _cdb = cdb.Cdb(
            [],
            pkg,
            self.setup,
            {},
            file_conflicts={outside_path: expected_fixed_path},
        )
        result = _cdb._fix_path(inside_path)
        self.assertEqual(
            result,
            path_handler.FixedPath(
                original=outside_path, actual=expected_fixed_path
            ),
        )

    def test_fixed_path_in_build_dir(self) -> None:
        """Test behavior when the fixed path is in pkg.build_dir.

        Paths in pkg.build_dir should be moved to the Cdb.build_dir. However,
        the actual file/dir won't move on the filesystem -- just the returned
        path.
        """
        pkg = self.new_package()
        cdb_build_dir = self.tempdir / "result_build_dir"
        cdb_build_dir.mkdir()
        _cdb = cdb.Cdb(
            [],
            pkg,
            self.setup,
            {},
            result_build_dir=str(cdb_build_dir),
        )

        outside_path = os.path.join(pkg.build_dir, "some/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        # PathHandler.fix_path() doesn't do much to a path inside pkg.build_dir:
        # it just converts the path from a chroot path to a host-absolute path.
        # Then Cdb._fix_path() will convert it from the package's build_dir to
        # the cdb's build_dir.
        expected_return_path = os.path.join(cdb_build_dir / "some/file.txt")
        result = _cdb._fix_path(inside_path)
        self.assertEqual(
            result,
            path_handler.FixedPath(
                original=outside_path, actual=expected_return_path
            ),
        )

        # The actual file shouldn't move.
        self.assertTrue(os.path.isfile(outside_path))
        self.assertFalse(os.path.isfile(expected_return_path))
