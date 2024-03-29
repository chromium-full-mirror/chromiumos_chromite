# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to run the whole package-indexing process."""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from chromite.contrib.package_index_cros.lib import build_dir
from chromite.contrib.package_index_cros.lib import cdb
from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_sleuth
from chromite.contrib.package_index_cros.lib import setup


class NoSupportedPackagesException(ValueError):
    """Raised when there are no supported packages to work on."""


class DuplicatePackagesException(ValueError):
    """Raise when we are trying to work on duplicate packages."""


class Conductor:
    """Helper class to orchestrate the whole process."""

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data
        self.cros_sdk = cros_sdk.CrosSdk(self.setup)
        self.packages: Optional[List[package.Package]] = None

    def prepare(self, package_names: List[str]) -> None:
        """Find relevant packages.

        Args:
            package_names: If non-empty, then fetch these packages and their
                dependencies. Otherwise, fetch all available packages.
        """
        if not os.path.isdir(self.setup.board_dir):
            raise FileNotFoundError(f"Board is not set up: {self.setup.board}")

        sleuth = package_sleuth.PackageSleuth(self.setup)
        packages_list = sleuth.list_packages(
            packages_names=package_names
        ).supported

        if not packages_list:
            raise NoSupportedPackagesException("No packages to work with.")
        if len(packages_list) != len(set(p.full_name for p in packages_list)):
            raise DuplicatePackagesException(
                f"Duplicates among packages: {packages_list}"
            )

        logging.info(
            "The following packages are going forward: %s",
            "\n".join([str(p) for p in packages_list]),
        )

        # Sort packages so that dependencies go first.
        self.packages = _get_sorted_packages(packages_list)

    def do_magic(
        self,
        *,
        cdb_output_file: Optional[str] = None,
        build_output_dir: Optional[str] = None,
        fail_fast: bool = False,
    ):
        """Call generators one by one.

        |prepare| should be called prior to this method.
        """
        if not self.packages:
            raise ValueError("No packages to work on.")
        bad_packages: List[package.Package] = []
        for p in self.packages:
            try:
                p.initialize()
            except Exception as e:
                logging.warning("Skipped with initialization failure: %s", e)
                bad_packages.append(p)
                if fail_fast:
                    raise e

        self.packages = [p for p in self.packages if p not in bad_packages]

        build_dir_conflicts: Dict[str, str] = {}
        if build_output_dir:
            build_dir_conflicts = build_dir.BuildDirGenerator(
                self.setup
            ).generate(self.packages, Path(build_output_dir))
            logging.info("Generated build dir: %s", build_output_dir)

        if cdb_output_file:
            cdb.CdbGenerator(
                self.setup,
                result_build_dir=build_output_dir,
                file_conflicts=build_dir_conflicts,
                fail_fast=fail_fast,
            ).generate(self.packages, cdb_output_file)
            logging.info("Generated cdb file: %s", cdb_output_file)

        logging.info("Done")


def _get_sorted_packages(
    packages_list: List[package.Package],
) -> List[package.Package]:
    """Return the given packages, sorted according to their dependencies.

    More independent packages go first.
    """
    packages_dict = {p.full_name: p for p in packages_list}

    # in_degrees is a dict where each key is a package's full name, and each
    # value is the number of packages that depend on it.
    in_degrees = {p.full_name: 0 for p in packages_list}
    for p in packages_list:
        for dep in p.dependencies:
            in_degrees[dep.name] = in_degrees[dep.name] + 1

    # result_packages is the list we'll return. Ultimately it should start with
    # the most independent packages (those that have no dependencies), and end
    # with the most dependent (those that no other packages depend on). But for
    # the sake of our algorithm, we'll construct it in the reverse order, and
    # then reverse it.
    result_packages: List[package.Package] = []

    # `queue` contains the names of packages that are ready to be appended to
    # result_packages. In other words, a package's name belongs in queue if and
    # only if no packages that aren't in result_packages depend on it.
    queue: List[str] = [
        p_name for p_name in in_degrees if in_degrees[p_name] == 0
    ]

    while queue:
        p_name = queue.pop(0)
        result_packages.append(packages_dict[p_name])
        for dep in packages_dict[p_name].dependencies:
            in_degrees[dep.name] = in_degrees[dep.name] - 1
            if in_degrees[dep.name] == 0:
                queue.append(dep.name)
        if len(result_packages) > len(packages_list):
            raise ValueError(
                "Too many sorted packages. This is probably due to circular "
                "dependencies.\n"
                f"result_packages: {result_packages}\n"
                f"packages_list: {packages_list}"
            )

    if len(result_packages) != len(packages_list):
        raise ValueError(
            "Missing some packages.\n"
            f"result_packages: {result_packages}\n"
            f"packages_list: {packages_list}"
        )

    result_packages.reverse()
    return result_packages
