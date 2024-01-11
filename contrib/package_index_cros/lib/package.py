# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Support and processing for Portage packages."""

import enum
import logging
import os
from typing import List, NamedTuple, Optional

from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import osutils
from chromite.lib import portage_util


class PackageSupport(enum.IntEnum):
    """Whether package_index_cros supports this package, and if not, why."""

    # Package is supported.
    SUPPORTED = 0
    # Package does not have local sources and is being downloaded.
    NO_LOCAL_SOURCE = 2
    # Package is not built with gn.
    NO_GN_BUILD = 3
    # There are some temporary issues with package that should be resolved.
    TEMP_NO_SUPPORT = 4

    def is_supported(self) -> bool:
        """Return whether this represents a supported package."""
        return self is PackageSupport.SUPPORTED

    def is_unsupported(self) -> bool:
        """Return whether this represents an unsupported package."""
        return not self.is_supported()


class PackageDependency(NamedTuple):
    """Data class representing a single package dependency.

    Attributes:
        name: The package name.
        types: A list of dependency types describing the dependency, such as
            "blocker", "buildtime", "buildtime_slot_op", "runtime",
            "runtime_slot_op", "runtime_post", "ignored", and "slot".
    """

    name: str
    types: List[str]


def _CheckEbuildVar(
    ebuild_file: str, var: str, temp_src_basedir: str = ""
) -> str:
    """Returns a variable's value in ebuild file."""

    env = {"CROS_WORKON_ALWAYS_LIVE": "", "S": temp_src_basedir}
    settings = osutils.SourceEnvironment(
        ebuild_file, (var,), env=env, multiline=True
    )
    if var in settings:
        return settings[var]

    return None


def GetPackageSupport(
    ebuild: portage_util.EBuild, setup_data: setup.Setup
) -> PackageSupport:
    """Check whether the package can be processed.

    Performs checks that the package can be processed:
    *   Package has local sources.
    *   Package is built with gn.

    Returns:
        Corresponding PackageSupport enum value.
    """
    # pylint: disable=protected-access
    ebuild_file = ebuild._unstable_ebuild_path
    ebuild_source_info = ebuild.GetSourceInfo(
        setup_data.src_dir,
        setup_data.manifest,
    )

    # We don't want to disqualify virtual packages from the dep graph expansion.
    def IsVirtual():
        if ebuild.category == "virtual":
            return True

    def HasLocalSource():
        # Project is CROS_WORKON_PROJECT in ebuild file.
        # Srcdir is CROS_WORKON_LOCALNAME in ebuild file.
        # If package does not have project and srcdir, it's downloaded.
        # If package has project or srcdir being empty-project, it's downloaded.
        if not ebuild_source_info.srcdirs or not ebuild_source_info.projects:
            return False
        if (
            ebuild_source_info.projects
            and len(ebuild_source_info.projects) == 1
            and ebuild_source_info.projects[0].endswith("empty-project")
        ):
            return False
        if (
            ebuild_source_info.srcdirs
            and len(ebuild_source_info.srcdirs) == 1
            and ebuild_source_info.srcdirs[0].endswith("empty-project")
        ):
            return False

        # If package has platform2 subdir and it does not exist and there's no
        # other src dir but platform2, it's downloaded.
        #
        # Downloadable examples:
        # *   chromeos-base/intel-nnha: platform2 with non-existing
        #     PLATFORM_SUBDIR.
        # *   chromeos-base/quipper: platform2 with non-existing
        #     PLATFORM_SUBDIR.
        # *   dev-libs/marisa-aosp: platform2 with non-existing PLATFORM_SUBDIR.
        #
        # With local source:
        # *   dev-libs/libtextclassifier: not platform2 with non-existing
        #     PLATFORM_SUBDIR.
        platform_subdir = _CheckEbuildVar(ebuild_file, "PLATFORM_SUBDIR")
        if platform_subdir and not os.path.isdir(
            os.path.join(setup_data.platform2_dir, platform_subdir)
        ):
            if not any(
                (
                    os.path.isdir(srcdir)
                    for srcdir in ebuild_source_info.srcdirs
                    if srcdir != setup_data.platform2_dir
                )
            ):
                return False

        return True

    def IsBuiltWithGn():
        # Subtrees is CROS_WORKON_SUBTREE in ebuild file.
        # If none of subtrees is .gn - package is not built with gn.
        if all((not st.endswith(".gn") for st in ebuild_source_info.subtrees)):
            return False

        if _CheckEbuildVar(ebuild_file, "CROS_RUST_SUBDIR"):
            return False

        # TODO: Returns true for config packages (should be false):
        # * chromeos-base/arc-common-scripts
        # * chromeos-base/arc-myfiles
        # * chromeos-base/arc-removable-media
        # TODO: Returns true for makefile packages (should be false):
        # * chromeos-base/avtest_label_detect

        return True

    if IsVirtual():
        return PackageSupport.SUPPORTED

    if not HasLocalSource():
        return PackageSupport.NO_LOCAL_SOURCE

    if not IsBuiltWithGn():
        return PackageSupport.NO_GN_BUILD

    if ebuild.package in constants.TEMPORARY_UNSUPPORTED_PACKAGES:
        return PackageSupport.TEMP_NO_SUPPORT

    if (
        setup_data.with_build
        and ebuild.package
        in constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_BUILD
    ):
        return PackageSupport.TEMP_NO_SUPPORT

    if (
        setup_data.with_build
        and setup_data.with_tests
        and ebuild.package
        in constants.TEMPORARY_UNSUPPORTED_PACKAGES_WITH_TESTS
    ):
        return PackageSupport.TEMP_NO_SUPPORT

    if ebuild.package in setup_data.skip_packages:
        return PackageSupport.TEMP_NO_SUPPORT

    return PackageSupport.SUPPORTED


