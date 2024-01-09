# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import os
from enum import IntEnum
from typing import List, NamedTuple, Tuple

from chromite.lib import osutils
from chromite.lib import portage_util

import lib.constants as constants
from .logger import g_logger
from .setup import Setup


class PackageSupport(IntEnum):

  SUPPORTED = 0
  # Package does not have local sources and is being downloaded.
  NO_LOCAL_SOURCE = 2
  # Package is not built with gn.
  NO_GN_BUILD = 3
  # There are some temporary issues with package that should be resolved.
  TEMP_NO_SUPPORT = 4


class PackagePathException(Exception):
  """Exception indicating some troubles while looking for packages dirs."""

  def __init__(self,
               package,
               message: str,
               first_dir: str = None,
               second_dir: str = None):
    if not first_dir:
      super(PackagePathException,
            self).__init__(f"{package.full_name}: {message}")
    elif not second_dir:
      super(PackagePathException,
            self).__init__(f"{package.full_name}: {message}: '{first_dir}'")
    else:
      super(PackagePathException, self).__init__(
          f"{package.full_name}: {message}: {first_dir} vs {second_dir}")


class PackageDependency(NamedTuple):
  name: str
  types: List[str]


def _CheckEbuildVar(ebuild_file: str,
                    var: str,
                    temp_src_basedir: str = '') -> str:
  """Returns a variable's value in ebuild file."""

  env = {'CROS_WORKON_ALWAYS_LIVE': '', 'S': temp_src_basedir}
  settings = osutils.SourceEnvironment(ebuild_file, (var,),
                                       env=env,
                                       multiline=True)
  if var in settings:
    return settings[var]

  return None


def IsPackageSupported(ebuild: portage_util.EBuild,
                       setup: Setup) -> PackageSupport:
  """
  Performs checks that the package can be processed:
    * Package has local sources.
    * Package is built with gn.

  Returns corresponding PackageSupport enum value.
  """

  ebuild_file = ebuild._unstable_ebuild_path
  ebuild_source_info = ebuild.GetSourceInfo(setup.src_dir, setup.manifest)

  def HasLocalSource():
    # Project is CROS_WORKON_PROJECT in ebuild file.
    # Srcdir is CROS_WORKON_LOCALNAME in ebuild file.
    # If package does not have project and srcdir - it's downloaded.
    # If package has project or srcdir being empty-project - it's downloaded.
    if not ebuild_source_info.srcdirs or not ebuild_source_info.projects:
      return False
    if ebuild_source_info.projects and len(
        ebuild_source_info.projects
    ) == 1 and ebuild_source_info.projects[0].endswith('empty-project'):
      return False
    if ebuild_source_info.srcdirs and len(
        ebuild_source_info.srcdirs
    ) == 1 and ebuild_source_info.srcdirs[0].endswith('empty-project'):
      return False

    # If package has platform2 subdir and it does not exist and there's no other
    #  src dir but platform2 - it's downloaded.
    # Downloadable examples:
    # * chromeos-base/intel-nnha: platform2 with non-existing PLATFORM_SUBDIR.
    # * chromeos-base/quipper: platform2 with non-existing PLATFORM_SUBDIR.
    # * dev-libs/marisa-aosp: platform2 with non-existing PLATFORM_SUBDIR.
    # With local source:
    # * dev-libs/libtextclassifier: not platform2 with non-existing
    #   PLATFORM_SUBDIR.
    platform_subdir = _CheckEbuildVar(ebuild_file, 'PLATFORM_SUBDIR')
    if platform_subdir and not os.path.isdir(
        os.path.join(setup.platform2_dir, platform_subdir)):
      if not any((os.path.isdir(srcdir)
                  for srcdir in ebuild_source_info.srcdirs
                  if srcdir != setup.platform2_dir)):
        return False

    return True

  def IsBuiltWithGn():
    # Subtrees is CROS_WORKON_SUBTREE in ebuild file.
    # If none of subtrees is .gn - package is not built with gn.
    if all((not st.endswith('.gn') for st in ebuild_source_info.subtrees)):
      return False

    if _CheckEbuildVar(ebuild_file, 'CROS_RUST_SUBDIR'):
      return False

    # TODO: Returns true for config packages (should be false):
    # * chromeos-base/arc-common-scripts
    # * chromeos-base/arc-myfiles
    # * chromeos-base/arc-removable-media
    # TODO: Returns true for makefile packages (should be false):
    # * chromeos-base/avtest_label_detect

    return True

  if not HasLocalSource():
    return PackageSupport.NO_LOCAL_SOURCE

  if not IsBuiltWithGn():
    return PackageSupport.NO_GN_BUILD

  if ebuild.package in constants.TEMPORARY_UNSUPPORTED_PACKAGES:
    return PackageSupport.TEMP_NO_SUPPORT

  if (setup.with_build and
      ebuild.package in constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_BUILD):
    return PackageSupport.TEMP_NO_SUPPORT

  if (setup.with_build and setup.with_tests and
      ebuild.package in constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_TESTS):
    return PackageSupport.TEMP_NO_SUPPORT

  if ebuild.package in setup.skip_packages:
    return PackageSupport.TEMP_NO_SUPPORT

  return PackageSupport.SUPPORTED


