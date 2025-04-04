# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Third-Party Inventory Collection.

This file contains logic to identify and collect metadata about third-party
software.

The operations here are intended to run inside chroot, after the system image
has been built (i.e. after `cros build-packages` and `cros build-image`).

The operations collects information from var/db/pkg of a given board, and
looks for additional information in the portage tree.
"""

import dataclasses
import logging
import multiprocessing.dummy

from chromite.lib import build_target_lib
from chromite.lib import cros_build_lib
from chromite.lib import portage_util


# TODO: b/408329681 - Make this a protobuf message.
@dataclasses.dataclass
class PackageMetadata:
    """Dataclass to store metadata about a package."""

    category: str = ""
    name: str = ""
    version: str = ""
    revision: int = ""


def _collect_in_sysroot(sysroot: str) -> list[PackageMetadata]:
    """Collects PackageMetadata from var/db/pkg in `sysroot`."""
    cros_build_lib.AssertInsideChroot()

    portage_db = portage_util.PortageDB(sysroot)

    # Collect package list.
    installed_pkgs = sorted(
        portage_db.InstalledPackages(),
        key=lambda pkg: f"{pkg.category}/{pkg.pf}",
    )

    def collect_package(pkg: portage_util.InstalledPackage) -> PackageMetadata:
        """Collects `cpf` into a partially filled PackageMetadata."""
        out = PackageMetadata()

        # Populate package info.
        pkg_info = pkg.package_info
        out.category = pkg_info.category
        out.name = pkg_info.package
        out.version = pkg_info.version
        out.revision = pkg_info.revision

        # TODO: b/408329681 - Collect "simple" metadata like description,
        # and homepage from vdb.
        # TODO: b/408329681 - Collect upstream, remotes and cpes.
        # TODO: b/408329681 - Collect from Portage metadata.xml.
        # TODO: b/408329681 - Collect from METADATA files.
        # TODO: b/408329681 - Deduplicate entries in repeated fields.

        logging.info("Collected %s", pkg_info.cpf)
        return out

    # Collect every package concurrently to speed up filesystem access.
    with multiprocessing.dummy.Pool() as pool:
        return pool.map(collect_package, installed_pkgs)


def collect_inventory(board: str) -> list[PackageMetadata]:
    """Collects PackageMetadata from a `board` default sysroot.

    This function assumes packages are already installed by emerge commands.
    """
    cros_build_lib.AssertInsideChroot()

    sysroot = build_target_lib.get_default_sysroot_path(board)

    # TODO: b/408329681 - Fill in board and OS version before returning the
    # metadata.

    pkgs = _collect_in_sysroot(sysroot)
    logging.info("Collected %d packages.", len(pkgs))

    return pkgs
