# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods for reading and building manifests exported by the subtools builder.

Loads and interprets subtools export manifests defined by the proto at
https://crsrc.org/o/src/config/proto/chromiumos/build/api/subtools.proto
"""

from pathlib import Path
import re
import shutil
from typing import List, Literal, Optional, Set

from chromite.third_party import lddtree
from chromite.third_party.google import protobuf
from chromite.third_party.google.protobuf import text_format

import chromite
from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import cipd
from chromite.lib import filetype
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.licensing import licenses_lib


logger = chromite.ChromiteLogger.getLogger(__name__)


class Error(Exception):
    """Module base error class."""

    def __init__(self, message: str, subtool: object):
        # TODO(build): Use self.add_note when Python 3.11 is available.
        super().__init__(f"{message}\nSubtool:\n{subtool}")


class ManifestInvalidError(Error):
    """The contents of the subtool package manifest proto are invalid."""


class ManifestBundlingError(Error):
    """The subtool could not be bundled."""


# Default glob to find export package manifests under the config_dir.
SUBTOOLS_EXPORTS_GLOB = "**/*.textproto"

# Path (relative to the bundle root) of the license file generated from the
# licenses of input files.
LICENSE_FILE = Path("license.html.gz")

# Standard set of arguments passed to all `lddtree` invocations.
LDDTREE_ARGS = ["--libdir", "/lib", "--bindir", "/bin", "--generate-wrappers"]

# Valid names. A stricter version of `packageNameRe` in
# https://crsrc.org/i/go/src/go.chromium.org/luci/cipd/common/common.go
# Diallows slashes and starting with a ".".
_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9_\-]+[a-z0-9_\-\.]*$")

# Default destination path in the bundle when not specified on a PathMapping.
_DEFAULT_DEST = "bin"

# Default regex to apply to input paths when bundling.
_DEFAULT_STRIP_PREFIX_REGEX = "^.*/"

# Default CIPD prefix when unspecified.
_DEFAULT_CIPD_PREFIX = "chromiumos/infra/tools"

# Allow the FileTypeDecoder to keep its cache, for files rooted at "/".
_FILETYPE_DECODER = filetype.FileTypeDecoder()


def get_installed_package(
    query: str, error_context: "Subtool"
) -> portage_util.InstalledPackage:
    """Returns an InstalledPackage for an installed ebuild."""
    packages = portage_util.FindPackageNameMatches(query)
    if len(packages) != 1:
        raise ManifestBundlingError(
            f"Package '{query}' must match exactly one package."
            f" Matched {len(packages)} -> {packages}.",
            error_context,
        )
    logger.debug("%s matched %s", query, packages[0])
    installed_package = portage_util.PortageDB().GetInstalledPackage(
        packages[0].category, packages[0].pvr
    )
    if not installed_package:
        atom = packages[0].atom
        raise ManifestBundlingError(
            f"Failed to map {query}=>{atom} to an *installed* package.",
            error_context,
        )
    return installed_package


class Subtool:
    """A subtool, backed by a .textproto manifest.

    Attributes:
        manifest_path: The source .textproto, used for debug output.
        package: The parsed protobuf message.
        work_root: Root path in which to build bundles for export.
        is_valid: Set after validation to indicate an export may be attempted.
        parse_error: Protobuf parse error held until validation.
    """

    def __init__(self, message: str, path: Path, work_root: Path):
        """Loads from a .textpoto file contents.

        Args:
            message: The contents of the .textproto file.
            path: The source file (for logging).
            work_root: Location on disk where packages are built.
        """
        self.manifest_path = path
        self.package = subtools_pb2.SubtoolPackage()
        self.work_root = work_root
        self.is_valid: Optional[bool] = None
        self.parse_error: Optional[text_format.ParseError] = None

        # Set of c/p-v-r strings that provided the bundle contents.
        self._source_ebuilds: Set[str] = set()
        # Paths bundled, but not yet attributed to a source ebuild.
        self._unmatched_paths: List[str] = []

        try:
            text_format.Parse(message, self.package)
        except text_format.ParseError as e:
            self.parse_error = e

    @classmethod
    def from_file(cls, path: Path, work_root: Path) -> "Subtool":
        """Helper to construct a Subtool from a path on disk."""
        return cls(path.read_text(encoding="utf-8"), path, work_root)

    def __str__(self) -> str:
        """Debug output; emits the parsed textproto and source filename."""
        textproto = text_format.MessageToString(self.package)
        return (
            f"{'=' * 10} {self.manifest_path} {'=' * 10}\n"
            + textproto
            + "=" * (len(self.manifest_path.as_posix()) + 22)
        )

    def _work_dir(self) -> Path:
        """Returns the path under work_root for creating files for export."""
        return self.work_root / self.package.name

    @property
    def metadata_dir(self) -> Path:
        """Path holding all work relating specifically to this package."""
        return self._work_dir()

    @property
    def bundle_dir(self) -> Path:
        """Path (under metadata) holding files to form the exported bundle."""
        return self._work_dir() / "bundle"

    @property
    def cipd_package(self) -> str:
        """Full path to the CIPD package name."""
        prefix = (
            self.package.cipd_prefix
            if self.package.HasField("cipd_prefix")
            else _DEFAULT_CIPD_PREFIX
        )
        return f"{prefix.rstrip('/')}/{self.package.name}"

    @property
    def summary(self) -> str:
        """A one-line summary describing this package."""
        return f"{self.package.name} (http://go/cipd/p/{self.cipd_package})"

    @property
    def source_packages(self) -> List[str]:
        """The list of packages that contributed files during bundling."""
        return sorted(self._source_ebuilds)

    def stamp(self, kind: Literal["bundled", "exported"]) -> Path:
        """Returns the path to a "stamp" file that tracks export progress."""
        return self.metadata_dir / f".{kind}"

    def clean(self) -> None:
        """Resets export progress and removes the temporary bundle tree."""
        self.stamp("bundled").unlink(missing_ok=True)
        self.stamp("exported").unlink(missing_ok=True)
        osutils.RmDir(self.bundle_dir, ignore_missing=True)

    def bundle(self) -> None:
        """Collect and bundle files described in `package` in the work dir."""
        self._validate()
        self._collect_files()
        self._match_ebuilds()
        self._collect_licenses()
        # TODO(b/277992359): hashing.
        self.stamp("bundled").touch()

    def export(self, use_production: bool, cipd_path: str) -> None:
        """Export the bundle, e.g., to cipd."""
        self._validate()
        if not self.stamp("bundled").exists():
            raise ManifestBundlingError("Bundling incomplete.", self)
        tags = {
            "builder_source": "sdk_subtools",
            "ebuild_source": ",".join(self.source_packages),
        }
        refs = ["latest"]
        cipd.CreatePackage(
            cipd_path,
            self.cipd_package,
            self.bundle_dir,
            tags,
            refs,
            service_url=None if use_production else cipd.STAGING_SERVICE_URL,
        )
        self.stamp("exported").touch()

    def _validate(self) -> None:
        """Validate fields in the proto."""
        if self.is_valid:
            # Note this does not worry about validity invalidation, e.g., due to
            # changed disk state since validation.
            return

        if self.parse_error:
            error = ManifestInvalidError(
                f"ParseError in .textproto: {self.parse_error}", self
            )
            error.__cause__ = self.parse_error
            raise error

        if not _PACKAGE_NAME_RE.match(self.package.name):
            raise ManifestInvalidError(
                f"Subtool name must match '{_PACKAGE_NAME_RE.pattern}'", self
            )
        if not self.package.paths:
            raise ManifestInvalidError("At least one path is required", self)

        # TODO(b/277992359): Validate more proto fields.

        self.is_valid = True

    def _copy_into_bundle(
        self, src: Path, destdir: Path, strip: re.Pattern
    ) -> int:
        """Copies a file on disk into the bundling folder.

        Copies only files (follows symlinks). Ensures files are not clobbered.
        Returns the number of files copied.
        """
        if not src.is_file():
            return 0

        # Apply the regex, and ensure the result is not an absolute path.
        dest = destdir / strip.sub("", src.as_posix()).lstrip("/")
        if dest.exists():
            raise ManifestBundlingError(
                f"{dest} exists: refusing to copy {src}.", self
            )
        osutils.SafeMakedirs(dest.parent)

        if _FILETYPE_DECODER.GetType(str(src)) == "binary/elf/dynamic-bin":
            return self._lddtree_into_bundle(src, dest.parent)

        logger.debug("Copy file %s -> %s.", src, dest)
        shutil.copy2(src, dest)
        return 1

    def _lddtree_into_bundle(self, elf: Path, destdir: Path) -> int:
        """Copies a dynamic elf into the bundle."""
        # Output of the main script is always `bin`, so avoid `bin/bin`.
        if destdir.name == "bin":
            destdir = destdir.parent
        lddtree.main(LDDTREE_ARGS + ["--copy-to-tree", str(destdir), str(elf)])
        # The globbing is done already, so there's no big concern about
        # accidentally bundling the entire filesystem. Count as "1 file".
        return 1

    def _check_counts(self, file_count: int) -> None:
        """Raise an error if files violate the manifest spec."""
        if file_count > self.package.max_files:
            raise ManifestBundlingError(
                f"Max file count ({self.package.max_files}) exceeded.", self
            )

    def _bundle_mapping(
        self, mapping: subtools_pb2.SubtoolPackage.PathMapping
    ) -> int:
        """Bundle files for the provided `mapping`.

        Returns the number of files matched.
        """
        subdir = mapping.dest if mapping.HasField("dest") else _DEFAULT_DEST
        destdir = self.bundle_dir / subdir.lstrip("/")
        strip_prefix_regex = (
            mapping.strip_prefix_regex
            if mapping.HasField("strip_prefix_regex")
            else _DEFAULT_STRIP_PREFIX_REGEX
        )
        strip = re.compile(strip_prefix_regex)

        # Any leading '/' must be stripped from the glob (pathlib only supports
        # relative patterns when matching). Steps below effectively restore it.
        glob = mapping.input.lstrip("/")

        file_count = 0

        if mapping.ebuild_filter:
            package = get_installed_package(mapping.ebuild_filter, self)
            for _file_type, relative_path in package.ListContents():
                path = Path(f"/{relative_path}")
                if not path.match(glob):
                    continue
                file_count += self._copy_into_bundle(path, destdir, strip)
                self._check_counts(file_count)
            if file_count:
                self._source_ebuilds.add(package.package_info.cpvr)
        else:
            for path in Path("/").glob(glob):
                added_files = self._copy_into_bundle(path, destdir, strip)
                if not added_files:
                    continue
                file_count += added_files
                self._check_counts(file_count)
                self._unmatched_paths.append(str(path))

        if file_count == 0:
            raise ManifestBundlingError(
                f"Input field {mapping.input} matched no files.", self
            )
        logger.info("Glob '%s' matched %d files.", mapping.input, file_count)
        return file_count

    def _collect_files(self) -> None:
        """Collect files described by the package manifest in the work dir."""
        self.clean()
        self.metadata_dir.mkdir(exist_ok=True)
        self.bundle_dir.mkdir()
        logger.notice(
            "%s: Subtool bundling under %s.", self.package.name, self.bundle_dir
        )
        # Emit the full .textproto to debug logs.
        logger.debug(self)
        file_count = 0
        self._source_ebuilds = set()
        self._unmatched_paths = []
        for path in self.package.paths:
            file_count += self._bundle_mapping(path)
        logger.notice("%s: Copied %d files.", self.package.name, file_count)

    def _match_ebuilds(self) -> None:
        """Match up unmatched paths to the package names that provided them."""
        if self._unmatched_paths:
            ebuilds = portage_util.FindPackageNamesForFiles(
                *self._unmatched_paths
            )
            # Assume all files were matched, and that it is not an error for any
            # file to not be matched to a package.
            self._unmatched_paths = []
            self._source_ebuilds.update(e.cpvr for e in ebuilds)
        if len(self._source_ebuilds) != 1:
            # TODO(b/277992359): Support this with an extra proto field.
            raise ManifestBundlingError(
                "Bundle cannot be attributed to exactly one package."
                f" Candidates: {self.source_packages}",
                self,
            )
        logger.notice("Contents provided by %s", self.source_packages)

    def _collect_licenses(self) -> None:
        """Generates a license file from `source_packages`."""
        packages = self.source_packages
        if not packages:
            # Avoid putting a useless file into the bundle in this case. But it
            # is only hit when _match_ebuilds is skipped (in tests).
            return

        logger.notice("%s: Collecting licenses.", self.package.name)
        # TODO(b/297978537): Use portage_util.GetFlattenedDepsForPackage to get
        # a full depgraph.
        licensing = licenses_lib.Licensing(
            sysroot="/", package_fullnames=packages, gen_licenses=True
        )
        licensing.LoadPackageInfo()
        licensing.ProcessPackageLicenses()
        # NOTE(b/297978537): Location of license files in the bundle is not
        # yet configurable. Dump it in the package root.
        licensing.GenerateHTMLLicenseOutput(
            self.bundle_dir / LICENSE_FILE, compress_output=True
        )


class InstalledSubtools:
    """Wraps the set of subtool manifests installed on the system.

    Attributes:
        subtools: Collection of parsed subtool manifests.
        work_root: Root folder where all packages are bundled.
    """

    def __init__(
        self,
        config_dir: Path,
        work_root: Path,
        glob: str = SUBTOOLS_EXPORTS_GLOB,
    ):
        logger.notice(
            "Loading subtools from %s/%s with Protobuf library v%s",
            config_dir,
            glob,
            protobuf.__version__,
        )
        self.work_root = work_root
        self.subtools = [
            Subtool.from_file(f, work_root) for f in config_dir.glob(glob)
        ]

    def bundle_all(self) -> None:
        """Read .textprotos and bundle blobs into `work_root`."""
        self.work_root.mkdir(exist_ok=True)
        for subtool in self.subtools:
            subtool.bundle()

    def export(
        self, use_production: bool, export_filter: Optional[List[str]] = None
    ) -> None:
        """Read .textprotos and export valid bundles in `work_root`.

        Args:
            use_production: Whether to export to production environments.
            export_filter: If provided, only export subtools with these names.
        """
        cipd_path = cipd.GetCIPDFromCache()
        for subtool in self.subtools:
            if export_filter is None or subtool.package.name in export_filter:
                subtool.export(use_production, cipd_path)