class Package:
  """"
  Represents portage package. Gives an access to paths associated with the
  package. Fields:
    * setup.
    * full_name: package's full name, e.g. chromeos-base/cryptohome.
    * package_info: various package info extracted from ebuild, like category
      and version, see |PackageInfo|.
    * is_highly_volatile: bool indicating if package's sources are patched on
      build. If true, one should not expect exact match between temp and
      actual sources.
    * temp_dir: base path to a dir with all temporary sources.
    * build_dir: path to a dir with build. Is expected to contain args.gn.
    * src_dir_matches: list of tuples (temp, actual). Represents a possible
      match between temporary and actual source dirs/files. The list is sorted
      by depth: match is better when closer to desired path.
    * additional_include_paths: list of actual paths to be added to include
      path arguments.
    * dependencies: list of package names on which this package depends on.

  Raises:
    * UnsupportedPackageException upon construction if package is not supported.

  NOTE: all dir fields are expected to exist when Initialize is called.
  NOTE: only packages built with gn are supported.
  """

  class UnsupportedPackageException(Exception):
    """Exception indicating attempt to create unsupported package."""

    def __init__(self, package_name, reason: PackageSupport):
      self.package_name = package_name
      self.reason = reason
      super(Package.UnsupportedPackageException,
            self).__init__(f"{package_name}: Not supported due to: {reason}")

  class DirsException(PackagePathException):
    """Exception indicating some troubles while looking for packages dirs."""

  class TempActualDichotomy(NamedTuple):
    temp: str
    actual: str

  class PackageInfo:

    def __init__(self, ebuild: portage_util.EBuild):
      self.ebuild_file = ebuild._unstable_ebuild_path
      self.category = ebuild.category
      self.name = ebuild.pkgname
      self.version = ebuild.version_no_rev
      # Extract revision from |version| formatted like
      # "|version_no_rev|-|revision|"
      self.revision = ebuild.version[len(ebuild.version_no_rev) + 1:]

  g_highly_volatile_packages = [
      # Libchrome has a number of patches applied on top of checkout.
      'chromeos-base/libchrome'
  ]

  # Packages categories which sources are in src dir and not in src/third_party.
  g_src_categories = ["chromeos-base", "brillo-base"]

  def __init__(self,
               setup: Setup,
               ebuild: portage_util.EBuild,
               deps: List[PackageDependency] = []):

    is_supported = IsPackageSupported(ebuild, setup)
    if is_supported != PackageSupport.SUPPORTED:
      raise Package.UnsupportedPackageException(ebuild.package, is_supported)

    self.setup = setup
    self.full_name = ebuild.package
    self.package_info = Package.PackageInfo(ebuild)

    self.is_highly_volatile = os.path.isdir(
        os.path.join(
            os.path.dirname(self.package_info.ebuild_file),
            'files')) or self.full_name in Package.g_highly_volatile_packages
    self.dependencies = deps if deps else []

  def __eq__(self, other) -> bool:
    if isinstance(other, str):
      return self.full_name == other
    elif isinstance(other, Package):
      return self.full_name == other.full_name

    raise NotImplementedError('Can compare only with Package or string')

  def __str__(self) -> str:
    return self.full_name

  @property
  def is_built_from_actual_sources(self) -> bool:
    assert self.temp_dir
    out_of_tree_build = (_CheckEbuildVar(self.package_info.ebuild_file,
                                         'CROS_WORKON_OUTOFTREE_BUILD') or
                         '0') == '1'
    # Instead of calling 'cros-workon list', just check if workon version is
    # present.
    is_not_stable = '9999' in self.temp_dir
    return out_of_tree_build and is_not_stable

  def Initialize(self) -> None:
    """
    Find directories associated with the package and check they exist.

    This method will fail not-yet-built package, so make sure you've built
    the package with FEATURES=noclean flag.

    Raises:
      * DirsException if build, source or temp source dir(s) is not found.
    """
    g_logger.debug('%s: Initializing', self.full_name)

    self.temp_dir = self._GetTempDir()
    g_logger.debug('%s: Temp dir: %s', self.full_name, self.temp_dir)

    self.build_dir = self._GetBuildDir()
    g_logger.debug('%s: Build dir: %s', self.full_name, self.build_dir)

    self.src_dir_matches = self._GetSourceDirsToTempSourceDirsMap()

    self.additional_include_paths = self.GetAdditionalIncludePaths()
    if self.additional_include_paths:
      for path in self.additional_include_paths:
        if not os.path.isdir(path):
          raise Package.DirsException(self,
                                      'Additional include path does not exist',
                                      path)

  def GetAdditionalIncludePaths(self) -> List[str]:
    """Returns a list of actual paths to be added as include path arguments."""

    # Special case for chromeos-base/update_engine which pretends to be in
    # platform2 and uses platform2 as include path. While the actual include
    # path is {src_dir}/aosp/system with update_engine inside.
    if self.full_name == 'chromeos-base/update_engine':
      return [os.path.join(self.setup.src_dir, 'aosp', 'system')]

    return None

  def _GetOrderedVersionSuffixes(self) -> List[str]:
    """
    Returns a list of versions of the current package ordered from highest to
    lowest.
    """

    return [
        '9999', f"{self.package_info.version}-{self.package_info.revision}",
        self.package_info.version
    ]

  def _GetTempDir(self) -> str:
    """
    Returns path to the base temp dir (${WORKDIR} in portage).

    See WORKDIR entry on
    https://devmanual.gentoo.org/ebuild-writing/variables/index.html.

    Chooses the dir with the highest ebuild version.
    """

    base_dir = os.path.join(self.setup.board_dir, 'tmp', 'portage')
    not_in_dirs = []

    for version_suffix in self._GetOrderedVersionSuffixes():
      temp_dir = os.path.join(base_dir, self.package_info.category,
                              f"{self.package_info.name}-{version_suffix}",
                              'work')

      if os.path.isdir(temp_dir):
        return temp_dir
      else:
        not_in_dirs.append(temp_dir)

    # Failed all tries, report and raise.
    dirs_tried = ', '.join([str(os.path.join(x)) for x in not_in_dirs])

    raise Package.DirsException(self, 'Cannot find temp dir in', dirs_tried)

  def _GetBuildDir(self) -> str:
    """
    Returns path to dir with build metadata (were args.gn lives).

    Raises:
      * DirsException if build dir is not found.
      * DirsException if 'args.gn' file not found in supposed build dir.
    """
    build_dirs = [
        os.path.join(self.setup.board_dir, 'var', 'cache', 'portage',
                     self.package_info.category, self.package_info.name, 'out',
                     'Default'),
        os.path.join(self.temp_dir, 'build', 'out', 'Default')
    ]

    for dir in build_dirs:
      if not os.path.isdir(dir):
        continue

      if not os.path.isfile(os.path.join(dir, 'args.gn')):
        continue

      return dir

    raise Package.DirsException(self, 'Cannot find build dir')

  def _GetTempSourceBaseDir(self) -> str:
    """
    Returns path to the base source dir inside temp dir (${S} in portage).

    See S on https://devmanual.gentoo.org/ebuild-writing/variables/index.html.

    The base source dir contains copied source files.
    """

    for version in self._GetOrderedVersionSuffixes():
      dir = os.path.join(self.temp_dir, f"{self.package_info.name}-{version}")

      if os.path.isdir(dir):
        return dir

    return None

  def _GetEbuildSourceDirs(self) -> List[str]:
    """
    Returns actual source dirs.

    Based on:
    https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=383
    """

    # Base dir is either src or src/third_party depending on package's category.
    source_base_dir = self.setup.src_dir
    if not self.package_info.category in Package.g_src_categories:
      source_base_dir = os.path.join(source_base_dir, 'third_party')

    # CROS_WORKON_SRCPATH and CROS_WORKON_LOCALNAME declare paths relative
    # to base source dir.
    source_dirs = _CheckEbuildVar(self.package_info.ebuild_file,
                                  'CROS_WORKON_SRCPATH', '')
    if not source_dirs:
      source_dirs = _CheckEbuildVar(self.package_info.ebuild_file,
                                    'CROS_WORKON_LOCALNAME', '')

    if not source_dirs:
      raise Package.DirsException(
          self, "Cannot extract source dir(s) from ebuild file")

    # |source_dirs| is a comma separated list of directories relative to the
    # source base dir.
    return [
        os.path.join(source_base_dir, dir) for dir in source_dirs.split(',')
    ]

  def _GetEbuildDestDirs(self, temp_source_basedir: str) -> List[str]:
    """
    Returns dest source dirs.

    Dest dirs contain temp copy of source dirs.

    Based on _cros-workon_emit_src_to_buid_dest_map():
    https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=474
    """

    # CROS_WORKON_DESTDIR declares abs paths in |temp_source_basedir|.
    dest_dirs = _CheckEbuildVar(self.package_info.ebuild_file,
                                'CROS_WORKON_DESTDIR', temp_source_basedir)

    if not dest_dirs:
      # Defaults to ${S}:
      # https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=583
      return [temp_source_basedir]
    else:
      # |dest_dirs| is a comma separated list of directories with absolute path.
      return dest_dirs.split(',')

  def _GetSourceDirsToTempSourceDirsMap(self) -> List[TempActualDichotomy]:
    """
    Returns list of matches between actual src dirs and temp src dirs.

    See cros-workon_src_unpack() on
    https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=564

    Raises:
      * DirsException if cannot find temp source dir for not workon not
        out-of-tree package.
      * DirsException if cannot actual source dirs.
      * DirsException if cannot find temp source dirs.
      * DirsException if cannot map actual source dirs on temp source dirs.
    """
    temp_source_basedir = self._GetTempSourceBaseDir()

    if not temp_source_basedir:
      if not self.is_built_from_actual_sources:
        raise Package.DirsException(
            self,
            "Only workon and out-of-tree packages may not have temp source copy"
        )
      # Out-of-tree packages are not copied but are built from the actual
      # sources.
      source_dirs = self._GetEbuildSourceDirs()
      return [
          Package.TempActualDichotomy(temp=source_dir, actual=source_dir)
          for source_dir in source_dirs
      ]

    # cros-workon.eclass maps source dirs to dest dirs extracted from ebuild in
    # order as they are declared.
    source_dirs = self._GetEbuildSourceDirs()
    dest_dirs = self._GetEbuildDestDirs(temp_source_basedir)

    if len(source_dirs) != len(dest_dirs):
      raise Package.DirsException(self,
                                  'Different number of src and temp src dirs')

    matches = [
        Package.TempActualDichotomy(temp=dest, actual=source)
        for source, dest in zip(source_dirs, dest_dirs)
    ]

    for match in matches:
      if not os.path.isdir(match.actual):
        raise Package.DirsException(self, 'Cannot find src dir', match.actual)

      if not os.path.isdir(match.temp):
        raise Package.DirsException(self, 'Cannot find temp src dir',
                                    match.temp)
      g_logger.debug('%s: Match between temp and actual: %s and %s',
                     self.full_name, match.temp, match.actual)

    # Sort by actual source dir length so the deepest and most accurate match
    # appears first.
    matches.sort(key=lambda match: len(match.actual), reverse=True)

    return matches