class PackagePathException(Exception):
    """Exception indicating some troubles while looking for packages dirs."""

    def __init__(
        self,
        package,
        message: str,
        first_dir: str = None,
        second_dir: str = None,
    ):
        if not first_dir:
            super().__init__(f"{package.full_name}: {message}")
        elif not second_dir:
            super().__init__(f"{package.full_name}: {message}: '{first_dir}'")
        else:
            super().__init__(
                f"{package.full_name}: {message}: {first_dir} vs {second_dir}"
            )


class DirsException(PackagePathException):
    """Exception indicating some troubles while looking for packages dirs."""


class UnsupportedPackageException(Exception):
    """Exception indicating an attempt to create an unsupported package."""

    def __init__(self, package_name, reason: PackageSupport):
        self.package_name = package_name
        self.reason = reason
        super(Package.UnsupportedPackageException, self).__init__(
            f"{package_name}: Not supported due to: {reason}"
        )


class TempActualDichotomy(NamedTuple):
    """Data class for a package's actual source dir and temp source dir."""

    temp: str
    actual: str


class PackageInfo:
    """Data class containing basic info about a package."""

    def __init__(self, ebuild: portage_util.EBuild):
        self.ebuild_file = ebuild._unstable_ebuild_path
        self.category = ebuild.category
        self.name = ebuild.pkgname
        self.version = ebuild.version_no_rev
        # Extract revision from |version| formatted like
        # "|version_no_rev|-|revision|"
        self.revision = ebuild.version[len(ebuild.version_no_rev) + 1 :]


