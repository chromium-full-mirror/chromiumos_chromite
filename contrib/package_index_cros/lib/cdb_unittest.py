# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for cdb.py."""

import filecmp
import json
import os
from typing import Any, Dict, Iterable, Optional, Union
from unittest import mock

import pytest

from chromite.contrib.package_index_cros.lib import cdb
from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import testing_utils


# pylint: disable=protected-access


def _make_command_dict(
    directory: Optional[str] = "some/directory",
    file: Optional[str] = "some/file",
    arguments: Optional[Iterable[str]] = ("/path/to/clang++", "some-args"),
    command: Optional[str] = "/path/to/clang++ some-args",
    output: Optional[str] = "some/output/file",
) -> Dict[str, Union[str, Iterable[str]]]:
    """Generate a dict that can be parsed into a cdb.Command.

    If any of the args is None, it will be excluded from the dict.
    """
    d = {}
    if directory is not None:
        d["directory"] = directory
    if file is not None:
        d["file"] = file
    if arguments is not None:
        # Note: `arguments` is listed as an Iterable instead of a List, because
        # the default value needed to be an immutable value besides None.
        # But really it should be a list.
        d["arguments"] = list(arguments)
    if command is not None:
        d["command"] = command
    if output is not None:
        d["output"] = output
    return d


def _make_command(**kwargs: Optional[Union[str, Iterable[str]]]) -> cdb.Command:
    """Generate a cdb.Command."""
    command_dict = _make_command_dict(**kwargs)
    return cdb.parse_compile_command(command_dict)


class ParseCompileCommandTestCase(testing_utils.TestCase):
    """Test cases for parsing compilation database JSON into Commands."""

    def test_basic(self) -> None:
        """Make sure we can create a cdb.Command object from a dict."""
        command = _make_command()
        self.assertEqual(command.directory, "some/directory")
        self.assertEqual(command.file, "some/file")
        self.assertEqual(command.arguments, ["/path/to/clang++", "some-args"])
        self.assertEqual(command.command, "/path/to/clang++ some-args")
        self.assertEqual(command.output, "some/output/file")

    def test_require_directory(self) -> None:
        """Test failing if the cdb command JSON has no directory."""
        command_dict = _make_command_dict(directory=None)
        with self.assertRaises(ValueError):
            cdb.parse_compile_command(command_dict)

    def test_require_arguments_or_command(self) -> None:
        """Test failing if the cdb command JSON has no arguments or commands."""
        command_dict = _make_command_dict(arguments=None, command=None)
        with self.assertRaises(ValueError):
            cdb.parse_compile_command(command_dict)

        # If the JSON had either arguments or command, it would be OK.
        _make_command(arguments=None)
        _make_command(command=None)

    def test_require_file(self) -> None:
        """Test failing if the cdb command JSON has no file."""
        command_dict = _make_command_dict(file=None)
        with self.assertRaises(ValueError):
            cdb.parse_compile_command(command_dict)


