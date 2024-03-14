# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Dependency calculation functionality/utilities."""

import logging
import os
from pathlib import Path
from typing import List, Mapping, Union

from chromite.lib import constants
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import portage_util
from chromite.utils.parser import portage_md5_cache


class Error(Exception):
    """Base error class for the module."""


class NoMatchingFileForDigest(Error):
    """No ebuild or eclass file could be found with the given MD5 digest."""


def _get_eclasses_for_ebuild(ebuild_path, path_cache, overlay_dirs):
    cache_entries = portage_md5_cache.Md5Cache(
        path=portage_util.get_cache_file(Path(ebuild_path)),
        missing_ok=False,
    )

    relevant_eclass_paths = []
    for eclass in cache_entries.eclasses:
        if eclass.digest in path_cache:
            relevant_eclass_paths.append(path_cache[eclass.digest])
        else:
            try:
                eclass_path = _find_matching_eclass_file(
                    eclass.name, eclass.digest, overlay_dirs
                )
                path_cache[eclass.digest] = eclass_path
                relevant_eclass_paths.append(eclass_path)
            except NoMatchingFileForDigest:
                logging.warning(
                    (
                        "Ebuild %s has a reference to eclass %s with digest "
                        "%s but no matching file could be found."
                    ),
                    ebuild_path,
                    eclass.name,
                    eclass.digest,
                )
                # If we can't find a matching eclass file then we don't know
                # exactly which overlay the eclass file is coming from, but we
                # do know that it has to be in one of the overlay_dirs. So as a
                # fallback we will pretend the eclass could be in any of them
                # and add all the paths that it could possibly have.
                relevant_eclass_paths.extend(
                    [
                        os.path.join(overlay, "eclass", eclass.name) + ".eclass"
                        for overlay in overlay_dirs
                    ]
                )

    return relevant_eclass_paths


def _find_matching_eclass_file(eclass, digest, overlay_dirs):
    for overlay in overlay_dirs:
        path = os.path.join(overlay, "eclass", eclass) + ".eclass"
        if os.path.isfile(path) and digest == osutils.MD5HashFile(path):
            return path
    raise NoMatchingFileForDigest(
        "No matching eclass file found: %s %s" % (eclass, digest)
    )


def get_source_path_mapping(
    packages: List[str],
    sysroot_path: str,
    board: Union[str, None],
    include_eclass: bool = True,
    include_overlay: bool = True,
) -> Mapping[str, List[str]]:
    """Returns a map from each package to the source paths it depends on.

    A source path is considered dependency of a package if modifying files in
    that path might change the content of the resulting package.

    Notes:
        1) This method errs on the side of returning unneeded dependent paths by
            default.
            i.e: for a given package X, some of its dependency source paths may
            contain files which doesn't affect the content of X. By contrast,
            any missing dependency source paths for package X is considered a
            bug.
        2) This only outputs the direct dependency source paths for a given
            package and does not include the dependency source paths of
            dependency packages.
            e.g: if package A depends on B (DEPEND=B), then results of computing
            dependency source paths of A doesn't include dependency source paths
            of B.

    Args:
        packages: The list of packages CPV names (str)
        sysroot_path: The path to the sysroot.  If the packages are board
            agnostic, then this should be '/'.
        board: The name of the board if packages are dependency of board. If
            the packages are board agnostic, then this should be None.
        include_eclass: Whether to include eclass paths.
        include_overlay: Whether to include overlay paths.

    Returns:
        Map from each package to the source path (relative to the repo checkout
            root, i.e: ~/chromiumos/ in your cros_sdk) it depends on.
        For each source path which is a directory, the string is ended with a
            trailing '/'.
    """
    results = {}

    packages_to_ebuild_paths = portage_util.FindEbuildsForPackages(
        packages, sysroot=sysroot_path, check=True, include_masked=True
    )

    # Source paths which are the directory of ebuild files.
    for package, ebuild_path in packages_to_ebuild_paths.items():
        # Include the entire directory that contains the ebuild as the package's
        # FILESDIR probably lives there too.
        results[package] = [os.path.dirname(ebuild_path)]

    # Source paths which are cros workon source paths.
    buildroot = os.path.join(constants.SOURCE_ROOT, "src")
    manifest = git.ManifestCheckout.Cached(buildroot)
    for package, ebuild_path in packages_to_ebuild_paths.items():
        ebuild = portage_util.EBuild(ebuild_path)
        if not ebuild.is_workon or ebuild.is_manually_uprevved:
            # Can only fetch workon source paths from workon ebuilds, and
            # manually uprevved packages are pinned so changes to the source
            # repo don't matter.
            continue

        workon_subtrees = ebuild.GetSourceInfo(buildroot, manifest).subtrees
        results[package].extend(workon_subtrees)

    if include_eclass or include_overlay:
        if board:
            overlay_directories = portage_util.FindOverlays(
                overlay_type="both", board=board
            )
        else:
            # If a board is not specified we assume the package is intended for
            # the SDK, and so we use the overlays for the SDK builder.
            overlay_directories = portage_util.FindOverlays(
                overlay_type="both", board=constants.CHROOT_BUILDER_BOARD
            )

    # Package's inherited eclass paths.
    if include_eclass:
        eclass_path_cache = {}
        eclass_overlays = [
            x
            for x in overlay_directories
            if os.path.isdir(os.path.join(x, "eclass"))
        ]
        for package, ebuild_path in packages_to_ebuild_paths.items():
            eclass_paths = _get_eclasses_for_ebuild(
                ebuild_path,
                eclass_path_cache,
                eclass_overlays,
            )
            results[package].extend(eclass_paths)

    # Source paths which are the overlay directories for the given board
    # (packages are board specific).
    if include_overlay:
        filter_existing = lambda paths: [x for x in paths if os.path.exists(x)]

        # The only parts of the overlay that affect every package are the
        # current profile (which lives somewhere in the profiles/ subdir) and a
        # top-level make.conf (if it exists).
        profile_directories = filter_existing(
            os.path.join(x, "profiles") for x in overlay_directories
        )
        make_conf_paths = filter_existing(
            os.path.join(x, "make.conf") for x in overlay_directories
        )

        # These directories *might* affect a build, so we include them for now
        # to be safe.
        metadata_directories = filter_existing(
            os.path.join(x, "metadata") for x in overlay_directories
        )
        scripts_directories = filter_existing(
            os.path.join(x, "scripts") for x in overlay_directories
        )

        # TODO(b/236161656): Fix.
        # pylint: disable-next=consider-using-dict-items
        for package in results:
            results[package].extend(profile_directories)
            results[package].extend(make_conf_paths)
            results[package].extend(metadata_directories)
            results[package].extend(scripts_directories)
            # The 'crosutils' repo potentially affects the build of every
            # package.
            results[package].append(str(constants.CROSUTILS_DIR))

        # chromiumos-overlay specifies default settings for every target in
        # chromeos/config  and so can potentially affect every board.
        # TODO(b/236161656): Fix.
        # pylint: disable-next=consider-using-dict-items
        for package in results:
            # TODO(b/236161656): Fix.
            # pylint: disable-next=modified-iterating-dict
            results[package].append(
                os.path.join(
                    constants.CHROOT_SOURCE_ROOT,
                    constants.CHROMIUMOS_OVERLAY_DIR,
                    "chromeos",
                    "config",
                )
            )

    for p in results:
        # TODO(b/236161656): Fix.
        # pylint: disable-next=modified-iterating-dict
        results[p] = path_util.normalize_paths_to_source_root(results[p])

    return results