class Package:
    """A portage package, with access to paths associated with the package.

    NOTE: All dir fields are expected to exist when Initialize is called.
    NOTE: Only packages built with gn are supported.

    Attributes:
        setup: Config settings from setting up this run.
        full_name: The package's category+package name, such as
            chromeos-base/cryptohome.
        package_info: Various package info extracted from ebuild, like category
            and version. See |PackageInfo|.
        is_highly_volatile: Bool indicating whether the package's sources are
            patched on build. If true, then one should not expect an exact match
            between temp and actual sources.
        dependencies: List of package names on which this package depends.
        temp_dir: Base path to a dir with all temporary sources.
        build_dir: Path to a dir with build. Is expected to contain args.gn.
        src_dir_matches: List of tuples (temp, actual). Represents a possible
            match between temporary and actual source dirs/files. The list is
            sorted by depth: match is better when closer to desired path.
        additional_include_paths: List of actual paths to be added to include
            path arguments.
    """

    highly_volatile_packages = [
        # Libchrome has a number of patches applied on top of checkout.
        "chromeos-base/libchrome"
    ]

    # Package categories whose sources are in src dir and not in
    # src/third_party.
    src_categories = ["chromeos-base", "brillo-base"]

    def __init__(
        self,
        setup_data: setup.Setup,
        ebuild: portage_util.EBuild,
        deps: Optional[List[PackageDependency]] = None,
    ):
        """Initialize instance-level attributes.

        Raises:
            UnsupportedPackageException: If the package is not supported.
        """
        package_support = GetPackageSupport(ebuild, setup_data)
        if package_support.is_unsupported():
            raise UnsupportedPackageException(ebuild.package, package_support)

        self.setup = setup_data
        self.full_name = ebuild.package
        self.package_info = PackageInfo(ebuild)

        self.is_highly_volatile = (
            os.path.isdir(
                os.path.join(
                    os.path.dirname(self.package_info.ebuild_file), "files"
                )
            )
            or self.full_name in Package.highly_volatile_packages
        )
        self.dependencies = deps or []

        # Attributes that will be set up later, during Initialize().
        self.temp_dir: Optional[str] = None
        self.build_dir: Optional[str] = None
        self.src_dir_matches: Optional[List[str]] = None
        self.additional_include_paths: Optional[List[str]] = None

    def __eq__(self, other) -> bool:
        """Return whether |self| and |other| refer to the same package.

        If compared to another Package object, they are equal if they have the
        same full_name (category+package).
        If compared to a string, they are equal if the string equals this
        package's full_name (category+package).

        Raises:
            NotImplementedError: |other| is an unsupported type.
        """
        if isinstance(other, str):
            return self.full_name == other
        elif isinstance(other, Package):
            return self.full_name == other.full_name
        raise NotImplementedError("Can compare only with Package or string")

    def __str__(self) -> str:
        """Return a string representation of this package."""
        return self.full_name

    @property
    def is_built_from_actual_sources(self) -> bool:
        assert self.temp_dir
        out_of_tree_build = (
            _CheckEbuildVar(
                self.package_info.ebuild_file, "CROS_WORKON_OUTOFTREE_BUILD"
            )
            or "0"
        ) == "1"
        # Instead of calling 'cros-workon list', just check if workon version is
        # present.
        is_not_stable = "9999" in self.temp_dir
        return out_of_tree_build and is_not_stable

    def Initialize(self) -> None:
        """Find directories associated with the package and check they exist.

        This method will fail on a not-yet-built package, so make sure you've
        built the package with FEATURES=noclean flag.

        Raises:
            DirsException: Build, source or temp source dirs are not found.
        """
        logging.debug("%s: Initializing", self.full_name)

        self.temp_dir = self._GetTempDir()
        logging.debug("%s: Temp dir: %s", self.full_name, self.temp_dir)

        self.build_dir = self._GetBuildDir()
        logging.debug("%s: Build dir: %s", self.full_name, self.build_dir)

        self.src_dir_matches = self._GetSourceDirsToTempSourceDirsMap()

        self.additional_include_paths = self.GetAdditionalIncludePaths()
        if self.additional_include_paths:
            for path in self.additional_include_paths:
                if not os.path.isdir(path):
                    raise DirsException(
                        self, "Additional include path does not exist", path
                    )

    def GetAdditionalIncludePaths(self) -> Optional[List[str]]:
        """Return a list of actual paths to be added as include path args."""

        # Special case for chromeos-base/update_engine which pretends to be in
        # platform2 and uses platform2 as include path. While the actual include
        # path is {src_dir}/aosp/system with update_engine inside.
        if self.full_name == "chromeos-base/update_engine":
            return [os.path.join(self.setup.src_dir, "aosp", "system")]

        return None

    def _GetOrderedVersionSuffixes(self) -> List[str]:
        """Return the current package's versions, sorted from high to low."""

        return [
            "9999",
            f"{self.package_info.version}-{self.package_info.revision}",
            self.package_info.version,
        ]

    def _GetTempDir(self) -> str:
        """Return the path to the base temp dir (${WORKDIR} in portage).

        See WORKDIR entry on
        https://devmanual.gentoo.org/ebuild-writing/variables/index.html.

        Chooses the dir with the highest ebuild version.
        """

        base_dir = os.path.join(self.setup.board_dir, "tmp", "portage")
        not_in_dirs = []

        for version_suffix in self._GetOrderedVersionSuffixes():
            temp_dir = os.path.join(
                base_dir,
                self.package_info.category,
                f"{self.package_info.name}-{version_suffix}",
                "work",
            )

            if os.path.isdir(temp_dir):
                return temp_dir
            else:
                not_in_dirs.append(temp_dir)

        # Failed all tries, report and raise.
        dirs_tried = ", ".join([str(os.path.join(x)) for x in not_in_dirs])

        raise DirsException(self, "Cannot find temp dir in", dirs_tried)

    def _GetBuildDir(self) -> str:
        """Return the path to the dir with build metadata (where args.gn lives).

        Raises:
            DirsException: build dir is not found.
            DirsException: 'args.gn' file not found in any expected build dir.
        """
        build_dirs = [
            os.path.join(
                self.setup.board_dir,
                "var",
                "cache",
                "portage",
                self.package_info.category,
                self.package_info.name,
                "out",
                "Default",
            ),
            os.path.join(self.temp_dir, "build", "out", "Default"),
        ]

        for build_dir in build_dirs:
            if not os.path.isdir(build_dir):
                continue

            if not os.path.isfile(os.path.join(build_dir, "args.gn")):
                continue

            return build_dir

        raise DirsException(self, "Cannot find build dir")

    def _GetTempSourceBaseDir(self) -> Optional[str]:
        """Return the base source path within the temp dir (${S} in portage).

        See S on
        https://devmanual.gentoo.org/ebuild-writing/variables/index.html.

        The base source dir contains copied source files.
        """
        for version in self._GetOrderedVersionSuffixes():
            source_dir = os.path.join(
                self.temp_dir, f"{self.package_info.name}-{version}"
            )
            if os.path.isdir(source_dir):
                return source_dir
        return None

    def _GetEbuildSourceDirs(self) -> List[str]:
        """Return actual source dirs.

        Based on:
        https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=383
        """
        # Base dir is either src or src/third_party, depending on the package's
        # category.
        source_base_dir = self.setup.src_dir
        if self.package_info.category not in Package.src_categories:
            source_base_dir = os.path.join(source_base_dir, "third_party")

        # CROS_WORKON_SRCPATH and CROS_WORKON_LOCALNAME declare paths relative
        # to base source dir.
        source_dirs = _CheckEbuildVar(
            self.package_info.ebuild_file, "CROS_WORKON_SRCPATH", ""
        )
        if not source_dirs:
            source_dirs = _CheckEbuildVar(
                self.package_info.ebuild_file, "CROS_WORKON_LOCALNAME", ""
            )

        if not source_dirs:
            raise DirsException(
                self, "Cannot extract source dir(s) from ebuild file"
            )

        # |source_dirs| is a comma separated list of directories relative to the
        # source base dir.
        return [
            os.path.join(source_base_dir, dir) for dir in source_dirs.split(",")
        ]

    def _GetEbuildDestDirs(self, temp_source_basedir: str) -> List[str]:
        """Return destination source dirs.

        Dest dirs contain temp copy of source dirs.

        Based on _cros-workon_emit_src_to_buid_dest_map():
        https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=474
        """

        # CROS_WORKON_DESTDIR declares abs paths in |temp_source_basedir|.
        dest_dirs = _CheckEbuildVar(
            self.package_info.ebuild_file,
            "CROS_WORKON_DESTDIR",
            temp_source_basedir,
        )

        if not dest_dirs:
            # Defaults to ${S}:
            # https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=583
            return [temp_source_basedir]
        else:
            # |dest_dirs| is a comma-separated list of absolute paths to dirs.
            return dest_dirs.split(",")

    def _GetSourceDirsToTempSourceDirsMap(self) -> List[TempActualDichotomy]:
        """Return a list of matches between actual src dirs and temp src dirs.

        See cros-workon_src_unpack() on
        https://crsrc.org/o/src/third_party/chromiumos-overlay/eclass/cros-workon.eclass;drc=236057acc44bead024a78b50362ec2c82205c286;l=564

        Raises:
            DirsException: Cannot find temp source dir for non-workon,
                non-out-of-tree package.
            DirsException: Cannot find actual source dirs.
            DirsException: Cannot find temp source dirs.
            DirsException: Cannot map actual source dirs to temp source dirs.
        """
        temp_source_basedir = self._GetTempSourceBaseDir()

        if not temp_source_basedir:
            if not self.is_built_from_actual_sources:
                raise DirsException(
                    self,
                    "Only workon and out-of-tree packages may not have temp "
                    "source copy",
                )
            # Out-of-tree packages are not copied but are built from the actual
            # sources.
            source_dirs = self._GetEbuildSourceDirs()
            return [
                TempActualDichotomy(temp=source_dir, actual=source_dir)
                for source_dir in source_dirs
            ]

        # cros-workon.eclass maps source dirs to dest dirs extracted from the
        # ebuild, in the order that they are declared.
        source_dirs = self._GetEbuildSourceDirs()
        dest_dirs = self._GetEbuildDestDirs(temp_source_basedir)

        if len(source_dirs) != len(dest_dirs):
            raise DirsException(
                self, "Different number of src and temp src dirs"
            )

        matches = [
            TempActualDichotomy(temp=dest, actual=source)
            for source, dest in zip(source_dirs, dest_dirs)
        ]

        for match in matches:
            if not os.path.isdir(match.actual):
                raise DirsException(self, "Cannot find src dir", match.actual)

            if not os.path.isdir(match.temp):
                raise DirsException(
                    self, "Cannot find temp src dir", match.temp
                )
            logging.debug(
                "%s: Match between temp and actual: %s and %s",
                self.full_name,
                match.temp,
                match.actual,
            )

        # Sort by actual source dir length so the deepest and most accurate
        # match appears first.
        matches.sort(key=lambda match: len(match.actual), reverse=True)

        return matches
