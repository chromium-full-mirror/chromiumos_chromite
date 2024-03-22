# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to handle filepaths between the chroot and the host filesystem.

In particular, this module is useful for mapping source filepaths from a
temporary location in the chroot to a their actual locations on the host
filesystem.
"""

import dataclasses
import functools
import logging
import os
import re
from typing import Callable, Dict, List, Optional, Tuple

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup


# _COMMON_NAME_REGEX matches any string that starts with a letter and contains
# letters, numbers, '.', '-', and '_'.
# Examples:
# *  some-name
# *  some_other.name
# *  name_number_3
# It has many uses, such as env var names and path components.
_COMMON_NAME_REGEX = r"(\w[\w\d\-_\.]*)"


class PathNotFixedException(package.PackagePathException):
    """Exception raised while while trying to fix a path."""


@dataclasses.dataclass
class FixedPath:
    """Combination of a path outside the chroot and its actual path.

    This matches a temporary downloaded src to an actual src file.
    """

    original: str
    actual: str


def sanitize_path(path: str) -> str:
    """Remove any trailing slashes from |path|."""
    return path.rstrip(os.path.sep)


def move_path(path: str, from_dir: str, to_dir: str) -> str:
    """Replace path's base dir |from_dir| with |to_dir|.

    Raises:
        ValueError: |path| is not in |from_dir|.
    """
    if not path.startswith(from_dir):
        raise ValueError(f"Path is not in dir: {path} vs {from_dir}")
    return os.path.realpath(
        os.path.join(to_dir, os.path.relpath(path, from_dir))
    )


class PathHandler:
    """Class with helper methods to convert paths.

    The main goal is to fix paths by substituting temp paths with actual paths.
    """

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data

    def from_chroot(self, chroot_path: str):
        return self.setup.chroot.full_path(chroot_path)

    def to_chroot(self, path: str):
        return self.setup.chroot.chroot_path(path)

    def _get_path_outside_of_chroot(
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
        if chroot_base_dir is None:
            if base_dir is None:
                raise ValueError(
                    "Either chroot_base_dir or base_dir must be set."
                )
            chroot_base_dir = self.to_chroot(base_dir)

        chroot_path = sanitize_path(chroot_path)
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

        return self.from_chroot(chroot_path)

    def _fix_path(
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
            raise PathNotFixedException(pkg, "Given path does not exist", path)

        def fix() -> str:
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
                    move_path(path, matching_dirs.temp, matching_dirs.actual)
                )
                if os.path.exists(actual_path):
                    return actual_path

            raise PathNotFixedException(
                pkg, "Could not find path in any of source dirs", path
            )

        def check(actual_path: str) -> None:
            if not os.path.exists(actual_path):
                raise PathNotFixedException(
                    pkg, "Found path does not exist", path, actual_path
                )

        actual_path = os.path.realpath(fix())
        check(actual_path)
        return FixedPath(original=path, actual=actual_path)

    def _fix_path_from_basedir(
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

        chroot_path = sanitize_path(chroot_path)
        chroot_path_base_dir = os.path.dirname(chroot_path)
        chroot_path_basename = os.path.basename(chroot_path)

        # Ignorable dir is the uppermost possible parent which may not exist.
        # If not given, use chroot_path as the ignorable dir.
        if ignorable_dir:
            chroot_ignorable_dir = self.to_chroot(sanitize_path(ignorable_dir))
        else:
            chroot_ignorable_dir = chroot_path
        if not chroot_ignorable_dir:
            raise ValueError(chroot_ignorable_dir)

        # Try to fix the base directory of the path. If unsuccessful, move up
        # the hierarchy. Stop when we reach the ignorable dir.
        while chroot_path and chroot_path.startswith(chroot_ignorable_dir):
            try:
                # Try fixing the base dir of the current path.
                fixed_path = self.fix_path(
                    chroot_path_base_dir,
                    pkg,
                    conflicting_paths=conflicting_paths,
                )
                return FixedPath(
                    original=os.path.join(
                        fixed_path.original, chroot_path_basename
                    ),
                    actual=os.path.join(
                        fixed_path.actual, chroot_path_basename
                    ),
                )
            except PathNotFixedException:
                # If base directory fixing fails, move up one directory level
                # and repeat.
                chroot_path = os.path.dirname(chroot_path)
                chroot_path_basename = os.path.join(
                    os.path.basename(chroot_path_base_dir), chroot_path_basename
                )
                chroot_path_base_dir = os.path.dirname(chroot_path_base_dir)

        raise PathNotFixedException(
            pkg, "Failed for fix from base dir", chroot_path
        )

    def fix_path(
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
        path = self._get_path_outside_of_chroot(
            chroot_path, pkg, base_dir=pkg.build_dir
        )
        if path is None:
            raise PathNotFixedException(
                pkg, "Cannot convert path to outside", path
            )
        return self._fix_path(path, pkg, conflicting_paths=conflicting_paths)

    def fix_path_with_ignores(
        self,
        chroot_path: str,
        pkg: package.Package,
        *,
        conflicting_paths: Optional[Dict] = None,
        ignore_highly_volatile: bool = False,
        ignore_generated: bool = False,
        ignore_stable: bool = False,
        ignorable_dirs: Optional[List[str]] = None,
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

        Raises:
            PathNotFixedException: |path| cannot resolve to an actual path.
            PathNotFixedException: The actual path does not exist.
        """
        if conflicting_paths is None:
            conflicting_paths = {}
        if ignorable_dirs is None:
            ignorable_dirs = []

        path = self._get_path_outside_of_chroot(
            chroot_path, pkg, base_dir=pkg.build_dir
        )
        if path is None:
            raise PathNotFixedException(
                pkg, "Cannot convert path to outside", path
            )

        try:
            return self._fix_path(
                path, pkg, conflicting_paths=conflicting_paths
            )
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
                return False

            if not can_ignore_failure():
                # Issue cannot be ignored. Report failure.
                raise e

            # Try to find matching ignorable dir containing path.
            ignorable_parent_dirs = [
                ignorable_dir
                for ignorable_dir in ignorable_dirs
                if path and path.startswith(ignorable_dir)
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


def fix_path_in_argument(
    arg: str, fixer_callback: Callable[[str], str]
) -> Tuple[str, str]:
    """Parse |arg| into a prefix and a path.

    If
    See _argument_regexes
    See |_PATH_REGEX| for acceptable paths.
    See |_ARGUMENT_REGEXES| for acceptable arguments.

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

    if _get_gn_target_regex().match(arg):
        # Argument is a gn target. Nothing to fix.
        return (arg, "")

    match = _get_argument_regex().match(arg)
    if not match:
        if os.sep in arg:
            raise ValueError(
                f"Unrecognized arg containing possible path: {arg}"
            )
        else:
            # Arg doesn't seem to contain a path. Nothing to fix.
            return (arg, "")

    prefix = match.group("prefix")
    chroot_path = match.group("path")

    if chroot_path[0] == "$":
        # Path starts with env. Do not fix.
        return (arg, "")

    return (prefix, fixer_callback(chroot_path))


@functools.lru_cache
def _get_argument_regex() -> re.Pattern:
    """Return a regex that matches a CLI argument and its path value.

    Returns:
        A compiled regex, with the following capture groups:
            prefix: Everything leading up to the value. Examples:
                *   -I
                *   :
                *   -arg=
                *   --my-arg=
                *   --my-arg=--another-arg=
                *   --my-arg=-I
                *   Mmy_proto.proto=
                *   empty string
            value: The argument's value. Must be a path. May be either absolute
                or relative. Must contain at least one slash (/), or else we
                won't know it's a path. If the value is contained in double
                quotes ("like so"), the quotes will be stripped. Examples:
                *   some/path/
                *  /some/abs/path
                *  //some/other/abs/path
                *  ./some/rel/path
                *  ../.././some/other/rel/path
                *  short_path/
    """
    # env_var_regex matches an env var usage.
    # Examples:
    # *  $ENV_VAR
    # *  ${env_var}
    env_var_regex = rf"(\$({_COMMON_NAME_REGEX}|{{{_COMMON_NAME_REGEX}}}))"

    # path_placeholder_component_regex matches a path component in
    # {{squiggle brackets}}.
    # Examples:
    # *  {{place_holder}}
    # *  {{place_holder}}hello
    path_placeholder_component_regex = (
        r"("
        # f-strings reduce double brackets to single: {{}} becomes {}.
        rf"{{{{{_COMMON_NAME_REGEX}}}}}"
        rf"{_COMMON_NAME_REGEX}?"
        r")"
    )

    # path_special_component_regex matches special path components: ".", "..".
    path_special_component_regex = r"(\.\.?)"

    # path_component_regex matches any single path component.
    # Examples:
    # *  lib64
    # *  ..
    # *  {{place_holder}}
    # *  ${env-var}
    path_component_regex = (
        r"("
        rf"{_COMMON_NAME_REGEX}|"
        rf"{path_special_component_regex}|"
        rf"{path_placeholder_component_regex}|"
        rf"{env_var_regex}"
        r")"
    )

    # abs_path_prefix_regex matches the start of an absolute path.
    # Examples:
    # *  /
    # *  //
    abs_path_prefix_regex = r"(//?)"

    # path_regex should match any path, absolute or relative, as long as it
    # contains at least one slash.
    # Examples:
    # *  some/path/
    # *  /some/abs/path
    # *  //some/other/abs/path
    # *  ./some/rel/path
    # *  ../.././some/other/rel/path
    # *  short_path/
    # Non-examples:
    # *  some_path (needs at least one slash)
    path_regex = (
        rf"("
        # May be an absolute path or not.
        rf"{abs_path_prefix_regex}?"
        # First component must end with /.
        rf"{path_component_regex}/"
        # Additional components may or may not end with /.
        rf"({path_component_regex}/?)*"
        r")"
    )

    # include_path_arg_prefix_regex matches the start of any include arg: "-I".
    include_path_arg_prefix_regex = r"(-I)"

    # colon_arg_prefix_regex matches the start of an arg indicated by ":".
    colon_arg_prefix_regex = r"(:)"

    # explicit_arg_prefix_regex matches the start an arg that begins with zero,
    # one, or two dashes, and ends with "=".
    # Examples:
    # *   --i_am_argument=
    # *   -another-argument=
    # *   argument-without-dashes=
    explicit_arg_prefix_regex = rf"(-?-?{_COMMON_NAME_REGEX}=)"

    # explicit_repeating_arg_prefix_regex matches a chain of explicit arg
    # prefixes.
    # Examples:
    # *   --argument=another-argument=
    # *   --argument=-L
    explicit_repeating_arg_prefix_regex = (
        rf"({explicit_arg_prefix_regex}({_COMMON_NAME_REGEX}=|-\w))"
    )

    # explicit_proto_arg_prefix_regex matches a proto arg prefix.
    # Examples:
    # *   Msome_proto_name.proto=
    explicit_proto_arg_prefix_regex = r"(M[\w_]+\.proto=)"

    # argument_prefix_regex should match any permissible arg prefix.
    # Examples:
    # *   -I
    # *   :
    # *   --i_am_argument=
    # *   --argument=another-argument=
    # *   Msome_proto_name.proto=
    argument_prefix_regex = (
        rf"("
        rf"{include_path_arg_prefix_regex}|"
        rf"{colon_arg_prefix_regex}|"
        rf"{explicit_arg_prefix_regex}|"
        rf"{explicit_repeating_arg_prefix_regex}|"
        rf"{explicit_proto_arg_prefix_regex}"
        r")"
    )

    # quote_with_escape matches a quote char, with or without an escape char.
    # Examples:
    # *   "
    # *   \"
    quote_with_escape = r'(\\?")'

    # argument_regex matches an argument and its value, as long as the prefix
    # matches argument_prefix_regex, and the value looks like a path.
    # If the path value is inside quotes, those won't be captured.
    # Capture groups: prefix, path
    argument_regex = re.compile(
        r"^"
        rf"(?P<prefix>{argument_prefix_regex}?)"
        # Path may be inside quote marks. Do not capture them.
        rf"{quote_with_escape}?"
        rf"(?P<path>{path_regex})"
        rf"{quote_with_escape}?"
        r"$"
    )

    return argument_regex


@functools.lru_cache
def _get_gn_target_regex() -> re.Pattern:
    """Return a regex that matches a GN target, possibly with a subtarget.

    Examples:
        //some_target
        //some_target:subtarget
    """
    return re.compile(
        r"^" rf"//{_COMMON_NAME_REGEX}" rf"(:{_COMMON_NAME_REGEX})?" r"$"
    )
