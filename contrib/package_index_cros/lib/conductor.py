# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to run the whole package-indexing process."""

import logging
import os
from typing import List, Optional

from chromite.contrib.package_index_cros.lib import build_dir
from chromite.contrib.package_index_cros.lib import cdb
from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import gn_targets
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_sleuth
from chromite.contrib.package_index_cros.lib import setup


class Conductor:
    """Helper class to orchestrate the whole process."""

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data
        self.cros_sdk = cros_sdk.CrosSdk(self.setup)
        self.packages: Optional[List[package.Package]] = None

    def prepare(
        self, package_names: List[str], *, ignore_unsupported: bool = False
    ) -> None:
        """Find relevant packages, and build them if necessary.

        Args:
            package_names: If non-empty, then fetch these packages and their
                dependencies. Otherwise, fetch all available packages.
            ignore_unsupported: If True, don't process any packages marked as
                unsupported, nor their dependencies.
        """

        assert os.path.isdir(
            self.setup.board_dir
        ), f"Board is not set up: {self.setup.board}"

        if ignore_unsupported:
            unsupported_packages = constants.TEMPORARY_UNSUPPORTED_PACKAGES
            if self.setup.with_build:
                unsupported_packages.update(
                    constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_BUILD
                )
            if self.setup.with_tests:
                unsupported_packages.update(
                    constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_TESTS
                )
            supported_packages = [
                pn for pn in package_names if not pn in unsupported_packages
            ]

            logging.warning(
                "Unsupported input packages: %s",
                (set(package_names).difference(supported_packages)),
            )
        else:
            supported_packages = package_names

        sleuth = package_sleuth.PackageSleuth(self.setup)
        packages_list, _ = sleuth.list_packages(
            packages_names=supported_packages
        )

        assert packages_list, "No packages to work with"
        assert len(packages_list) == len(
            set(p.full_name for p in packages_list)
        ), "Duplicates among packages"

        logging.info(
            "The following packages are going forward: %s",
            "\n".join([str(p) for p in packages_list]),
        )

        # Sort packages so that dependencies go first.
        self.packages = _get_sorted_packages(packages_list)

        if self.setup.with_build:
            package_names = [p.full_name for p in self.packages]
            self.cros_sdk.build_packages(package_names)

    def do_magic(
        self,
        *,
        cdb_output_file: Optional[str] = None,
        targets_output_file: Optional[str] = None,
        build_output_dir: Optional[str] = None,
        fail_fast: bool = False,
    ):
        """Call generators one by one.

        |prepare| should be called prior to this method.
        """
        assert self.packages is not None
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

        build_dir_conflicts = {}
        if build_output_dir:
            build_dir_conflicts = build_dir.BuildDirGenerator(
                self.setup
            ).generate(self.packages, build_output_dir)
            logging.info("Generated build dir: %s", build_output_dir)

        if cdb_output_file:
            cdb.CdbGenerator(
                self.setup,
                result_build_dir=build_output_dir,
                file_conflicts=build_dir_conflicts,
                fail_fast=fail_fast,
            ).generate(self.packages, cdb_output_file)
            logging.info("Generated cdb file: %s", cdb_output_file)

        if targets_output_file:
            gn_targets.GnTargetsGenerator(
                self.setup,
                result_build_dir=build_output_dir,
                file_conflicts=build_dir_conflicts,
                fail_fast=fail_fast,
            ).generate(self.packages, targets_output_file)
            logging.info("Generated targets file: %s", targets_output_file)

        logging.info("Done")


def _get_sorted_packages(
    packages_list: List[package.Package],
) -> List[package.Package]:
    """Return the given packages, sorted according to their dependencies.

    More independent packages go first.
    """
    result_packages = []
    packages_dict = {p.full_name: p for p in packages_list}

    in_degrees = {p.full_name: 0 for p in packages_list}
    for p in packages_list:
        for dep in p.dependencies:
            in_degrees[dep.name] = in_degrees[dep.name] + 1

    queue = [p_name for p_name in in_degrees if in_degrees[p_name] == 0]
    while queue:
        p_name = queue.pop(0)
        result_packages.append(packages_dict[p_name])
        for dep in packages_dict[p_name].dependencies:
            in_degrees[dep.name] = in_degrees[dep.name] - 1
            if in_degrees[dep.name] == 0:
                queue.append(dep.name)
        assert len(result_packages) <= len(
            packages_list
        ), "Too many sorted packages, probably due to circular dependencies"

    assert len(result_packages) == len(packages_list), "Missing some packages"

    result_packages.reverse()
    return result_packages
