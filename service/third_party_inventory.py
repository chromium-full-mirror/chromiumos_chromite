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

import logging
import multiprocessing.dummy

from chromite.third_party.google.protobuf import json_format

from chromite.api.gen.chromiumos.build.api import third_party_inventory_pb2
from chromite.lib import build_target_lib
from chromite.lib import chromeos_version
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import portage_util


def _collect_in_sysroot(
    sysroot: str,
) -> list[third_party_inventory_pb2.PackageMetadata]:
    """Collects PackageMetadata from a board's `sysroot`.

    This function assumes packages are already installed by emerge commands.
    """
    portage_db = portage_util.PortageDB(sysroot)
    installed_pkgs = sorted(
        portage_db.InstalledPackages(),
        key=lambda pkg: f"{pkg.category}/{pkg.pf}",
    )

    def collect_package(
        pkg: portage_util.InstalledPackage,
    ) -> third_party_inventory_pb2.PackageMetadata:
        """Collects `cpf` into a partially filled PackageMetadata."""
        out = third_party_inventory_pb2.PackageMetadata()

        # Populate package info.
        pkg_info = pkg.package_info
        out.category = pkg_info.category
        out.name = pkg_info.package
        out.version = pkg_info.version
        out.revision = pkg_info.revision

        # Portage VDB entries.
        out.homepages.extend((pkg.homepage or "").split())
        out.description = pkg.description or ""
        out.portage_repository = pkg.repository
        out.installed_size = int(pkg.size)

        # TODO: b/408329681 - Collect and resolve SRC_URI.
        # TODO: b/408329681 - Collect CROS_WORKON_* vars.
        # TODO: b/408329681 - Collect upstream, remotes and cpes.
        # TODO: b/408329681 - Collect from Portage metadata.xml.
        # TODO: b/408329681 - Collect from METADATA files.
        # TODO: b/408329681 - Deduplicate entries in repeated fields.

        logging.info("Collected %s", pkg_info.cpf)
        return out

    # Collect every package concurrently to speed up filesystem access.
    with multiprocessing.dummy.Pool() as pool:
        return pool.map(collect_package, installed_pkgs)


def _to_proto_json(pkg: third_party_inventory_pb2.PackageMetadata) -> str:
    """Convert collected `pkg` into a single-line ProtoJSON."""
    return json_format.MessageToJson(
        pkg,
        indent=None,
        including_default_value_fields=True,
        preserving_proto_field_name=True,
        sort_keys=True,
    )


def collect_inventory(board: str) -> list[str]:
    """Collect third-party software inventory of a `board`.

    This function collects third-party software inventory of a given board
    from its default build sysroot path.

    This function returns a list of single-line ProtoJSON strings, where each
    string is a `third_party_inventory_pb2.PackageMetadata`.
    """
    cros_build_lib.AssertInsideChroot()

    sysroot = build_target_lib.get_default_sysroot_path(board)

    pkgs = _collect_in_sysroot(sysroot)
    logging.info("Collected %d packages.", len(pkgs))

    # Fill in board and OS version based on the checked-out source code.
    os_ver = chromeos_version.VersionInfo.from_repo(constants.SOURCE_ROOT)
    os_ver_proto = third_party_inventory_pb2.OsVersion(
        milestone=int(os_ver.chrome_branch),
        build=int(os_ver.build_number),
        branch=int(os_ver.branch_build_number),
        patch=int(os_ver.patch_number),
    )

    for pkg in pkgs:
        pkg.board = board
        pkg.os_ver.CopyFrom(os_ver_proto)

    return [_to_proto_json(x) for x in pkgs]
