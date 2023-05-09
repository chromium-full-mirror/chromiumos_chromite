# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Handle path inference and translation."""

import collections
import os
from pathlib import Path
import tempfile
from typing import Callable, Iterator, List, Optional, Union

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.utils import memoize


GENERAL_CACHE_DIR = ".cache"
CHROME_CACHE_DIR = "cros_cache"

CHECKOUT_TYPE_UNKNOWN = "unknown"
CHECKOUT_TYPE_GCLIENT = "gclient"
CHECKOUT_TYPE_REPO = "repo"

CheckoutInfo = collections.namedtuple(
    "CheckoutInfo", ["type", "root", "chrome_src_dir"]
)


class ChrootPathResolver(object):
    """Perform path resolution to/from the chroot.

    Attributes:
        source_path: Value to override default source root inference.
        source_from_path_repo: Whether to infer the source root from the
            converted path's repo parent during inbound translation; overrides
            |source_path|.
        chroot_path: Full path of the chroot to use. If chroot_path is
            specified, source_path cannot be specified.
        out_path: Full path of the output directory to use.
    """

    # When chroot_path is specified, it is assumed that any reference to
    # the chroot mount point (/mnt/host/source) points back to the
    # inferred source root determined by constants.SOURCE_ROOT. For example,
    # assuming:
    #   constants.SOURCE_ROOT == /workspace/checkout/
    # and
    #   chroot_path = /custom/chroot/path :
    #
    # FromChroot('/mnt/host/source/my/file') -> /workspace/checkout/my/file
    # FromChroot('/some/other/file') -> /custom/chroot/path/some/other/file
    # ToChroot('/workspace/checkout/file') -> /mnt/host/source/file
    # ToChroot('/custom/checkout/chroot/this/file') -> /this/file

    def __init__(
        self,
        source_path: Optional[Union[str, os.PathLike]] = None,
        source_from_path_repo: bool = True,
        chroot_path: Optional[Union[str, os.PathLike]] = None,
        out_path: Optional[os.PathLike] = None,
    ):
        if chroot_path and source_path:
            raise AssertionError(
                "Either source_path or chroot_path must be specified"
            )
        if out_path and source_path:
            raise AssertionError(
                "Either source_path or out_path must be specified"
            )
        self._inside_chroot = cros_build_lib.IsInsideChroot()
        self._source_from_path_repo = source_from_path_repo
        self._custom_chroot_path = chroot_path
        self._source_path = (
            constants.SOURCE_ROOT if source_path is None else source_path
        )
        if chroot_path and self._TranslatePath(
            str(chroot_path), self._source_path, ""
        ):
            # chroot_path is inside of source_path, so assume a non-custom
            # chroot_path.
            self._custom_chroot_path = None

        # The following are only needed if outside the chroot.
        if self._inside_chroot:
            self._chroot_path = None
            self._chroot_link = None
            self._chroot_to_host_roots = None
            self._out_path = None
        else:
            self._chroot_path = self._GetSourcePathChroot(
                self._source_path, self._custom_chroot_path
            )
            if out_path is not None:
                self._out_path = out_path
            elif self._source_path is not None:
                self._out_path = (
                    Path(self._source_path) / constants.DEFAULT_OUT_DIR
                )
            else:
                self._out_path = constants.DEFAULT_OUT_PATH

            # The chroot link allows us to resolve paths when the chroot is
            # symlinked to the default location. This is generally not used, but
            # it is useful for CI for optimization purposes. We will trust them
            # not to do something dumb, like symlink to /, but this doesn't
            # enable that kind of behavior anyway, just allows resolving paths
            # correctly from outside the chroot.
            self._chroot_link = self._ReadChrootLink(self._chroot_path)

            # Initialize mapping of known root bind mounts.
            self._chroot_to_host_roots = (
                (constants.CHROOT_SOURCE_ROOT, self._source_path),
                (constants.CHROOT_CACHE_ROOT, self._GetCachePath),
                (constants.CHROOT_OUT_ROOT, self._out_path),
            )

    @classmethod
    @memoize.MemoizedSingleCall
    def _GetCachePath(cls) -> str:
        """Returns the cache directory."""
        return os.path.realpath(GetCacheDir())

    def _GetSourcePathChroot(
        self,
        source_path: Optional[str],
        custom_chroot_path: Optional[str] = None,
    ) -> Optional[str]:
        """Returns path to the chroot directory of a given source root."""
        if custom_chroot_path:
            return custom_chroot_path
        if source_path is None:
            return None
        return os.path.join(source_path, constants.DEFAULT_CHROOT_DIR)

    def _ReadChrootLink(self, path: Optional[str]) -> Optional[str]:
        """Convert a chroot symlink to its absolute path.

        This contains defaults/edge cases assumptions for chroot paths. Not
        recommended for non-chroot paths.

        Args:
            path: The path to resolve.

        Returns:
            The resolved path if the provided path is a symlink, None otherwise.
        """
        # Mainly for the "if self._source_from_path_repo:" branch in
        # _GetChrootPath. _GetSourcePathChroot can return None, so double check
        # it here.
        if not path:
            return None

        abs_path = os.path.abspath(path)
        link = osutils.ResolveSymlink(abs_path)

        # ResolveSymlink returns the passed path when the path isn't a symlink.
        # We can skip some redundant work when its falling back on the link when
        # the chroot is not a symlink.
        if link == abs_path:
            return None

        return link

    def _TranslatePath(
        self,
        path: str,
        src_root: Union[os.PathLike, str],
        dst_root_input: Union[
            Callable[[], Optional[Union[str, os.PathLike]]],
            Optional[Union[str, os.PathLike]],
        ],
    ) -> Optional[str]:
        """If |path| starts with |src_root|, replace it using |dst_root_input|.

        Args:
            path: An absolute path we want to convert to a destination
                equivalent.
            src_root: The root that path needs to be contained in.
            dst_root_input: The root we want to relocate the relative path into,
                or a function returning this value.

        Returns:
            A translated path, or None if |src_root| is not a prefix of |path|.

        Raises:
            ValueError: If |src_root| is a prefix but |dst_root_input| yields
                None, which means we don't have sufficient information to do the
                translation.
        """
        if not src_root:
            raise ValueError("No source root to translate path from")
        if not osutils.IsSubPath(path, src_root):
            return None
        dst_root = (
            dst_root_input() if callable(dst_root_input) else dst_root_input
        )
        if dst_root is None:
            raise ValueError("No target root to translate path to")
        return str(
            dst_root
            / Path(path).absolute().relative_to(Path(src_root).absolute())
        )

    def _GetChrootPath(self, path) -> str:
        """Translates a fully-expanded host |path| into a chroot equivalent.

        This checks path prefixes in order from the most to least "contained":
        the chroot itself, then the cache directory, and finally the source
        tree. The idea is to return the shortest possible chroot equivalent.

        Args:
            path: A host path to translate.

        Returns:
            An equivalent chroot path.

        Raises:
            ValueError: If |path| is not reachable from the chroot.
        """
        # Preliminary: compute the actual source and chroot paths to use. These
        # are generally the precomputed values, unless we're inferring the
        # source root from the path itself.
        source_path = self._source_path
        chroot_path = self._chroot_path
        chroot_link = self._chroot_link

        if self._custom_chroot_path is None and self._source_from_path_repo:
            path_repo_dir = git.FindRepoDir(path)
            if path_repo_dir is not None:
                source_path = os.path.abspath(os.path.join(path_repo_dir, ".."))
            chroot_path = self._GetSourcePathChroot(source_path)
            chroot_link = self._ReadChrootLink(chroot_path)

        # NB: This mirrors self._chroot_to_host_roots, with tweaks due to
        # per-|path| dynamic handling of |self._source_from_path_repo|. If you
        # update one, you might need to update both.
        host_to_chroot_roots = (
            # Check if the path happens to be in the chroot already.
            (chroot_path, "/"),
            # Or in the symlinked dir.
            (chroot_link, "/"),
            # Check the cache directory.
            (self._GetCachePath(), constants.CHROOT_CACHE_ROOT),
            (self._out_path, constants.CHROOT_OUT_ROOT),
            # Check the current SDK checkout tree.
            (source_path, constants.CHROOT_SOURCE_ROOT),
        )

        for src_root, dst_root in host_to_chroot_roots:
            if src_root is None:
                continue
            new_path = self._TranslatePath(path, src_root, dst_root)
            if new_path is not None:
                return new_path

        raise ValueError("Path is not reachable from the chroot")

    def _GetHostPath(self, path) -> str:
        """Translates a fully-expanded chroot |path| into a host equivalent.

        We first attempt translation of known roots (source). If any is
        successful, we check whether the result happens to point back to the
        chroot, in which case we trim the chroot path prefix and recurse. If
        neither was successful, just prepend the chroot path.

        Args:
            path: A chroot path to translate.

        Returns:
            An equivalent host path.

        Raises:
            ValueError: If |path| could not be mapped to a proper host
                destination.
        """
        new_path = None

        # Attempt resolution of known roots.
        for src_root, dst_root in self._chroot_to_host_roots:
            new_path = self._TranslatePath(path, src_root, dst_root)
            if new_path is not None:
                break

        if new_path is None:
            # If no known root was identified, just prepend the chroot path.
            new_path = self._TranslatePath(path, "/", self._chroot_path)
        else:
            # Check whether the resolved path happens to point back at the
            # chroot, in which case trim the chroot path or link prefix and
            # continue recursively.
            path = self._TranslatePath(new_path, self._chroot_path, "/")
            if path is None and self._chroot_link:
                path = self._TranslatePath(new_path, self._chroot_link, "/")

            if path is not None:
                new_path = self._GetHostPath(path)

        return new_path

    def _ConvertPath(self, path, get_converted_path) -> str:
        """Expands |path|; if outside the chroot, applies |get_converted_path|.

        Args:
            path: A path to be converted.
            get_converted_path: A conversion function.

        Returns:
            An expanded and (if needed) converted path.

        Raises:
            ValueError: If path conversion failed.
        """
        # NOTE: We do not want to expand wrapper script symlinks because this
        # prevents them from working. Therefore, if the path points to a file we
        # only resolve its dirname but leave the basename intact. This means our
        # path resolution might return unusable results for file symlinks that
        # point outside the reachable space. These are edge cases in which the
        # user is expected to resolve the realpath themselves in advance.
        expanded_path = os.path.expanduser(path)
        if os.path.isfile(expanded_path):
            expanded_path = os.path.join(
                os.path.realpath(os.path.dirname(expanded_path)),
                os.path.basename(expanded_path),
            )
        else:
            expanded_path = os.path.realpath(expanded_path)

        if self._inside_chroot:
            return expanded_path

        try:
            return get_converted_path(expanded_path)
        except ValueError as e:
            raise ValueError("%s: %s" % (e, path))

    def ToChroot(self, path: Union[str, os.PathLike]) -> str:
        """Resolves current environment |path| for use in the chroot."""
        return self._ConvertPath(path, self._GetChrootPath)

    def FromChroot(self, path: Union[str, os.PathLike]) -> str:
        """Resolves chroot |path| for use in the current environment."""
        return self._ConvertPath(path, self._GetHostPath)


