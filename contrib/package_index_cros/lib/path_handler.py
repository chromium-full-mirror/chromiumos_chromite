# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to handle filepaths between the chroot and the host filesystem.

In particular, this module is useful for mapping source filepaths from a
temporary location in the chroot to a their actual locations on the host
filesystem.
"""

import dataclasses
import logging
import os
from pathlib import Path
import re
from typing import Callable, Dict, List, Optional, Tuple

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup


class PathNotFixedException(package.PackagePathException):
    """Exception raised while while trying to fix a path."""


@dataclasses.dataclass
class FixedPath:
    """Combination of a path outside the chroot and its actual path.

    This matches a temporary downloaded src to an actual src file.
    """

    original: Path
    actual: Path


def move_path(path: Path, from_dir: Path, to_dir: Path) -> Path:
    """Replace path's base dir |from_dir| with |to_dir|.

    Raises:
        ValueError: |path| is not in |from_dir|.
    """
    return to_dir / path.relative_to(from_dir)


class PathHandler:
    """Class with helper methods to convert paths.

    The main goal is to fix paths by substituting temp paths with actual paths.
    """

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data

    def from_chroot(self, chroot_path: Path) -> Path:
        """Convert a chroot path to a host-absolute path."""
        return Path(self.setup.chroot.full_path(chroot_path))

    def to_chroot(self, path: Path) -> Path:
        """Convert an absolute host path to a chroot path."""
        return Path(self.setup.chroot.chroot_path(path))

    def _get_path_outside_of_chroot(
        self,
        chroot_path: Path,
        pkg: package.Package,
        *,
        chroot_base_dir: Optional[Path] = None,
        base_dir: Optional[Path] = None,
    ) -> Optional[Path]:
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
        if chroot_base_dir is None:
            if base_dir is None:
                raise ValueError(
                    "Either chroot_base_dir or base_dir must be set."
                )
            chroot_base_dir = self.to_chroot(base_dir)

        if Path("//") in chroot_path.parents:
            # Special case. '//' indicates source dir.
            for match_dirs in pkg.src_dir_matches:
                path_attempt = match_dirs.temp / chroot_path.relative_to("//")
                if path_attempt.exists():
                    return path_attempt
            return None

        if not chroot_path.is_absolute():
            chroot_path = chroot_base_dir / chroot_path

        # Only remove dotted paths elements, do not resolve chroot's symlinks.
        chroot_path = chroot_path.absolute()
        return self.from_chroot(chroot_path)

    def _fix_path(
        self,
        path: Path,
        pkg: package.Package,
        *,
        conflicting_paths: Dict[Path, Path],
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
        if not path or not path.exists():
            raise PathNotFixedException(
                pkg, "Given path does not exist", path, path
            )

        def fix() -> Path:
            if path in conflicting_paths:
                return conflicting_paths[path]

            # Don't care about paths outside of temp_dir.
            if pkg.temp_dir not in path.parents:
                return path

            # Build dir can be a subdir of temp_dir, but we don't care either.
            if pkg.build_dir in path.parents:
                return path

            for matching_dirs in pkg.src_dir_matches:
                if matching_dirs.temp not in path.parents:
                    continue
                actual_path = move_path(
                    path, matching_dirs.temp, matching_dirs.actual
                )
                if actual_path.exists():
                    return actual_path

            raise PathNotFixedException(
                pkg, "Could not find path in any of source dirs", path
            )

        def check(actual_path: Path) -> None:
            if not actual_path.exists():
                raise PathNotFixedException(
                    pkg, "Found path does not exist", path, actual_path
                )

        actual_path = fix().resolve()
        check(actual_path)
        return FixedPath(original=path, actual=actual_path)

    def _fix_path_from_basedir(
        self,
        chroot_path: Path,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict[Path, Path]] = None,
        ignorable_dir: Optional[Path] = None,
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

        chroot_path_base_dir = chroot_path.parent
        chroot_path_basename = chroot_path.name

        # Ignorable dir is the uppermost possible parent which may not exist.
        # If not given, use chroot_path as the ignorable dir.
        if ignorable_dir:
            chroot_ignorable_dir = self.to_chroot(ignorable_dir)
        else:
            chroot_ignorable_dir = chroot_path
        if not chroot_ignorable_dir:
            raise ValueError(chroot_ignorable_dir)

        # Try to fix the base directory of the path. If unsuccessful, move up
        # the hierarchy. Stop when we reach the ignorable dir.
        relative_path = Path(chroot_path_basename)
        while chroot_path and chroot_ignorable_dir in chroot_path.parents:
            try:
                # Try fixing the base dir of the current path.
                fixed_path = self.fix_path(
                    chroot_path_base_dir,
                    pkg,
                    conflicting_paths=conflicting_paths,
                )
                return FixedPath(
                    original=fixed_path.original / relative_path,
                    actual=fixed_path.actual / relative_path,
                )
            except PathNotFixedException:
                # If base directory fixing fails, move up one directory level
                # and repeat.
                chroot_path = chroot_path.parent
                relative_path = Path(chroot_path_base_dir.name) / relative_path
                chroot_path_base_dir = chroot_path_base_dir.parent

        raise PathNotFixedException(
            pkg, "Failed for fix from base dir", chroot_path, chroot_path
        )

    def fix_path(
        self,
        chroot_path: Path,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict[Path, Path]] = None,
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
        path = self._get_path_outside_of_chroot(
            chroot_path, pkg, base_dir=pkg.build_dir
        )
        if path is None:
            raise PathNotFixedException(
                pkg, "Cannot convert path to outside", path, path
            )
        return self._fix_path(path, pkg, conflicting_paths=conflicting_paths)

    def fix_path_with_ignores(
        self,
        chroot_path: Path,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict[Path, Path]] = None,
        ignore_highly_volatile: bool = False,
        ignore_generated: bool = False,
        ignore_stable: bool = False,
        ignorable_dirs: Optional[List[Path]] = None,
        ignorable_extensions: Optional[List[str]] = None,
    ) -> FixedPath:
        """Fix a path (like |fix_path|), but ignore some failures.

        Does not fail if given or actual path does not exist, according to given
        arguments.

        If |fix_path| fails but the issue can be ignored, attempts to fix
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

        path = self._get_path_outside_of_chroot(
            chroot_path, pkg, base_dir=pkg.build_dir
        )
        if path is None:
            raise PathNotFixedException(
                pkg, "Cannot convert path to outside", path, path
            )

        try:
            return self._fix_path(
                path, pkg, conflicting_paths=conflicting_paths
            )
        except PathNotFixedException as e:
            # Failed to fix as is. Check if the error can be ignored, and try to
            # fix from parent dir. Note that |path| can be None.

            if ignore_generated and path and pkg.build_dir in path.parents:
                # Path inside build dir and ignorable, return as is.
                logging.debug(
                    "%s: Failed to fix generated path: %s",
                    pkg.full_name,
                    path,
                )
                return FixedPath(original=path, actual=path)

            def can_ignore_failure() -> bool:
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
                if (
                    ignorable_extensions
                    and chroot_path.suffix in ignorable_extensions
                ):
                    logging.debug(
                        "%s: Failed to fix path with ignorable extension: %s",
                        pkg.full_name,
                        chroot_path,
                    )
                    return True
                return False

            if not can_ignore_failure():
                # Issue cannot be ignored. Report failure.
                raise e

            # Try to find matching ignorable dir containing path.
            ignorable_parent_dirs = [
                ignorable_dir
                for ignorable_dir in ignorable_dirs
                if path and ignorable_dir in path.parents
            ]
            if len(ignorable_parent_dirs) > 1:
                raise ValueError(
                    f"Expecting one match at most; got {ignorable_parent_dirs}"
                )
            ignorable_parent_dir = (
                ignorable_parent_dirs[0] if ignorable_parent_dirs else None
            )
            return self._fix_path_from_basedir(
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


def fix_path_in_argument(
    arg: str, fixer_callback: Callable[[Path], Path]
) -> Tuple[str, Optional[Path]]:
    """Parse |arg| into a prefix and a path.

    See |PathHandler.g_path_regex| for acceptable paths.
    See |g_argument_prefix_regex| for acceptable arguments.

    |fixer_callback| shall have chroot path as an argument and return
    corresponding actual path.

    Returns:
        A tuple of (prefix, actual_path), fixed with the given callback. If
        the arg cannot be parsed, then default to returning (arg, None).

    Raises:
        PathNotFixedException: |path| cannot be resolved to an actual path.
        PathNotFixedException: The actual path does not exist.
    """
    # Do not sanitize the arg, as it can have trailing separators required
    # for regex match.

    # Include argument may not have a path with a separator in it which is
    # required for regex. Handle it separately.
    if arg[0:2] == "-I":
        chroot_path = Path(arg[2:])
        return ("-I", fixer_callback(chroot_path))

    match = re.match(PathHandler.g_argument_regexes, arg)
    if not match:
        if not re.match(PathHandler.g_gn_target_regex, arg):
            if os.sep in arg:
                raise ValueError(f"Unknown arg with possible path: {arg}")

        # Argument is a gn target. Nothing to fix.
        return (arg, None)

    if os.sep not in arg:
        raise ValueError(f"Unknown arg: {arg}")
    prefix = match.group(1)
    chroot_path = Path(match.group(2))

    if str(chroot_path).startswith("$"):
        # Path starts with env. Do not fix.
        return (arg, None)

    return (prefix, fixer_callback(chroot_path))
