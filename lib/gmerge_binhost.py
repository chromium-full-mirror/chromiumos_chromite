# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Installs packages from a sysroot into a gmerge-specific binhost"""

import logging
import os
from pathlib import Path
import shutil
import subprocess
from typing import List

import portage  # pylint: disable=import-error

from chromite.lib import compression_lib
from chromite.lib import cros_build_lib
from chromite.lib import osutils


# Relative path to the wrapper directory inside the sysroot.
_SYSROOT_BUILD_BIN = "build/bin"


def _filter_install_mask_from_package(in_path: str, out_path: str) -> None:
    """Filter files matching DEFAULT_INSTALL_MASK out of a tarball.

    Args:
        in_path: Unfiltered tarball.
        out_path: Location to write filtered tarball.
    """

    # Grab metadata about package in xpak format.
    my_xpak = portage.xpak.xpak_mem(portage.xpak.tbz2(in_path).get_data())

    # Build list of files to exclude. The tar command uses a slightly
    # different exclude format than gmerge, so it needs to be adjusted
    # appropriately.
    masks = os.environ.get("DEFAULT_INSTALL_MASK", "").split()
    # Look for complete paths matching the specified pattern.  Leading slashes
    # are removed so that the paths are relative. Trailing slashes are removed
    # so that we delete the directory itself when the '/usr/include/' path is
    # given.
    masks = [f"--exclude=./{x.strip('/')}" for x in masks]
    excludes = ["--anchored"] + masks

    gmerge_dir = os.path.dirname(out_path)
    os.makedirs(gmerge_dir, mode=0o755, exist_ok=True)

    with osutils.TempDir(sudo_rm=True) as tmpd:
        tmpd_sysroot = Path(tmpd) / "sysroot"
        osutils.SafeMakedirs(tmpd_sysroot)
        # Decompress package to memory.  The binpkg isn't a well-formed zstd
        # file due to the xpak content at the end, so we have to use zstd or
        # zstdmt (pzstd doesn't work), and we have to pipe via stdout rather
        # than extracting to the filesystem (that throws an error that's skipped
        # with -c).
        res = cros_build_lib.run(
            ["zstdmt", "-dcf", in_path], stdout=subprocess.PIPE
        )

        # Extract package to temporary directory (excluding masked files).
        # Run tar as root so we can extract paths using the correct ownership
        # and permissions.  Sometimes ebuilds use fowners when installing.  Use
        # numeric owners so we don't worry about the current name:id mapping vs
        # what was recorded for the board.
        cros_build_lib.sudo_run(
            [
                "tar",
                "-x",
                "-C",
                tmpd_sysroot,
                "--numeric-owner",
                "--preserve-permissions",
                "--wildcards",
            ]
            + excludes,
            input=res.stdout,
        )

        tmp_out_path = Path(tmpd) / Path(out_path).name
        # Create the file as ourselves so the next sudo tar step doesn't create
        # it as root which we would have to then reset.
        tmp_out_path.touch()
        # Build filtered version of package.  Use sudo so we can read all the
        # paths regardless of the ownership & permissions.
        compression_lib.create_tarball(
            tmp_out_path,
            tmpd_sysroot,
            compression=compression_lib.CompressionType.ZSTD,
            compressor=["zstdmt"],
            sudo=True,
        )

        # Copy package metadata over to new package file.
        portage.xpak.tbz2(tmp_out_path).recompose_mem(my_xpak)

        # Move it to the final location.
        try:
            shutil.move(tmp_out_path, out_path)
        except PermissionError:
            # Developers with older layouts will often have dirs owned by root.
            # Reset those perms here to recover gracefully.
            # TODO(build): Delete this Jan 2025.
            cros_build_lib.sudo_run(
                [
                    "find",
                    os.path.dirname(gmerge_dir),
                    "-uid",
                    "0",
                    "-exec",
                    "chown",
                    f"{os.getuid()}:{os.getgid()}",
                    "{}",
                    "+",
                ]
            )
            shutil.move(tmp_out_path, out_path)


