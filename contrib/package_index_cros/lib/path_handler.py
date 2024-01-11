# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to handle filepaths between the chroot and the host filesystem.

In particular, this module is useful for mapping source filepaths from a
temporary location in the chroot to a their actual locations on the host
filesystem.
"""

import logging
import os
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup


class PathNotFixedException(package.PackagePathException):
    """Exception raised while while trying to fix a path."""


class FixedPath(NamedTuple):
    """Data class to represent a path outside the chroot and its actual path.

    This matches a temporary downloaded src to an actual src file.
    """

    original: str
    actual: str


class PathHandler:
    """Class with helper methods to convert paths.

    The main goal is to fix paths by substituting temp paths with actual paths.
    """

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data

    @staticmethod
    def SanitizePath(path: str) -> str:
        """Remove any trailing slashes from |path|."""
        return path.rstrip(os.path.sep)

    @staticmethod
    def MovePath(path: str, from_dir: str, to_dir: str) -> str:
        """Replace path's base dir |from_dir| with |to_dir|.

        Raises:
            ValueError: |path| is not in |from_dir|.
        """
        if not path.startswith(from_dir):
            raise ValueError(f"Path is not in dir: {path} vs {from_dir}")
        return os.path.realpath(
            os.path.join(to_dir, os.path.relpath(path, from_dir))
        )

    def FromChroot(self, chroot_path: str):
        return self.setup.chroot.full_path(chroot_path)

    def ToChroot(self, path: str):
        return self.setup.chroot.chroot_path(path)

    def _GetPathOutsideOfChroot(
        self,
        chroot_path: str,
        pkg: package.Package,
        *,
        chroot_base_dir: Optional[str] = None,
        base_dir: Optional[str] = None,
    ) -> Optional[str]:
        """Convert a path inside the chroot to an outside path.

        If the path is relative, then it will return an absolute dir with
        |chroot_base_dir| as the base dir.

        Either |chroot_base_dir| or |base_dir| shall be specified. If
        |chroot_base_dir| is given, |base_dir| is ignored. If |base_dir| is
        given, it is resolved to chroot path and used as |chroot_base_dir|.

        Args:
            chroot_path: a path inside chroot.
            pkg: a package that path belongs to.
            chroot_base_dir: base dir for relative |chroot_path| inside chroot.
            base_dir: base dir for relative |chroot_path| outside of chroot.

        Returns:
            Path outside of chroot if able to move; otherwise, None.
        """
        chroot_path = PathHandler.SanitizePath(chroot_path)

        assert (
            chroot_base_dir or base_dir
        ), "Either chroot_base_dir or base_dir must be set"
        if not chroot_base_dir:
            chroot_base_dir = self.ToChroot(base_dir)

        if chroot_path.startswith("//"):
            # Special case. '//' indicates source dir.
            for match_dirs in pkg.src_dir_matches:
                path_attempt = os.path.join(match_dirs.temp, chroot_path[2:])
                if os.path.exists(path_attempt):
                    return path_attempt
            return None

        if not os.path.isabs(chroot_path):
            chroot_path = os.path.join(chroot_base_dir, chroot_path)

        # Only remove dotted paths elements, do not resolve chroot's symlinks.
        chroot_path = os.path.normpath(chroot_path)

        return self.FromChroot(chroot_path)

    def _FixPath(
        self,
        path: str,
        pkg: package.Package,
        *,
        conflicting_paths: Dict[str, str],
    ) -> FixedPath:
        """Map a temporary source path (outside the chroot) to its actual path.

        Args:
            path: A temporary, copied source path outside the chroot.
            pkg: A package that path belongs to.
            conflicting_paths: Dict of paths outside of chroot that have
                conflicts between packages.

        Returns:
            Pair of |path| and corresponding actual path.

        Raises:
            PathNotFixedException: Original path does not exist.
            PathNotFixedException: Cannot resolve |path| to actual path.
            PathNotFixedException: Actual path does not exist.
        """
        if not path or not os.path.exists(path):
            raise PathNotFixedException(
                pkg, "Given path does not exist", path, path
            )

        def Fix() -> str:
            if path in conflicting_paths:
                return conflicting_paths[path]

            if not path.startswith(pkg.temp_dir) or path.startswith(
                pkg.build_dir
            ):
                # Don't care about paths outside of temp_dir.
                # Build dir can be subdir of temp_dir, but we don't care either.
                return path

            for matching_dirs in pkg.src_dir_matches:
                if not path.startswith(matching_dirs.temp):
                    continue
                actual_path = os.path.realpath(
                    PathHandler.MovePath(
                        path, matching_dirs.temp, matching_dirs.actual
                    )
                )
                if os.path.exists(actual_path):
                    return actual_path

            raise PathNotFixedException(
                pkg, "Could not find path in any of source dirs", path
            )

        def Check(actual_path: str) -> None:
            if not os.path.exists(actual_path):
                raise PathNotFixedException(
                    pkg, "Found path does not exist", path, actual_path
                )

        actual_path = os.path.realpath(Fix())
        Check(actual_path)
        return PathHandler.FixedPath(path, actual_path)

    def _FixPathFromBasedir(
        self,
        chroot_path: str,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict[str, str]] = None,
        ignorable_dir: Optional[str] = None,
    ) -> FixedPath:
        """Fix chroot_path's base dir, and append its basename to the fixed dir.

        Will attempt to fix the base dir until |ignorable_dir| has at least one
        dir containing the given chroot_path.

        For example, say the function was called with chroot_path='/a/b/c/d/e'
        and ignorable_dir=='/a/b/c'. In the filesystem, '/a/b/c' does not exist,
        but '/a/b' does exist.
        1.  chroot_path == '/a/b/c/d/e' which does not exist. Parent also does
            not exist, so go up the hierarchy.
        2.  chroot_path == '/a/b/c/d' which does not exist. Parent also does not
            exist, so go up the hierarchy.
        3.  chroot_path == '/a/b/c' which does not exist. Parent does exist, so
            fix the path.
        4.  return '/fixed-a-b/' + 'c/d/e'

        Raises:
            PathNotFixedException: Cannot resolve path most possible parent dir
                to actual path.
            PathNotFixedException: Actual path's most possible parent dir does
                not exist.
        """
        if conflicting_paths is None:
            conflicting_paths = {}

        chroot_path = PathHandler.SanitizePath(chroot_path)
        chroot_path_base_dir = os.path.dirname(chroot_path)
        chroot_path_basename = os.path.basename(chroot_path)

        # Ignorable dir is the uppermost possible parent which may not exist.
        # If not given, use chroot_path as the ignorable dir.
        if ignorable_dir:
            chroot_ignorable_dir = self.ToChroot(
                PathHandler.SanitizePath(ignorable_dir)
            )
        else:
            ignorable_dir = chroot_path
        assert chroot_ignorable_dir

        # Try to fix the base directory of the path. If unsuccessful, move up
        # the hierarchy. Stop when we reach the ignorable dir.
        while chroot_path and chroot_path.startswith(chroot_ignorable_dir):
            try:
                # Try fixing the base dir of the current path.
                path_basedir, actual_path_basedir = self.FixPath(
                    chroot_path_base_dir,
                    pkg,
                    conflicting_paths=conflicting_paths,
                )
                path = os.path.join(path_basedir, chroot_path_basename)
                actual_path = os.path.join(
                    actual_path_basedir, chroot_path_basename
                )
                return PathHandler.FixedPath(path, actual_path)
            except PathNotFixedException:
                # If base directory fixing fails, move up one directory level
                # and repeat.
                chroot_path = os.path.dirname(chroot_path)
                chroot_path_basename = os.path.join(
                    os.path.basename(chroot_path_base_dir), chroot_path_basename
                )
                chroot_path_base_dir = os.path.dirname(chroot_path_base_dir)

        raise PathNotFixedException(
            pkg, "Failed for fix from base dir", chroot_path, chroot_path
        )

    def FixPath(
        self,
        chroot_path: str,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict] = None,
    ) -> FixedPath:
        """Convert a chroot path to an original and an actual path (outside).

        A path outside of |pkg.temp_dir| is considered as actual path and
        returned as is.

        If |chroot_path| is resolved to a path which is present in
        |conflicting_paths| dict, return a path from corresponding entry.

        Args:
            chroot_path: A path inside the chroot to resolve.
            pkg: A package that path belongs to.
            conflicting_paths: Dict of paths outside of chroot that have
                conflicts between packages.

        Returns:
            Temp and actual source paths corresponding to chroot_path, outside
            the chroot.

        Raises:
            PathNotFixedException: |path| cannot be resolved to an actual path.
            PathNotFixedException: The actual path doesn't exist.
        """
        if conflicting_paths is None:
            conflicting_paths = {}
        path = self._GetPathOutsideOfChroot(
            chroot_path, pkg, base_dir=pkg.build_dir
        )
        return self._FixPath(path, pkg, conflicting_paths=conflicting_paths)

    def FixPathWithIgnores(
        self,
        chroot_path: str,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict] = None,
        ignore_highly_volatile: bool = False,
        ignore_generated: bool = False,
        ignore_stable: bool = False,
        ignorable_dirs: Optional[List[str]] = None,
        ignorable_extensions: Optional[List[str]] = None,
    ) -> FixedPath:
        """Fix a path (like |FixPath|), but ignore some failures.

        Does not fail if given or actual path does not exist, according to given
        arguments.

        If |FixPath| fails but the issue can be ignored, attempts to fix
        |chroot_path| parent dir or parent's parent dir until prefix matches. If
        this attempt fails as well - report failure.

        Args:
            chroot_path: A path inside the chroot to resolve.
            pkg: A package that that path belongs to.
            conflicting_paths: A dict of paths outside the chroot that have
                conflicts between packages.
            ignore_generated: If |chroot_path| is in |pkg.build_dir|, don't
                fail; instead, return as is. Unlike |ignorable_dirs|, we ignore
                anything that happens inside |pkg.build_dir|, just not path's
                parent dir.
            ignore_stable: Do not fail if |chroot_path| belongs to a stably
                built package.
            ignore_highly_volatile: Do not fail if |pkg| is considered as highly
                volatile (may contain patches which create/delete files).
            ignorable_dirs: Do not fail if path is inside one of given dirs
                outside of chroot (aka has a dir as prefix).
            ignorable_extensions: Do not fail if path ends with one of given
                extensions.

        Raises:
            PathNotFixedException: |path| cannot resolve to an actual path.
            PathNotFixedException: The actual path does not exist.
        """
        if conflicting_paths is None:
            conflicting_paths = {}
        if ignorable_dirs is None:
            ignorable_dirs = []
        if ignorable_extensions is None:
            ignorable_extensions = []

        path = self._GetPathOutsideOfChroot(
            chroot_path, pkg, base_dir=pkg.build_dir
        )

        try:
            return self._FixPath(path, pkg, conflicting_paths=conflicting_paths)
        except PathNotFixedException as e:
            # Failed to fix as is. Check if the error can be ignored, and try to
            # fix from parent dir. Note that |path| can be None.

            if ignore_generated and path and path.startswith(pkg.build_dir):
                # Path inside build dir and ignorable, return as is.
                logging.debug(
                    "%s: Failed to fix generated path: %s",
                    pkg.full_name,
                    path,
                )
                return PathHandler.FixedPath(path, path)

            def CanIgnoreFailure() -> bool:
                if ignore_highly_volatile and pkg.is_highly_volatile:
                    logging.debug(
                        "%s: Failed to fix path "
                        "for highly volatile package: %s",
                        pkg.full_name,
                        chroot_path,
                    )
                    return True
                if ignore_stable and not pkg.is_built_from_actual_sources:
                    logging.debug(
                        "%s: Failed to fix path for stable package: %s",
                        pkg.full_name,
                        chroot_path,
                    )
                    return True
                if ignorable_dirs:
                    logging.debug(
                        "%s: Failed to fix path in ignorable dir: %s",
                        pkg.full_name,
                        chroot_path,
                    )
                    return True
                if ignorable_extensions and any(
                    chroot_path.endswith(ignorable_ext)
                    for ignorable_ext in ignorable_extensions
                ):
                    logging.debug(
                        "%s: Failed to fix path with ignorable extension: %s",
                        pkg.full_name,
                        chroot_path,
                    )
                    return True

            if not CanIgnoreFailure():
                # Issue cannot be ignored. Report failure.
                raise e

            # Try to find matching ignorable dir containing path.
            ignorable_parent_dirs = [
                ignorable_dir
                for ignorable_dir in ignorable_dirs
                if path and path.startswith(ignorable_dir)
            ]
            assert (
                len(ignorable_parent_dirs) <= 1
            ), "Expecting one match at most"
            ignorable_parent_dir = (
                ignorable_parent_dirs[0] if ignorable_parent_dirs else None
            )
            return self._FixPathFromBasedir(
                chroot_path,
                pkg,
                conflicting_paths=conflicting_paths,
                ignorable_dir=ignorable_parent_dir,
            )

    g_common_name_regex = r"(?:\w[\w\d\-_\.]*)"
    # Matches:
    # * $ENV_VAR
    # * ${env_var}
    g_common_env_var_name_regex = (
        r"(?:" rf"\$(?:{g_common_name_regex}|{{{g_common_name_regex}}})" r")"
    )
    # Matches:
    # * some-name
    # * some_other.name
    # * name_number_3
    # Name must start with a letter. It can include letters, numbers, '.', '-',
    # and '_'.
    g_path_simple_name_regex = g_common_name_regex
    # Matches:
    # * {{place_holder}}
    g_path_placeholder_name_regex = (
        r"(?:"
        # {{ is encoded into a single {
        rf"{{{{{g_path_simple_name_regex}}}}}"
        rf"{g_path_simple_name_regex}?"
        r")"
    )
    # Matches:
    # * .
    # * ..
    g_path_special_name_regex = r"(?:\.\.?)"
    # Matches any path name above.
    g_path_name_regex = (
        r"(?:"
        rf"{g_path_simple_name_regex}|"
        rf"{g_path_special_name_regex}|"
        rf"{g_path_placeholder_name_regex}|"
        rf"{g_common_env_var_name_regex}"
        r")"
    )
    # Matches:
    # * /
    # * //
    g_abs_path_prefix_regex = r"(?:\/\/?)"
    # Matches:
    # * some/path/
    # * /some/abs/path
    # * //some/other/abs/path
    # * ./some/rel/path
    # * ../.././some/other/rel/path
    # * short_path/
    # Does not match:
    # * some_path: needs at least one slash
    g_path_regex = (
        rf"(?:"
        # Abs path or nothing
        rf"{g_abs_path_prefix_regex}?"
        # First name ending with /
        rf"{g_path_name_regex}\/"
        # Any number of names possibly ending with /
        rf"(?:{g_path_name_regex}\/?)*"
        r")"
    )

    g_include_path_arg_prefix_regex = r"(?:-I)"
    g_colon_arg_prefix_regex = r"(?::)"
    # Matches:
    # --i_am_argument=
    # -another-argument=
    # argument-without-dashes=
    g_explicit_arg_prefix_regex = rf"(?:-?-?{g_common_name_regex}=)"
    # Matches:
    # * --argument=another-argument=
    # * --argument=-L
    g_explicit_repeating_arg_prefix_regex = (
        rf"(?:"
        rf"{g_explicit_arg_prefix_regex}"
        rf"(?:(?:{g_common_name_regex}=)|(?:-\w))"
        r")"
    )
    # Matches:
    # Msome_proto_name.proto=
    g_explicit_proto_arg_prefix_regex = r"(?:M[\w_]+\.proto=)"

    # Matches any prefix above.
    g_argument_prefix_regex = (
        rf"(?:"
        rf"{g_include_path_arg_prefix_regex}|"
        rf"{g_colon_arg_prefix_regex}|"
        rf"{g_explicit_arg_prefix_regex}|"
        rf"{g_explicit_repeating_arg_prefix_regex}|"
        rf"{g_explicit_proto_arg_prefix_regex}"
        r")"
    )

    # Matches:
    # 1. "
    # 2. \"
    g_quote_with_escape = r'(?:\\?")?'

    # Captures:
    # 1. Group 1: arg prefix
    # 2. Group 2: path
    g_argument_regexes = (
        r"^"
        rf"({g_argument_prefix_regex}?)"
        # Path may be inside quote marks. Do not capture them.
        rf"(?:{g_quote_with_escape})({g_path_regex})(?:{g_quote_with_escape})"
        r"$"
    )

    # Matches:
    # //some_target
    # //some_target:subtarget
    g_gn_target_regex = (
        r"^(?:"
        rf"(?:\/\/{g_common_name_regex})"
        rf"(?:\:{g_common_name_regex})?"
        r")$"
    )

    @staticmethod
    def FixPathInArgument(
        arg: str, fixer_callback: Callable[[str], str]
    ) -> Tuple[str, str]:
        """Parse |arg| into a prefix and a path.

        See |PathHandler.g_path_regex| for acceptable paths.
        See |g_argument_prefix_regex| for acceptable arguments.

        |fixer_callback| shall have chroot path as an argument and return
        corresponding actual path.

        Returns:
            A tuple of (prefix, actual_path), fixed with the given callback. If
            the arg cannot be parsed, then default to returning (arg, "").

        Raises:
            PathNotFixedException: |path| cannot be resolved to an actual path.
            PathNotFixedException: The actual path does not exist.
        """
        # Do not sanitize the arg, as it can have trailing separators required
        # for regex match.

        # Include argument may not have a path with a separator in it which is
        # required for regex. Handle it separately.
        if arg[0:2] == "-I":
            chroot_path = arg[2:]
            return ("-I", fixer_callback(chroot_path))

        match = re.match(PathHandler.g_argument_regexes, arg)
        if not match:
            if not re.match(PathHandler.g_gn_target_regex, arg):
                assert (
                    os.sep not in arg
                ), f"Unknown arg with possible path: {arg}"

            # Argument is a gn target. Nothing to fix.

            return (arg, "")

        assert os.sep in arg, f"Unknown arg: {arg}"
        prefix = match.group(1)
        chroot_path = match.group(2)

        if chroot_path[0] == "$":
            # Path starts with env. Do not fix.
            return (arg, "")

        return (prefix, fixer_callback(chroot_path))
