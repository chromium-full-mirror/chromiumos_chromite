# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List
import os

import lib.constants as constants
from .build_dir import BuildDirGenerator
from .cdb import CdbGenerator
from .cros_sdk import CrosSdk
from .gn_targets import GnTargetsGenerator
from .logger import g_logger
from .package import Package
from .package_sleuth import PackageSleuth
from .setup import Setup


class Conductor:
  """Orchestrates whole process."""

  def __init__(self, setup: Setup):
    self.setup = setup
    self.cros_sdk = CrosSdk(self.setup)

  def Prepare(self,
              package_names: List[str],
              *,
              ignore_unsupported: bool = False):
    """
    Does:
      * List packages:
        * If |package_names| - fetches given packages and their dependencies.
        * If not |package_names| - fetches all available packages.
      * If |ignore_unsupported|:
        * Ignore any packages marked as unsupported from processing as
          well as their dependencies.
    """

    assert os.path.isdir(
        self.setup.board_dir), f"Board is not set up: {self.setup.board}"

    package_sleuth = PackageSleuth(self.setup)

    if ignore_unsupported:
      unsupported_packages = constants.TEMPORARY_UNSUPPORTED_PACKAGES
      if self.setup.with_build:
        unsupported_packages.update(
            constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_BUILD)
      if self.setup.with_tests:
        unsupported_packages.update(
            constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_TESTS)
      supported_packages = [
          pn for pn in package_names if not pn in unsupported_packages
      ]

      g_logger.warn("Unsupported input packages: %s",
                    (set(package_names).difference(supported_packages)))
    else:
      supported_packages = package_names

    packages_list, ignored_packages_list = package_sleuth.ListPackages(
        packages_names=supported_packages)

    assert packages_list, 'No packages to work with'
    assert len(packages_list) == len(set([p.full_name for p in packages_list
                                         ])), 'Duplicates among packages'

    g_logger.info('The following packages are going forward: %s',
                  '\n'.join([str(p) for p in packages_list]))

    # Sort packages so that dependencies go first.
    self.packages = Conductor._GetSortedPackages(packages_list)

    if self.setup.with_build:
      package_names = [p.full_name for p in self.packages]
      self.cros_sdk.BuildPackages(package_names)

  def DoMagic(self,
              *,
              cdb_output_file: str = None,
              targets_output_file: str = None,
              build_output_dir: str = None,
              keep_going: bool = False):
    """
    Calls generators one by one. |Prepare| should be called prior this method.
    """
    bad_packages: List[Package] = []
    for p in self.packages:
      try:
        p.Initialize()
      except Exception as e:
        bad_packages.append(p)
        if keep_going:
          g_logger.warning('Skipped with initialization failure: %s', e)
          continue
        raise e
    self.packages = [p for p in self.packages if p not in bad_packages]

    build_dir_conflicts = {}
    if build_output_dir:
      build_dir_conflicts = BuildDirGenerator(self.setup).Generate(
          self.packages, build_output_dir)
      g_logger.info('Generated build dir: %s', build_output_dir)

    if cdb_output_file:
      CdbGenerator(
          self.setup,
          result_build_dir=build_output_dir,
          file_conflicts=build_dir_conflicts,
          keep_going=keep_going).Generate(self.packages, cdb_output_file)
      g_logger.info('Generated cdb file: %s', cdb_output_file)

    if targets_output_file:
      GnTargetsGenerator(
          self.setup,
          result_build_dir=build_output_dir,
          file_conflicts=build_dir_conflicts,
          keep_going=keep_going).Generate(self.packages, targets_output_file)
      g_logger.info('Generated targets file: %s', targets_output_file)

    g_logger.info('Done')

  @staticmethod
  def _GetSortedPackages(packages_list: List[Package]) -> List[Package]:
    """
    Returns topologically sorted packages.

    Packages graph is according to package dependencies: more independent
    packages go first.
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
      ), 'Too many sorted packages. Probably because of circular dependencies'

    assert len(result_packages) == len(packages_list), "Missing some packages"

    result_packages.reverse()
    return result_packages
