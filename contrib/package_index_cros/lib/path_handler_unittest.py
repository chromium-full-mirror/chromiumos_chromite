# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for path_handler.py."""

import os
from typing import Optional, Tuple

import pytest

from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import testing_utils


class GetPathOutsideOfChrootTestCase(testing_utils.TestCase):
    """Test cases for path_handler._get_path_outside_of_chroot()."""

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
        """Test converting a source path in the package's src_dir_matches.

        Source paths are specified by the "//" prefix. In this case, if any of
        the package's src_dir_matches' `temp` dirs contains a subdir equal to
        the given source dir, then that will be returned.
        """
        outside_base_dir = self.setup.chroot.full_path("base")
        pkg = self.new_package()

        # foobar won't contain the given source path, so it will be ignored.
        self.add_src_dir_match(pkg, "foobar")

        dichotomy = self.add_src_dir_match(pkg, "hello")
        expected_result = os.path.join(dichotomy.temp, "path/to/file.txt")
        self.touch(expected_result)

        # pylint: disable-next=protected-access
        actual_result = self.path_handler._get_path_outside_of_chroot(
            "//path/to/file.txt",
            pkg,
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


class FixPathTestCase(testing_utils.TestCase):
    """Test cases for PathHandler.fix_path() and PathHandler._fix_path()."""

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

        # irrelevant/file.txt won't exist, so we expect this to be ignored.
        self.add_src_dir_match(pkg, "a", actual_path="irrelevant")

        # In contrast, we will create b/file.txt. Thus, we expect fix_path() to
        # return that path.
        dichotomy = self.add_src_dir_match(pkg, "a", actual_path="b")
        expected_fixed_path = os.path.join(dichotomy.actual, "file.txt")
        self.touch(expected_fixed_path)

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

        # irrelevant/file.txt won't exist, so we expect this to be ignored.
        self.add_src_dir_match(pkg, "a", actual_path="irrelevant")

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


class FixPathFromBasedirTestCase(testing_utils.TestCase):
    """Test cases for PathHandler._fix_path_from_basedir()."""

    def test_no_recursion(self) -> None:
        """Test a simple case: no ignorable_dir, no recursion."""
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "a/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        # The fixed path doesn't need to exist, but its basedir does.
        dichotomy = self.add_src_dir_match(
            pkg, "a", actual_path="b", make_actual_dir=True
        )
        expected_fixed_path = os.path.join(dichotomy.actual, "file.txt")

        self.assertEqual(
            # pylint: disable-next=protected-access
            self.path_handler._fix_path_from_basedir(inside_path, pkg),
            path_handler.FixedPath(
                original=outside_path,
                actual=expected_fixed_path,
            ),
        )

    def test_recursion(self) -> None:
        """Test a case that requires recursion, thanks to ignorable_dir."""
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        # `$TMP/a/b` gets fixed to `$TMP/x/y`.
        # We'll find this even though it's two dirs above the input file.
        # The fixed path doesn't need to exist.
        dichotomy = self.add_src_dir_match(
            pkg, "a/b", actual_path="x/y", make_actual_dir=True
        )
        expected_fixed_path = os.path.join(dichotomy.actual, "c/file.txt")

        self.assertEqual(
            # pylint: disable-next=protected-access
            self.path_handler._fix_path_from_basedir(
                inside_path,
                pkg,
                ignorable_dir=os.path.join(pkg.temp_dir, "a"),
            ),
            path_handler.FixedPath(
                original=outside_path,
                actual=expected_fixed_path,
            ),
        )

    def test_cannot_recurse_because_no_ignorable_dir(self) -> None:
        """Test a case that is unfixable because we're not recursing.

        This test case should be almost identical to test_recursion(), except
        without passing the ignorable_dir kwarg, and we expect an exception.
        """
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        # `$TMP/a/b` gets fixed to `$TMP/x/y`, which does exist.
        # However, we wont be able to find that fix, because it's above the
        # input path's basedir, and we don't have an ignorable_dir.
        self.add_src_dir_match(
            pkg, "a/b", actual_path="x/y", make_actual_dir=True
        )

        with self.assertRaises(path_handler.PathNotFixedException):
            # pylint: disable-next=protected-access
            self.path_handler._fix_path_from_basedir(inside_path, pkg)

    def test_fixable_path_is_above_ignorable_dir(self) -> None:
        """Test a case that is unfixable because ignorable_dir is too deep."""
        pkg = self.new_package()
        outside_path = os.path.join(pkg.temp_dir, "a/b/c/file.txt")
        self.touch(outside_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)

        # `$TMP/a` gets fixed to `$TMP/x`, which does exist.
        # However, we wont be able to find that fix, because it's above the
        # ignorable_dir.
        self.add_src_dir_match(pkg, "a", actual_path="x", make_actual_dir=True)

        with self.assertRaises(path_handler.PathNotFixedException):
            # pylint: disable-next=protected-access
            self.path_handler._fix_path_from_basedir(
                inside_path,
                pkg,
                ignorable_dir=os.path.join(pkg.temp_dir, "a/b/c"),
            )


class FixPathWithIgnoresTestCase(testing_utils.TestCase):
    """Test cases for PathHandler.fix_path_with_ignores()."""

    def _get_input_paths(
        self,
        pkg: package.Package,
        relative_path: str = "a/b/c/file.txt",
        create: bool = True,
        in_build_dir_instead_of_temp_dir: bool = False,
    ) -> Tuple[str, str]:
        """Return an outside path and its chroot equivalent to use as input.

        Args:
            pkg: The package containing the files.
            relative_path: The filepath, relative to the package's temp_dir.
                (Unless in_build_dir_instead_of_temp_dir is True; see below.)
            create: If True, create the (outside) file on the filesystem.
            in_build_dir_instead_of_temp_dir: Normally, the path will be inside
                the package's temp_dir. But if this kwarg is True, then it will
                instead be inside the package's build_dir.

        Returns:
            A tuple (outside_path, inside_path), where outside_path is a
            host-absolute path pointing to a file inside the package's temp (or
            build) directory, and inside_path is the chroot path pointing to
            that same file.
        """
        root_dir = pkg.temp_dir
        if in_build_dir_instead_of_temp_dir:
            root_dir = pkg.build_dir
        outside_path = os.path.join(root_dir, relative_path)
        inside_path = self.setup.chroot.chroot_path(outside_path)
        if create:
            self.touch(outside_path)
        return (outside_path, inside_path)

    def test_ignore_generated(self) -> None:
        """Test ignoring failures for inputs inside pkg.build_dir."""
        pkg = self.new_package()
        outside_path, inside_path = self._get_input_paths(
            pkg, create=False, in_build_dir_instead_of_temp_dir=True
        )

        # Normally we expect fixing to fail, since the original path doesn't
        # exist on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # ignore_generated is particularly aggressive. It ignores all failures,
        # without resorting to _fix_path_from_basedir().
        # In this case, it won't even check whether the original path exists.
        self.assertEqual(
            self.path_handler.fix_path_with_ignores(
                inside_path, pkg, ignore_generated=True
            ),
            path_handler.FixedPath(original=outside_path, actual=outside_path),
        )

    def test_ignore_stable(self) -> None:
        """Test ignoring failures for stable packages."""
        pkg = self.new_package(
            additional_ebuild_contents="CROS_WORKON_OUTOFTREE_BUILD=1",
            create_9999_ebuild=False,
        )
        (outside_path, inside_path) = self._get_input_paths(pkg)
        dichotomy = self.add_src_dir_match(pkg, "a/b/c", make_actual_dir=True)

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # When we use ignore_stable, it should instead check the file's basedir,
        # which does have a src_dir_match.
        self.assertEqual(
            self.path_handler.fix_path_with_ignores(
                inside_path, pkg, ignore_stable=True
            ),
            path_handler.FixedPath(
                original=outside_path,
                actual=os.path.join(dichotomy.actual, "file.txt"),
            ),
        )

        # Finally, ignore_stable isn't a panacea. If the input path's basedir
        # doesn't have a src_dir_match, it should still fail.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(
                "/some/path", pkg, ignore_stable=True
            )

    def test_ignore_highly_volatile(self) -> None:
        """Test ignoring failures for highly volatile packages."""
        pkg = self.new_package()
        self.PatchObject(constants, "HIGHLY_VOLATILE_PACKAGES", pkg.full_name)
        (outside_path, inside_path) = self._get_input_paths(pkg)
        dichotomy = self.add_src_dir_match(pkg, "a/b/c", make_actual_dir=True)

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # When we use ignore_highly_volatile, it should instead check the file's
        # basedir, which does have a src_dir_match.
        self.assertEqual(
            self.path_handler.fix_path_with_ignores(
                inside_path, pkg, ignore_highly_volatile=True
            ),
            path_handler.FixedPath(
                original=outside_path,
                actual=os.path.join(dichotomy.actual, "file.txt"),
            ),
        )

        # Finally, ignore_highly_volatile isn't a panacea. If the input path's
        # basedir doesn't have a src_dir_match, it should still fail.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(
                "/some/path", pkg, ignore_highly_volatile=True
            )

    def test_ignorable_dirs(self) -> None:
        """Test ignoring failures in certain dirs."""
        pkg = self.new_package()
        (outside_path, inside_path) = self._get_input_paths(pkg)
        dichotomy = self.add_src_dir_match(pkg, "a", make_actual_dir=True)

        # Normally we expect fixing to fail, since we didn't create file.txt in
        # the actual dir on the filesystem.
        with self.assertRaises(path_handler.PathNotFixedException):
            self.path_handler.fix_path_with_ignores(inside_path, pkg)

        # When we use ignorable_dirs, it should walk up the filetree until it
        # finds the src_dir_match at a/.
        self.assertEqual(
            self.path_handler.fix_path_with_ignores(
                inside_path, pkg, ignorable_dirs=[dichotomy.temp]
            ),
            path_handler.FixedPath(
                original=outside_path,
                actual=os.path.join(dichotomy.actual, "b/c/file.txt"),
            ),
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