class GetFixedDirectoryTestCase(testing_utils.TestCase):
    """Test cases for cdb._get_fixed_directory()."""

    def test_not_build_dir(self) -> None:
        """Test a call where the directory doesn't point to pkg.build_dir."""
        # Use a path that's similar to the build_dir. If we instead passed in a
        # totally bogus path, like "/some/path", then we might not catch certain
        # bugs -- for example, if we incorrectly permitted directories that look
        # like build dirs but don't actually match this package.
        package_1 = self.new_package(package_name="package-1")
        package_2 = self.new_package(package_name="package-2")
        cdb_command = _make_command(
            directory=self.setup.chroot.chroot_path(package_1.build_dir),
            arguments=["/usr/bin/clang++", "-Irelative", "etc"],
            file="file.cc",
        )
        _cdb = cdb.Cdb([cdb_command], package_2, self.setup, {})
        with self.assertRaises(cdb.DirectoryFieldException):
            _cdb._get_fixed_directory(cdb_command)

    def test_success(self) -> None:
        """Test a basic, correct call."""
        pkg = self.new_package()
        cdb_command = _make_command(
            directory=self.setup.chroot.chroot_path(pkg.build_dir),
            arguments=["/usr/bin/clang++", "-Irelative", "etc"],
            file="file.cc",
        )
        _cdb = cdb.Cdb([cdb_command], pkg, self.setup, {})
        fixed = _cdb._get_fixed_directory(cdb_command)
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

    def test_fix_compiler(self) -> None:
        """Make sure we're fixing the first arg as a compiler."""
        command = _make_command(arguments=["/path/to/clang++"])
        _cdb = cdb.Cdb([command], self.new_package(), self.setup, {})
        self.assertEqual(
            _cdb._get_fixed_arguments(command),
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
        command = _make_command(
            arguments=["/path/to/clang++", f"-I{inside_path}"]
        )
        _cdb = cdb.Cdb(
            [command],
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
            _cdb._get_fixed_arguments(command),
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
        command = _make_command(
            arguments=["/path/to/clang++", f"-I{inside_path}"]
        )
        _cdb = cdb.Cdb(
            [command],
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
            _cdb._get_fixed_arguments(command),
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
        command = _make_command(
            arguments=["/path/to/clang++", f"-I{inside_path}"]
        )
        _cdb = cdb.Cdb(
            [command],
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
            _cdb._get_fixed_arguments(command),
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
        command = _make_command(
            arguments=["/path/to/clang++", f"-I{inside_path}"]
        )
        _cdb = cdb.Cdb(
            [command],
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
            _cdb._get_fixed_arguments(command),
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

        # Mock out the command object we'll try to fix.
        # The actual arguments don't matter (besides clang++). What's important
        # is that we call it enough times to get all the mock return values.
        command = _make_command(
            arguments=["/path/to/clang++", "a", "b", "c", "d", "e"]
        )
        _cdb = cdb.Cdb(
            [command], main_package, self.setup, package_to_include_args
        )
        _cdb._get_fixed_arguments(command)

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

        # Mock out the command object we'll try to fix.
        # The actual arguments don't matter (besides clang++). What's important
        # is that we call it enough times to get all the mock return values.
        command = _make_command(
            arguments=["/path/to/clang++", "a", "b", "c", "d", "e"]
        )
        _cdb = cdb.Cdb(
            [command], main_package, self.setup, package_to_include_args
        )

        self.assertEqual(
            _cdb._get_fixed_arguments(command),
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
        command = _make_command(
            arguments=["/path/to/clang++", "/some/unfixed/path"]
        )
        _cdb = cdb.Cdb([command], main_package, self.setup, {})
        with self.assertRaises(NotImplementedError):
            _cdb._get_fixed_arguments(command)


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


class GetFixedFileTestCase(testing_utils.TestCase):
    """Test cases for Cdb._get_fixed_file()."""

    def _generic_test_case(
        self,
        *,
        does_original_file_exist: bool = True,
        does_actual_file_exist: bool = True,
        is_actual_filepath_identical_to_original: bool = False,
        do_file_contents_differ: bool = False,
        is_package_highly_volatile: bool = False,
        expected_exception: Optional[Exception] = None,
    ) -> None:
        """Generic test case for Cdb._get_fixed_file.

        By default, this function will create a package, and a CDB command for
        which the "file" field points to a path inside the chroot. The host-
        absolute version of that path will be created on the filesystem.
        PathHandler will be mocked to easily return a desired actual_path, which
        will also be created. Cdb._get_fixed_file() will be called on the CDB
        command; it should return the mocked actual_path.

        Args:
            does_original_file_exist: If True, then the original file -- that
                is, the host-absolute version of the CDB command's "file" value
                -- will be created on the filesystem.
            does_actual_file_exist: If True, then the actual file (which will be
                returned by a mock method) will be created on the filesystem.
            is_actual_filepath_identical_to_original: If True, then the mocked
                actual filepath will be the same as the host-absolute original
                filepath. Otherwise, it will be a different path.
            do_file_contents_differ: If True, then the actual and original
                filepaths will have different contents.
            is_package_highly_volatile: If True, then the package will be
                considered "highly volatile".
            expected_exception: If not None, then Cdb._get_fixed_file() should
                raise this exception.
        """
        pkg = self.new_package()
        if is_package_highly_volatile:
            self.PatchObject(
                constants, "HIGHLY_VOLATILE_PACKAGES", [pkg.full_name]
            )

        inside_path = "/some/file.txt"
        outside_path = self.setup.chroot.full_path(inside_path)

        mock_actual_filepath: str
        if is_actual_filepath_identical_to_original:
            mock_actual_filepath = outside_path
        else:
            mock_actual_filepath = str(self.tempdir / "path/to/fixed/file.txt")
        fix_path_with_ignores_mock = self.PatchObject(
            path_handler.PathHandler,
            "fix_path_with_ignores",
            return_value=path_handler.FixedPath(
                original=outside_path, actual=mock_actual_filepath
            ),
        )

        if does_original_file_exist:
            self.touch(outside_path)
        if does_actual_file_exist:
            self.touch(mock_actual_filepath)
        if do_file_contents_differ:
            self.assertTrue(does_actual_file_exist)
            self.assertFalse(is_actual_filepath_identical_to_original)
            with open(mock_actual_filepath, mode="w", encoding="utf-8") as f:
                f.write("file contents!")
            self.assertFalse(filecmp.cmp(outside_path, mock_actual_filepath))

        command = _make_command(file=inside_path)
        _cdb = cdb.Cdb([command], pkg, self.setup, {})
        if expected_exception:
            with self.assertRaises(expected_exception):
                _cdb._get_fixed_file(command)
        else:
            self.assertEqual(
                _cdb._get_fixed_file(command), mock_actual_filepath
            )
            fix_path_with_ignores_mock.assert_called_with(
                inside_path,
                pkg,
                conflicting_paths={},
                ignore_generated=True,
                ignore_highly_volatile=True,
            )

    def test_original_file_is_equal_to_actual_file(self) -> None:
        """Test a simple case where the fixed path equals the original.

        Note that "original" is a weird word here. FixedPath converts an inside
        path to an outside path before it stores it as the "original". So really
        we're checking whether the fixed path is the OUTSIDE version of the
        chroot path we passed in.
        """
        self._generic_test_case(is_actual_filepath_identical_to_original=True)

    def test_original_file_does_not_exist(self) -> None:
        """Test that it's OK if the original file doesn't exist."""
        self._generic_test_case(does_original_file_exist=False)

    def test_fixed_file_does_not_exist(self) -> None:
        """Test that it's OK if the fixed file doesn't exist."""
        self._generic_test_case(does_actual_file_exist=False)

    def test_differing_files_volatile_package(self) -> None:
        """Test that differing files are OK for a volatile package."""
        self._generic_test_case(
            do_file_contents_differ=True,
            is_package_highly_volatile=True,
        )

    def test_differing_files_non_volatile_package(self) -> None:
        """Test that different files are not OK for a non-volatile package."""
        self._generic_test_case(
            do_file_contents_differ=True,
            expected_exception=cdb.FileFieldException,
        )


class GetFixOutputTestCase(testing_utils.TestCase):
    """Test cases for Cdb._get_fix_output()."""

    def test_no_output_field(self) -> None:
        """Make sure we fail if the command has no "output" field."""
        command = _make_command(output=None)
        _cdb = cdb.Cdb([command], self.new_package(), self.setup, {})
        with self.assertRaises(ValueError):
            _cdb._get_fix_output(command)

    def test_fix_output(self) -> None:
        """Make sure we fix the output field."""
        inside_path = "/original/output/path"
        outside_path = self.setup.chroot.full_path(inside_path)
        self.touch(outside_path)

        fix_path_with_ignores_mock = self.PatchObject(
            path_handler.PathHandler,
            "fix_path_with_ignores",
            return_value=path_handler.FixedPath(
                original=outside_path, actual="/fixed/output/path"
            ),
        )

        pkg = self.new_package()
        command = _make_command(output=inside_path)
        _cdb = cdb.Cdb([command], pkg, self.setup, {})
        self.assertEqual(_cdb._get_fix_output(command), "/fixed/output/path")
        fix_path_with_ignores_mock.assert_called_with(
            inside_path,
            pkg,
            conflicting_paths={},
            ignore_generated=True,
            ignore_highly_volatile=True,
        )


class FixTestCase(testing_utils.TestCase):
    """Test cases for Cdb.fix()."""

    def _mock_fix_path_with_ignores(
        self,
        return_path: str = "/fixed/path",
    ) -> mock.Mock:
        """Mock out PathHandler.fix_path_with_ignores().

        Args:
            return_path: The path that the mock should return.

        Returns:
            The patched method mock.
        """
        return self.PatchObject(
            path_handler.PathHandler,
            "fix_path_with_ignores",
            return_value=return_path,
        )

    def test_fix_all_fields(self) -> None:
        """Make sure we fix all the expected fields."""
        pkg = self.new_package()
        cdb_build_dir = str(self.tempdir / "cdb_build_dir")
        os.mkdir(cdb_build_dir)

        # The original directory path should always be the package's build_dir.
        # The fixed directory path should always be the CDB's build_path.
        outside_unfixed_directory_path = pkg.build_dir
        self.touch(outside_unfixed_directory_path)
        inside_unfixed_directory_path = self.setup.chroot.chroot_path(
            outside_unfixed_directory_path
        )
        expected_fixed_directory_path = cdb_build_dir

        outside_unfixed_file_path = os.path.join(
            pkg.build_dir, "some_dir/my_file.txt"
        )
        self.touch(outside_unfixed_file_path)
        inside_unfixed_file_path = self.setup.chroot.chroot_path(
            outside_unfixed_file_path
        )
        # Normally, paths in the package's build_dir should be fixed with only
        # two changes: chroot paths should be converted to host-absolute paths,
        # and they should be moved from the package's build_dir to the CDB's
        # build_dir. However, in the case of the "file" field, it should also
        # be made relative to the "directory" field (which is also the CDB's
        # build_dir).
        expected_fixed_file_path = "some_dir/my_file.txt"

        outside_unfixed_include_path = os.path.join(pkg.build_dir, "include_me")
        self.touch(outside_unfixed_include_path)
        inside_unfixed_include_path = self.setup.chroot.chroot_path(
            outside_unfixed_include_path
        )
        inside_unfixed_include_arg = f"-I{inside_unfixed_include_path}"
        # Since the include path is in the package's build_dir, we expect it to
        # be moved to the CDB's build_dir.
        expected_fixed_include_path = os.path.join(cdb_build_dir, "include_me")
        expected_fixed_include_arg = f"-I{expected_fixed_include_path}"

        outside_unfixed_output_path = os.path.join(pkg.build_dir, "out_path")
        self.touch(outside_unfixed_output_path)
        inside_unfixed_output_path = self.setup.chroot.chroot_path(
            outside_unfixed_output_path
        )
        # Since the output path is in the package's build_dir, we expect it to
        # be moved to the CDB's build_dir.
        expected_fixed_output_path = os.path.join(cdb_build_dir, "out_path")

        command = _make_command(
            directory=inside_unfixed_directory_path,
            file=inside_unfixed_file_path,
            arguments=["/path/to/clang++", inside_unfixed_include_arg],
            output=inside_unfixed_output_path,
        )
        _cdb = cdb.Cdb(
            [command], pkg, self.setup, {}, result_build_dir=cdb_build_dir
        )
        result = _cdb.fix()
        self.assertEqual(result, _cdb)

        expected_fixed_cdb_command = cdb.Command(
            arguments=None,
            directory=expected_fixed_directory_path,
            file=expected_fixed_file_path,
            command=f"clang++ -stdlib=libc++ {expected_fixed_include_arg}",
            output=expected_fixed_output_path,
        )
        self.assertEqual(_cdb.commands, [expected_fixed_cdb_command])


class GenerateCdbForPackageTestCase(testing_utils.TestCase):
    """Test cases for CdbGenerator._generate_cdb_for_package()."""

    _cdb_command_dict = {
        "arguments": ["clang++"],
        "file": "/some/file",
        "directory": "/some/dir",
    }
    _cdb_command = cdb.Command(
        arguments=["clang++"],
        file="/some/file",
        directory="/some/dir",
        command=None,
        output=None,
    )

    def _mock_generate_compile_commands(self, stdout: Any) -> mock.Mock:
        """Mock out the return value for CrosSdk.generate_compile_commands().

        Args:
            stdout: The raw string that CrosSdk.generate_compile_commands()
                should return. Typically this is a json.dumps()'d version of the
                object you actually want to return.
        """
        return self.PatchObject(
            cros_sdk.CrosSdk, "generate_compile_commands", return_value=stdout
        )

    def test_basic(self) -> None:
        """Basic test case: initialize a cdb.Cdb."""
        result_build_dir = str(self.tempdir / "cdb_build_dir")
        file_conflicts = {"/path1": "/path2", "/path3": "/path4"}
        cdb_generator = cdb.CdbGenerator(
            self.setup,
            result_build_dir=result_build_dir,
            file_conflicts=file_conflicts,
        )
        packages_to_include_args = {
            "chromeos-base/some-package": cdb._IncludePathOrder(
                local={"-Isome/local/path"},
                generated={"-Isome/generated/path"},
                chroot=set(),
            )
        }
        self._mock_generate_compile_commands(
            json.dumps([self._cdb_command_dict])
        )

        _cdb = cdb_generator._generate_cdb_for_package(
            self.new_package(), packages_to_include_args
        )
        self.assertEqual(_cdb.commands, [self._cdb_command])
        self.assertEqual(_cdb.package_to_include_args, packages_to_include_args)
        self.assertEqual(_cdb.build_dir, result_build_dir)
        self.assertEqual(_cdb.file_conflicts, file_conflicts)

    def test_empty_compile_commands(self) -> None:
        """Test case for when the generated compilation database is empty.

        Importantly, generation shouldn't fail. It should complain, and then
        return a Cdb with no compile commands.
        """
        cdb_generator = cdb.CdbGenerator(self.setup)
        pkg = self.new_package()
        self._mock_generate_compile_commands(json.dumps([]))
        with self.assertLogs(level="ERROR"):
            _cdb = cdb_generator._generate_cdb_for_package(pkg, {})
        self.assertEqual(_cdb.commands, [])

    def test_unexpected_cdb_json(self) -> None:
        """Test case for when the generated compilation database looks wrong."""
        cdb_generator = cdb.CdbGenerator(self.setup)
        pkg = self.new_package()
        for raw_compdb in (
            self._cdb_command_dict,
            str([self._cdb_command_dict]),
            123,
            True,
            None,
        ):
            self._mock_generate_compile_commands(json.dumps(raw_compdb))
            with self.assertRaises(ValueError):
                cdb_generator._generate_cdb_for_package(pkg, {})


class GenerateResultCdbTestCase(testing_utils.TestCase):
    """Test cases for CdbGenerator._generate_result_cdb()."""

    def test_two_successful_packages(self) -> None:
        """Test generating a Cdbs for two packages.

        We expect the following behavior:
        1.  CdbGenerator.package_status should show each package as a success.
        2.  Each Cdb's packages_to_include_args should be the same object. In
            particular, the first package's _IncludePathOrder should be passed
            into the second package's Cdb.
        3.  The return value should be equal to the concatenation of each Cdb's
            (fixed) compile commands.
        """
        cdb_build_dir = str(self.tempdir / "cdb_build_dir")
        os.mkdir(cdb_build_dir)

        # Set up the first package.
        # The first package will use two cdb commands, just to demonstrate that
        # we fix all the commands.
        first_pkg = self.new_package(package_name="first-package")

        # Each cdb command has a "file" field. In order for those to be fixable,
        # the original file should be a chroot path inside the package's temp
        # dir; we should create it (outside the chroot); and the package needs a
        # src_dir_match pointing to the original file's parent dir.
        # The expected fixed file should have the same filename, but inside the
        # src_dir_match's actual dir. It, too, should exist.
        first_pkg_actual_dir = self.add_src_dir_match(
            first_pkg, "x", make_actual_dir=True
        ).actual

        first_pkg_unfixed_file_1 = self.setup.chroot.chroot_path(
            os.path.join(first_pkg.temp_dir, "x/file1.txt")
        )
        self.touch(self.setup.chroot.full_path(first_pkg_unfixed_file_1))
        first_pkg_expected_fixed_file_1 = os.path.join(
            first_pkg_actual_dir, "file1.txt"
        )
        self.touch(first_pkg_expected_fixed_file_1)

        # Now the second cdb command's "file" field.
        first_pkg_unfixed_file_2 = self.setup.chroot.chroot_path(
            os.path.join(first_pkg.temp_dir, "x/file2.md")
        )
        self.touch(self.setup.chroot.full_path(first_pkg_unfixed_file_2))
        first_pkg_expected_fixed_file_2 = os.path.join(
            first_pkg_actual_dir, "file2.md"
        )
        self.touch(first_pkg_expected_fixed_file_2)

        # We want to demonstrate that include paths get passed along to packages
        # that depend on this one.
        # One of our cdb commands will have an include arg (-I/some/path).
        # We'll manage that by making it a "local" include path: the original
        # path should be inside the package's build_dir (inside the chroot), and
        # we should create it (outside the chroot).
        # The fixed path will have the same filename, but inside the
        # cdb_build_dir. It, too, must exist.
        first_pkg_unfixed_include_path = os.path.join(
            self.setup.chroot.chroot_path(first_pkg.build_dir),
            "some-local-path",
        )
        self.touch(self.setup.chroot.full_path(first_pkg_unfixed_include_path))
        first_pkg_unfixed_include_arg = f"-I{first_pkg_unfixed_include_path}"
        first_pkg_expected_fixed_include_path = os.path.join(
            cdb_build_dir, "some-local-path"
        )
        self.touch(first_pkg_expected_fixed_include_path)

        # These are the cdb_commands for the first package. We'll mock the
        # stdout of CrosSdk.generate_compile_commands to return these as JSON.
        first_pkg_unfixed_cdb_stdout = json.dumps(
            [
                {
                    "arguments": [
                        "path/to/clang++",
                        first_pkg_unfixed_include_arg,
                    ],
                    "file": first_pkg_unfixed_file_1,
                    "directory": self.setup.chroot.chroot_path(
                        first_pkg.build_dir
                    ),
                },
                {
                    "arguments": ["path/to/clang++"],
                    "file": first_pkg_unfixed_file_2,
                    "directory": self.setup.chroot.chroot_path(
                        first_pkg.build_dir
                    ),
                },
            ]
        )

        # These are the first package's expected cdb commands after fixing.
        first_pkg_expected_fixed_cdb_commands = [
            cdb.Command(
                arguments=None,
                command=(
                    "clang++ -stdlib=libc++ "
                    f"-I{first_pkg_expected_fixed_include_path}"
                ),
                file=os.path.relpath(
                    first_pkg_expected_fixed_file_1, cdb_build_dir
                ),
                directory=cdb_build_dir,
                output=None,
            ),
            cdb.Command(
                arguments=None,
                command="clang++ -stdlib=libc++",
                file=os.path.relpath(
                    first_pkg_expected_fixed_file_2, cdb_build_dir
                ),
                directory=cdb_build_dir,
                output=None,
            ),
        ]

        # Now set up the second package.
        # This one will depend on the first package. That will allow us to
        # verify that include paths get passed along.
        # For simplicity, this package will only use one cdb command, and no
        # include paths (other than the one from its dependency)
        second_pkg = self.new_package(
            package_name="second-package",
            dependencies=[
                package.PackageDependency(
                    name=first_pkg.full_name, types=["buildtime"]
                )
            ],
        )

        # Set up the cdb command's "file", as above.
        second_pkg_unfixed_file = self.setup.chroot.chroot_path(
            os.path.join(second_pkg.temp_dir, "y/file3.cpp")
        )
        self.touch(self.setup.chroot.full_path(second_pkg_unfixed_file))
        second_pkg_actual_dir = self.add_src_dir_match(
            second_pkg, "y", make_actual_dir=True
        ).actual
        second_pkg_expected_fixed_file = os.path.join(
            second_pkg_actual_dir, "file3.cpp"
        )
        self.touch(second_pkg_expected_fixed_file)

        second_pkg_unfixed_cdb_stdout = json.dumps(
            [
                {
                    "arguments": ["path/to/clang++"],
                    "file": second_pkg_unfixed_file,
                    "directory": self.setup.chroot.chroot_path(
                        second_pkg.build_dir
                    ),
                }
            ]
        )

        second_pkg_expected_fixed_cdb_commands = [
            cdb.Command(
                arguments=None,
                command=(
                    "clang++ -stdlib=libc++ "
                    f"-I{first_pkg_expected_fixed_include_path}"
                ),
                file=os.path.relpath(
                    second_pkg_expected_fixed_file, cdb_build_dir
                ),
                directory=cdb_build_dir,
                output=None,
            ),
        ]

        # generate_compile_commands will be called twice, once for each package.
        self.PatchObject(
            cros_sdk.CrosSdk,
            "generate_compile_commands",
            side_effect=[
                first_pkg_unfixed_cdb_stdout,
                second_pkg_unfixed_cdb_stdout,
            ],
        )

        # Call the function under test.
        cdb_generator = cdb.CdbGenerator(
            self.setup, result_build_dir=cdb_build_dir, fail_fast=True
        )
        result_cdb_commands = cdb_generator._generate_result_cdb(
            [first_pkg, second_pkg]
        )

        # Make assertions about the output.
        self.assertEqual(
            cdb_generator.package_status["success"],
            [first_pkg.full_name, second_pkg.full_name],
        )
        self.assertEqual(
            result_cdb_commands,
            [
                *first_pkg_expected_fixed_cdb_commands,
                *second_pkg_expected_fixed_cdb_commands,
            ],
        )

    def test_fail_fast(self) -> None:
        """Test failing on an early package, with fail_fast=True."""
        # The first package is going to fail because the file doesn't exist.
        first_pkg = self.new_package(package_name="first-package")
        first_pkg_cdb_command = {
            "arguments": ["path/to/clang++"],
            "file": "/some/random/path",
            "directory": self.setup.chroot.chroot_path(first_pkg.build_dir),
        }

        # The second package isn't going to have any compile commands, so it
        # should pass.
        second_pkg = self.new_package(package_name="second-package")

        self.PatchObject(
            cros_sdk.CrosSdk,
            "generate_compile_commands",
            side_effect=[
                json.dumps([first_pkg_cdb_command]),
                json.dumps([]),
            ],
        )
        cdb_generator = cdb.CdbGenerator(self.setup, fail_fast=True)
        with self.assertRaises(path_handler.PathNotFixedException):
            cdb_generator._generate_result_cdb([first_pkg, second_pkg])

    def test_dont_fail_fast(self) -> None:
        """Test failing on an early package, with fail_fast=False."""
        # The first package is going to fail because the file doesn't exist.
        first_pkg = self.new_package(package_name="first-package")
        first_pkg_cdb_command = {
            "arguments": ["path/to/clang++"],
            "file": "/some/random/path",
            "directory": self.setup.chroot.chroot_path(first_pkg.build_dir),
        }

        # The second package isn't going to have any compile commands, so it
        # should pass.
        second_pkg = self.new_package(package_name="second-package")

        self.PatchObject(
            cros_sdk.CrosSdk,
            "generate_compile_commands",
            side_effect=[
                json.dumps([first_pkg_cdb_command]),
                json.dumps([]),
            ],
        )
        cdb_generator = cdb.CdbGenerator(self.setup, fail_fast=False)
        cdb_generator._generate_result_cdb([first_pkg, second_pkg])
        self.assertEqual(
            cdb_generator.package_status["failed_exception"],
            [first_pkg.full_name],
        )
        self.assertEqual(
            cdb_generator.package_status["success"], [second_pkg.full_name]
        )


class GenerateTestCase(testing_utils.TestCase):
    """Test cases for CdbGenerator.generate()."""

    def test_write_to_file(self) -> None:
        """Test that when CdbGenerator.generate() writes the cdb to a file."""
        self.PatchObject(
            cdb.CdbGenerator,
            "_generate_result_cdb",
            return_value=[
                cdb.Command(
                    command="clang++ -stdlib=libc++",
                    file="some/file",
                    directory="some/directory",
                    arguments=None,
                    output=None,
                ),
            ],
        )
        pkg = self.new_package()
        result_file = str(self.tempdir / "compilation_database.json")
        cdb.CdbGenerator(self.setup).generate([pkg], result_file)
        with open(result_file, encoding="utf-8") as f:
            file_contents = json.load(f)
        self.assertEqual(
            file_contents,
            [
                {
                    "command": "clang++ -stdlib=libc++",
                    "file": "some/file",
                    "directory": "some/directory",
                }
            ],
        )
