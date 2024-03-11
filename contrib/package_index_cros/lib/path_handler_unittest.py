# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for path_handler.py."""

import os
from pathlib import Path
from typing import Optional

import pytest

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_unittest
from chromite.contrib.package_index_cros.lib import path_handler


class GetPathOutsideOfChrootTestCase(package_unittest.PackageTestCase):
    """Test cases for path_handler._get_path_outside_of_chroot()."""

    @property
    def path_handler(self) -> path_handler.PathHandler:
        """Return a PathHandler we can use for testing."""
        return path_handler.PathHandler(self.setup)

    def test_neither_chroot_base_dir_nor_base_dir(self) -> None:
        """Make sure we fail if chroot_base_dir and base_dir are None."""
        with self.assertRaises(ValueError):
            # pylint: disable-next=protected-access
            self.path_handler._get_path_outside_of_chroot(
                "/some/path",
                self.new_package(),
                chroot_base_dir=None,
                base_dir=None,
            )

    def test_convert_absolute_path(self) -> None:
        """Test converting an absolute path from inside to outside."""
        outside_base_dir = self.setup.chroot.full_path("/irrelevant")
        inside_path = "/some/path.txt"
        expected_result = self.setup.chroot.full_path(inside_path)
        # pylint: disable-next=protected-access
        actual_result = self.path_handler._get_path_outside_of_chroot(
            inside_path, self.new_package(), base_dir=outside_base_dir
        )
        self.assertEqual(actual_result, expected_result)

    def test_convert_relative_path(self) -> None:
        """Test converting a relative path from inside to outside."""
        outside_base_dir = self.setup.chroot.full_path("base")
        relative_path = "some/relative/path"
        expected_result = os.path.join(outside_base_dir, relative_path)
        # pylint: disable-next=protected-access
        actual_result = self.path_handler._get_path_outside_of_chroot(
            relative_path, self.new_package(), base_dir=outside_base_dir
        )
        self.assertEqual(actual_result, expected_result)

    def test_source_dir_with_src_dir_match(self) -> None:
        """Test converting a source path in the package's src_dir_matches."""
        outside_base_dir = self.setup.chroot.full_path("base")
        my_package = self.new_package(
            src_dir_matches=[
                package.TempActualDichotomy(str(self.tempdir / "foobar"), ""),
                package.TempActualDichotomy(str(self.tempdir / "hello"), ""),
            ],
        )
        expected_result = self.tempdir / "hello" / "path/to/file.txt"
        expected_result.parent.mkdir(parents=True)
        expected_result.touch()
        # pylint: disable-next=protected-access
        actual_result = self.path_handler._get_path_outside_of_chroot(
            "//path/to/file.txt",
            my_package,
            base_dir=outside_base_dir,
        )
        self.assertEqual(actual_result, str(expected_result))

    def test_source_dir_without_src_dir_match(self) -> None:
        """Test converting a source path with no src_dir_match."""
        outside_base_dir = self.setup.chroot.full_path("base")
        my_package = self.new_package()
        self.assertIsNone(
            # pylint: disable-next=protected-access
            self.path_handler._get_path_outside_of_chroot(
                "//path/to/file.txt",
                my_package,
                base_dir=outside_base_dir,
            )
        )