def DetermineCheckout(cwd=None) -> CheckoutInfo:
    """Gather information on the checkout we are in.

    There are several checkout types, as defined by CHECKOUT_TYPE_XXX variables.
    This function determines what checkout type |cwd| is in, for example, if
    |cwd| belongs to a `repo` checkout.

    Returns:
        CheckoutInfo object with these attributes:
            type: The type of checkout.  Valid values are CHECKOUT_TYPE_*.
            root: The root of the checkout.
            chrome_src_dir: If the checkout is a Chrome checkout, the path to
                the Chrome src/ directory.
    """
    checkout_type = CHECKOUT_TYPE_UNKNOWN
    root, path = None, None

    cwd = cwd or os.getcwd()
    for path in osutils.IteratePathParents(cwd):
        gclient_file = os.path.join(path, ".gclient")
        if os.path.exists(gclient_file):
            checkout_type = CHECKOUT_TYPE_GCLIENT
            break
        repo_dir = os.path.join(path, ".repo")
        if os.path.isdir(repo_dir):
            checkout_type = CHECKOUT_TYPE_REPO
            break

    if checkout_type != CHECKOUT_TYPE_UNKNOWN:
        # TODO(vapier): Change this function to pathlib Path.
        root = str(path)

    # Determine the chrome src directory.
    chrome_src_dir = None
    if checkout_type == CHECKOUT_TYPE_GCLIENT:
        chrome_src_dir = os.path.join(root, "src")

    return CheckoutInfo(checkout_type, root, chrome_src_dir)