def update_gmerge_binhost(sysroot: str, pkgs: List[str], deep: bool) -> bool:
    """Add packages to our gmerge-specific binhost.

    Files matching DEFAULT_INSTALL_MASK are not included in the tarball.

    Args:
        sysroot: Path to the sysroot.
        pkgs: List of packages to update.
        deep: If True, update all packages in the binhost, else only the ones
            specified in pkgs.

    Returns:
        True if any packages were updated in the gmerge binhost.
    """
    # Portage internal api expects the sysroot to ends with a '/'.
    sysroot = os.path.join(sysroot, "")
    # To handle the edge case where we invoke this against the SDK sysroot on a
    # builder where / is not writable, we'll put our output dirs under /tmp.
    # Since we believe this is only done in unit tests, we accept the
    # inconsistency with where the output is written for board sysroots.
    output_dir = os.path.join(sysroot, "tmp") if sysroot == "/" else sysroot

    pkgdir = os.path.join(output_dir, "stripped-packages")

    # Migrate old naming schema.
    # TODO(build): Delete this logic in Jan 2025 & all "gmerge-packages".
    legacy_link = os.path.join(output_dir, "gmerge-packages")
    if os.path.islink(pkgdir):
        osutils.SafeUnlink(pkgdir, sudo=True)
    if not os.path.islink(legacy_link):
        if os.path.isdir(legacy_link):
            cros_build_lib.sudo_run(["mv", legacy_link, pkgdir])
        else:
            osutils.SafeUnlink(legacy_link, sudo=True)
    osutils.SafeSymlink(os.path.basename(pkgdir), legacy_link, sudo=True)

    # Create gmerge pkgdir and give us permission to write to it.
    osutils.SafeMakedirs(pkgdir, sudo=True)
    osutils.Chown(pkgdir, user=True)

    # Load databases.
    trees = portage.create_trees(config_root=sysroot, target_root=sysroot)
    vardb = trees[sysroot]["vartree"].dbapi
    bintree = trees[sysroot]["bintree"]
    bintree.populate()
    gmerge_tree = portage.dbapi.bintree.binarytree(
        pkgdir=pkgdir, settings=bintree.settings
    )
    gmerge_tree.populate()

    # The portage API here is subtle.  Results from these lookups are a pkg_str
    # object which derive from Python strings but attach some extra metadata
    # (like package file sizes and build times).  Helpers like __cmp__ aren't
    # changed, so the set logic can works.  But if you use a pkg_str from one
    # bintree in another, it can fail to resolve, while stripping off the extra
    # metadata allows the bintree to do the resolution internally.  Hence we
    # normalize all results here to strings.
    if deep:
        # If we're in deep mode, fill in the binhost completely.
        gmerge_matches = {str(x) for x in gmerge_tree.dbapi.cpv_all()}
        bindb_matches = {str(x) for x in bintree.dbapi.cpv_all()}
        installed_matches = {str(x) for x in vardb.cpv_all()} & bindb_matches
    else:
        # Otherwise, just fill in the requested package.
        gmerge_matches = set()
        bindb_matches = set()
        installed_matches = set()
        for pkg in pkgs:
            gmerge_matches.update(
                {str(x) for x in gmerge_tree.dbapi.match(pkg)}
            )
            bindb_matches.update({str(x) for x in bintree.dbapi.match(pkg)})
            installed_matches.update(
                {str(x) for x in vardb.match(pkg)} & bindb_matches
            )

    # Remove any stale packages that exist in the local binhost but are not
    # installed anymore.
    if bindb_matches - installed_matches:
        subprocess.check_call(
            [
                cros_build_lib.GetSysrootToolPath(sysroot, "eclean"),
                "-d",
                "packages",
            ]
        )

    # Remove any stale packages that exist in the gmerge binhost but are not
    # installed anymore.
    for pkg in gmerge_matches - installed_matches:
        gmerge_path = gmerge_tree.getname(pkg)
        osutils.SafeUnlink(gmerge_path, sudo=True)

    # Copy any installed packages that have been rebuilt to the gmerge binhost.
    for pkg in installed_matches:
        (build_time,) = bintree.dbapi.aux_get(pkg, ["BUILD_TIME"])
        build_path = bintree.getname(pkg)
        gmerge_path = gmerge_tree.getname(pkg)

        # If a package exists in the gmerge binhost with the same build time,
        # don't rebuild it.
        if pkg in gmerge_matches and os.path.exists(gmerge_path):
            (old_build_time,) = gmerge_tree.dbapi.aux_get(pkg, ["BUILD_TIME"])
            if old_build_time == build_time:
                continue

        logging.info("Filtering install mask from %s", pkg)
        _filter_install_mask_from_package(build_path, gmerge_path)

    return bool(installed_matches)