class FixPathTestCase(package_unittest.PackageTestCase):
    """Test cases for PathHandler.fix_path() and PathHandler._fix_path()."""

    @property
    def path_handler(self) -> path_handler.PathHandler:
        """Return a PathHandler we can use for testing."""
        return path_handler.PathHandler(self.setup)

    def touch(self, path: str) -> None:
        """Make a file and its parents."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()

    def test_fix_conflicting_path(self) -> None:
        """Test fix_path() where the input is in conflicting_paths."""
        inside_path = "/usr/foo.txt"
        outside_path = self.setup.chroot.full_path(inside_path)
        self.touch(outside_path)

        expected_fixed_path = self.setup.chroot.full_path("another/path.txt")
        # If expected_fixed_path doesn't exist, fix_path() will raise an error.
        self.touch(expected_fixed_path)

        result = self.path_handler.fix_path(
            inside_path,
            self.new_package(),
            conflicting_paths={outside_path: expected_fixed_path},
        )
        self.assertEqual(
            result,
            path_handler.FixedPath(
                original=outside_path, actual=expected_fixed_path
            ),
        )

    def test_fix_nonexistent_path(self) -> None:
        """Test fix_path() where the input path does not exist."""
        inside_path = "/does/not/exist.txt"
        outside_path = self.setup.chroot.full_path(inside_path)

        # Make sure that the would-be response path exists. Otherwise we might
        # accidentally be testing a different code path, in which we raise a
        # PathNotFixedException because the fixed path doesn't exist.
        outside_fixed_path = self.setup.chroot.full_path("another/path.txt")
        self.touch(outside_fixed_path)

        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path(
                inside_path,
                self.new_package(),
                conflicting_paths={outside_path: outside_fixed_path},
            )

    def test_fix_path_in_temp_dir_with_src_dir_match(self) -> None:
        """Test fix_path() where the input file is in the temp dir.

        The only fixing here should be converting outside->inside.
        """
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "a/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        expected_fixed_path = os.path.join(pkg.temp_dir, "b/file.txt")
        self.touch(expected_fixed_path)

        # pylint: disable-next=protected-access
        pkg._src_dir_matches = [
            # irrelevant/file.txt won't exist, so we expect this to be ignored.
            package.TempActualDichotomy(
                temp=os.path.join(pkg.temp_dir, "a"),
                actual=os.path.join(pkg.temp_dir, "irrelevant"),
            ),
            package.TempActualDichotomy(
                temp=os.path.join(pkg.temp_dir, "a"),
                actual=os.path.join(pkg.temp_dir, "b"),
            ),
        ]

        result = self.path_handler.fix_path(inside_path, pkg)
        self.assertEqual(
            result,
            path_handler.FixedPath(
                original=outside_path,
                actual=expected_fixed_path,
            ),
        )

    def test_fix_path_in_temp_path_with_no_src_dir_match(self) -> None:
        """Test fix_path() where no fixed path exists in pkg.src_dir_matches."""
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "some/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.full_path(outside_path)

        # pylint: disable-next=protected-access
        pkg._src_dir_matches = [
            # irrelevant/file.txt won't exist, so we expect this to be ignored.
            package.TempActualDichotomy(
                temp=os.path.join(pkg.temp_dir, "a"),
                actual=os.path.join(pkg.temp_dir, "irrelevant"),
            )
        ]

        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path(inside_path, pkg)

    def test_fix_path_outside_temp_dir(self) -> None:
        """Test fix_path() where the input file is outside the temp dir.

        The only fixing here should be converting the inside path to outside.
        """
        inside_path = "/foo/bar.txt"
        outside_path = self.setup.chroot.full_path(inside_path)
        self.touch(outside_path)
        pkg = self.new_package()
        self.assertEqual(
            self.path_handler.fix_path(inside_path, pkg),
            path_handler.FixedPath(original=outside_path, actual=outside_path),
        )

    def test_fix_path_in_build_dir_in_temp_dir(self) -> None:
        """Test fix_path() where the input is in build_dir, nested in temp_dir.

        The only fixing here should be converting the inside path to outside.
        """
        pkg = self.new_package()
        # pylint: disable-next=protected-access
        pkg._build_dir = os.path.join(pkg.temp_dir, "build", "out", "Default")

        outside_path = os.path.join(pkg.build_dir, "some/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        self.assertEqual(
            self.path_handler.fix_path(inside_path, pkg),
            path_handler.FixedPath(original=outside_path, actual=outside_path),
        )

    def test_fix_path_but_fixed_path_does_not_exist(self) -> None:
        """Test fix_path() where the path we want to return does not exist."""
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "some/path.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path(
                inside_path,
                pkg,
                conflicting_paths={outside_path: "/fake/path.txt"},
            )


@pytest.mark.parametrize(
    (
        "input_arg",
        "expected_prefix",
        "expected_fixed_path",
        "expected_exception",
    ),
    (
        ('--arg=\\"escaped/path\\"', "--arg=", "escaped/path/fixed", None),
        ("just/a/path", "", "just/a/path/fixed", None),
        ("-Ifoobar", "-I", "foobar/fixed", None),
        ("//gn_target:subtarget", "//gn_target:subtarget", "", None),
        ("-Q/usr/lib", "", "", ValueError),
        ("--arg=$HOME/path", "--arg=$HOME/path", "", None),
        ("--arg=not-a-path", "--arg=not-a-path", "", None),
    ),
)
def test_fix_path_in_argument(
    input_arg: str,
    expected_prefix: str,
    expected_fixed_path: str,
    expected_exception: Optional[Exception],
) -> None:
    """Test cases for path_handler.fix_path_in_argument()."""
    fixer_callback = lambda path: f"{path}/fixed"
    if expected_exception:
        with pytest.raises(expected_exception):
            path_handler.fix_path_in_argument(input_arg, fixer_callback)
    else:
        prefix, fixed_path = path_handler.fix_path_in_argument(
            input_arg, fixer_callback
        )
        assert prefix == expected_prefix
        assert fixed_path == expected_fixed_path


@pytest.mark.parametrize(
    ("test_string", "expect_match", "expected_prefix", "expected_path"),
    (
        ("just/a/path", True, "", "just/a/path"),
        (":/usr/lib", True, ":", "/usr/lib"),
        ("--two-dashes=/usr/lib", True, "--two-dashes=", "/usr/lib"),
        ("-one-dash=/usr/lib", True, "-one-dash=", "/usr/lib"),
        ("no-dashes=/usr/lib", True, "no-dashes=", "/usr/lib"),
        ("wEiRd_-...=/usr/lib", True, "wEiRd_-...=", "/usr/lib"),
        ("--chain=link=/usr/lib", True, "--chain=link=", "/usr/lib"),
        ("--chain=-L/usr/lib", True, "--chain=-L", "/usr/lib"),
        ("Mhello.proto=/usr/lib", True, "Mhello.proto=", "/usr/lib"),
        ('--arg="quoted/path"', True, "--arg=", "quoted/path"),
        ('--arg=\\"escaped/path\\"', True, "--arg=", "escaped/path"),
        ("--arg=$HOME/path", True, "--arg=", "$HOME/path"),
        ("--arg=${HOME}/path", True, "--arg=", "${HOME}/path"),
        ("--arg=/usr/{{lib}}/home", True, "--arg=", "/usr/{{lib}}/home"),
        ("--arg=usr/.././lib", True, "--arg=", "usr/.././lib"),
        ("--arg=not-a-path", False, None, None),
        ("some random string", False, None, None),
        ("-Q/usr/lib", False, None, None),
    ),
)
def test_argument_regex(
    test_string: str,
    expect_match: bool,
    expected_prefix: Optional[str],
    expected_path: Optional[str],
) -> None:
    """Test cases for _get_argument_regex()."""
    # pylint: disable-next=protected-access
    argument_regex = path_handler._get_argument_regex()
    match = argument_regex.match(test_string)
    assert bool(match) == expect_match
    if expect_match:
        assert match.group("prefix") == expected_prefix
        assert match.group("path") == expected_path


def test_gn_target_regex() -> None:
    """Test cases for _get_gn_target_regex()."""
    # pylint: disable-next=protected-access
    gn_target_regex = path_handler._get_gn_target_regex()
    for positive_test in ("//gn_target", "//gn_target:subtarget"):
        assert gn_target_regex.match(positive_test)
    for negative_test in ("hello", "//with spaces", "//gn_target/path"):
        assert not gn_target_regex.match(negative_test)


def test_move_path() -> None:
    """Test cases for path_handler.move_path()."""
    for path, from_dir, to_dir, expected_result in (
        ("/usr/lib/foo.txt", "/usr/lib", "/usr/bin", "/usr/bin/foo.txt"),
        ("usr/lib/foo.txt", "usr/lib", "usr/bin", "usr/bin/foo.txt"),
        ("/usr/lib/foo.txt", "/usr", "/home", "/home/lib/foo.txt"),
    ):
        actual_result = path_handler.move_path(path, from_dir, to_dir)
        assert os.path.realpath(actual_result) == os.path.realpath(
            expected_result
        )
    for path, from_dir, to_dir in (
        ("/usr/lib/foo.txt", "/home", "/usr/bin"),
        ("/usr/lib/foo.txt", "usr/lib", "usr/bin"),
    ):
        with pytest.raises(ValueError):
            path_handler.move_path(path, from_dir, to_dir)