def FindCacheDir() -> str:
    """Returns the cache directory location based on the checkout type."""
    checkout = DetermineCheckout()
    if checkout.type == CHECKOUT_TYPE_REPO:
        return os.path.join(checkout.root, GENERAL_CACHE_DIR)
    elif checkout.type == CHECKOUT_TYPE_GCLIENT:
        return os.path.join(checkout.chrome_src_dir, "build", CHROME_CACHE_DIR)
    elif checkout.type == CHECKOUT_TYPE_UNKNOWN:
        return os.path.join(tempfile.gettempdir(), "chromeos-cache")
    else:
        raise AssertionError("Unexpected type %s" % checkout.type)


def GetCacheDir() -> str:
    """Returns the current cache dir."""
    return os.environ.get(constants.SHARED_CACHE_ENVVAR, FindCacheDir())


def ToChrootPath(
    path: Optional[Union[str, os.PathLike]],
    source_path: Optional[Union[str, os.PathLike]] = None,
    chroot_path: Optional[Union[str, os.PathLike]] = None,
    out_path: Optional[os.PathLike] = None,
) -> str:
    """Resolves current environment |path| for use in the chroot.

    Args:
        path: string path to translate into chroot namespace.
        source_path: string path to root of source checkout with chroot in it.
        chroot_path: string name of the full chroot path to use.
        out_path: Path name of the full out path to use.

    Returns:
        The same path converted to "inside chroot" namespace.

    Raises:
        ValueError: If the path references a location not available in the
            chroot.
    """
    return ChrootPathResolver(
        source_path=source_path, chroot_path=chroot_path, out_path=out_path
    ).ToChroot(path)


def FromChrootPath(
    path: Optional[Union[str, os.PathLike]],
    source_path: Optional[Union[str, os.PathLike]] = None,
    chroot_path: Optional[Union[str, os.PathLike]] = None,
    out_path: Optional[os.PathLike] = None,
) -> str:
    """Resolves chroot |path| for use in the current environment.

    Args:
        path: string path to translate out of chroot namespace.
        source_path: string path to root of source checkout with chroot in it.
        chroot_path: string name of the full chroot path to use
        out_path: Path name of the full out path to use

    Returns:
        The same path converted to "outside chroot" namespace.
    """
    return ChrootPathResolver(
        source_path=source_path, chroot_path=chroot_path, out_path=out_path
    ).FromChroot(path)


def normalize_paths_to_source_root(
    source_paths: List[str], source_root: str = constants.SOURCE_ROOT
) -> List[str]:
    """Return the "normalized" list of source paths relative to |source_root|.

    Normalizing includes:
      * Sorting the source paths in alphabetical order.
      * Remove paths that are sub-path of others in the source paths.
      * Ensure all the directory path strings are ended with the trailing '/'.
      * Convert all the path from absolute paths to relative path (relative to
        the |source_root|).
    """
    for i, path in enumerate(source_paths):
        assert os.path.isabs(path), "path %s is not an aboslute path" % path
        source_paths[i] = os.path.normpath(path)

    source_paths.sort()

    results = []

    for i, path in enumerate(source_paths):
        is_subpath_of_other = False
        for j, other in enumerate(source_paths):
            if j != i and osutils.IsSubPath(path, other):
                is_subpath_of_other = True
        if not is_subpath_of_other:
            if os.path.isdir(path) and not path.endswith("/"):
                path += "/"
            path = os.path.relpath(path, source_root)
            results.append(path)

    return results


def ExpandDirectories(files: List[Path]) -> Iterator[Path]:
    """Expand a list of files and directories to be files only.

    This function is intended to be called by tools which take a list of file
    paths (e.g., cros format and cros lint), where expansion of directories
    passed in would be useful.   If a directory is located inside a git
    checkout, any gitignore'd files will be respected (by means of using
    "git ls-files").

    Args:
        files: The list of files to process.

    Yields:
        Paths to files.
    """
    for f in files:
        if f.is_dir():
            if git.FindGitTopLevel(f):
                yield from git.LsFiles(files=[f], untracked=True)
            else:
                yield from (x for x in f.rglob("*") if x.is_file())
        else:
            yield f
