# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods for reading and building manifests exported by the subtools builder.

Loads and interprets subtools export manifests defined by the proto at
https://crsrc.org/o/src/config/proto/chromiumos/build/api/subtools.proto
"""

import dataclasses
import fnmatch
import functools
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
from typing import Any, Dict, List, Literal, Optional, Set

from chromite.third_party import lddtree
from chromite.third_party.google import protobuf
from chromite.third_party.google.protobuf import text_format

import chromite
from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import cipd
from chromite.lib import compression_lib
from chromite.lib import cros_build_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib.parser import package_info
from chromite.licensing import licenses_lib
from chromite.utils import compat
from chromite.utils import gs_urls_util


try:
    # The filetype module imports `magic` which is available in the SDK, glinux
    # and vpython environments, but not on bots outside the SDK.
    from chromite.lib import filetype
except ImportError:
    cros_build_lib.AssertOutsideChroot()

logger = chromite.ChromiteLogger.getLogger(__name__)


class Error(Exception):
    """Module base error class."""

    def __init__(self, message: str, subtool: object) -> None:
        # TODO(build): Use self.add_note when Python 3.11 is available.
        super().__init__(f"{message}\nSubtool:\n{subtool}")


class ManifestInvalidError(Error):
    """The contents of the subtool package manifest proto are invalid."""


class ManifestBundlingError(Error):
    """The subtool could not be bundled."""


# Use `cipd` from $PATH, which usually comes from a pin in depot_tools. An
# alternative, cipd.GetCIPDFromCache(), could be used which has a version pinned
# inside chromite. But there's no reason to pick it.
CIPD_PATH = "cipd"

# Default glob to find export package manifests under the config_dir.
SUBTOOLS_EXPORTS_GLOB = "**/*.textproto"

# Path (relative to the bundle root) of the license file generated from the
# licenses of input files. Note the suffix determines the compressor. If GZIP
# is used, the `--no-name` argument must also be passed. Otherwise gzip will
# include the random name of the temporary file and a timestamp in its header,
# which defeats idempotence. This is important to ensure CIPD can de-dupe
# identical uploads.
LICENSE_FILE = Path("license.html.zst")

# Path (relative to the metadata work dir) of serialized upload metadata.
UPLOAD_METADATA_FILE = Path("subtool_upload.json")

# CIPD metadata tag key for storing the hash calculated by the subtools builder.
SUBTOOLS_HASH_TAG = "subtools_hash"

# A generous hardcoded limit for bundles managed by the subtools builder. This
# reflects the desire to be considerate with downstream resources such as CIPD
# storage buckets and developer disk space, rather than a limit imposed by other
# systems. If a use case arises for something bigger, there may be scope to add
# a manifest attribute to permit a higher threshold. The full, uncompressed size
# of bundle content is accumulated, before any upload to CIPD. We allow a more
# gracious limit for uploads to GCS, partly as compression is better (zstd
# tarball instead of zip archive), but also because resources are cheaper.

MAX_BUNDLE_SIZE_BYTES = {
    subtools_pb2.SubtoolPackage.EXPORT_CIPD: 500_000_000,
    subtools_pb2.SubtoolPackage.EXPORT_GCS: 5_000_000_000,
}

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

# Portage overlays known to be public. If files came from ebuilds outside of
# these overlays then no default CIPD prefix will be provided.
_KNOWN_PUBLIC_OVERLAYS = frozenset(
    (
        "amd64-host",
        "chromiumos",
        "crossdev",
        "eclass-overlay",
        "portage-stable",
        "toolchains",
    )
)

# Digest from hashlib to use for hashing files and accumulating hashes.
_DIGEST = "sha1"

# Mapping from proto ARCHIVE_FORMAT_* to CompressionType.
_ARCHIVE_FORMAT_MAP = {
    subtools_pb2.SubtoolPackage.GcsExportOptions.ARCHIVE_FORMAT_TAR_ZST: (
        compression_lib.CompressionType.ZSTD
    ),
}

# Mapping from CompressionType to extension used.
_COMPRESSION_EXTENSIONS = {
    compression_lib.CompressionType.ZSTD: ".tar.zst",
}


@dataclasses.dataclass
class CipdMetadata:
    """Structure of a `cipd_package` in serialized metadata.

    This is reconstructed from JSON, so should not reference other classes.
    Optional members can be added, but should never be removed or added in a way
    that assumes their presence, because they may be serialized by old branches.

    IMPORTANT: Always include type annotations, or you'll get a class variable
    per PEP0526, and it will be omitted from serialization.

    Attributes:
        package: The CIPD package prefix.
        tags: Tags to associate with the package upload.
        refs: Refs to associate with the package upload.
        search_tags: Tag keys that determine whether an existing instance is
            equivalent. If this is empty, all (known) `tags` are used.
    """

    package: str = ""
    tags: Dict[str, str] = dataclasses.field(default_factory=dict)
    refs: List[str] = dataclasses.field(default_factory=list)
    search_tags: List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class GcsMetadata:
    """Metadata for packages which get uploaded to a GS bucket.

    This is reconstructed as a Dict. Essentially it maps keys to a metadata
    subtype. Members should not be removed and the reader must be able to handle
    any prior structure.

    IMPORTANT: Always include type annotations.

    Attributes:
        bucket: The bucket to upload to.
        package_name: The package name.
        digest: A unique hash of the content of the package.
        version: A version number to use for subdirectory name.
        compression: The compression to use for the tarball.
        prefix: An optional subdirectory in that bucket to use.
    """

    bucket: str
    package_name: str
    version: str
    digest: str
    compression: compression_lib.CompressionType
    prefix: Optional[str] = None


@dataclasses.dataclass
class UploadMetadata:
    """Structure of the serialized upload metadata.

    This is reconstructed as a Dict. Essentially it maps keys to a metadata
    subtype. Members should not be removed and the reader must be able to handle
    any prior structure.

    IMPORTANT: Always include type annotations.

    Attributes:
        upload_metadata_version: Version of the upload metadata file structure.
            Increment this when making changes that require the ToT uploader to
            change logic for files produced on old branches.
        cipd_package: Metadata for uploading a CIPD package.
    """

    upload_metadata_version: int = 1
    cipd_package: CipdMetadata = dataclasses.field(default_factory=CipdMetadata)
    gcs_metadata: Optional[GcsMetadata] = None

    @staticmethod
    def from_dict(d: Dict[str, Dict[str, Any]]) -> "UploadMetadata":
        metadata = UploadMetadata()
        # Fields are never removed, and all have default values, so just unpack.
        metadata.cipd_package = CipdMetadata(**d.get("cipd_package", {}))
        gcs_metadata = d.get("gcs_metadata")
        if gcs_metadata:
            metadata.gcs_metadata = GcsMetadata(**gcs_metadata)
        return metadata


def _extract_build_id(file: Path) -> Optional[str]:
    """Runs `readelf -n` to extract a Build ID as a hex string."""
    BUILD_ID_PATTERN = re.compile("^    Build ID: *([0-9a-f]+)", re.MULTILINE)
    result = cros_build_lib.run(
        ["readelf", "-n", file], capture_output=True, encoding="utf-8"
    ).stdout
    match = BUILD_ID_PATTERN.search(result)
    return match.group(1) if match else None


def extract_hash(file: Path, file_type: str) -> str:
    """Extract build-id from an ELF binary, falling back to a file hash.

    Args:
        file: The file to hash.
        file_type: The result of filetype.FileTypeDecoder.GetType for `file`.

    Returns:
        A hexadecimal string: either the Build ID or file hash.
    """
    if file_type.startswith("binary/elf"):
        build_id = _extract_build_id(file)
        # Only accept BuildID that are at least 64-bit. 160-bit is also common.
        if build_id and len(build_id) >= 8:
            return build_id
        logger.warning(
            "%s is binary/elf but BuildID is bad. Falling back to %s hash",
            file,
            _DIGEST,
        )
    else:
        logger.debug("Hashing %s with %s", file, _DIGEST)

    # TODO(build): Use hashlib.file_digest in Python 3.11.
    BUFSIZE = 256 * 1024
    hasher = hashlib.new(_DIGEST)
    with open(file, "rb") as fp:
        buf = fp.read(BUFSIZE)
        while buf:
            hasher.update(buf)
            buf = fp.read(BUFSIZE)
    return hasher.hexdigest()


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
        work_root: Root path in which to build bundles for upload.
        is_valid: Set after validation to indicate an upload may be attempted.
        parse_error: Protobuf parse error held until validation.
    """

    # Allow the FileTypeDecoder to keep its cache, for files rooted at "/".
    _FILETYPE_DECODER: Optional["filetype.FileTypeDecoder"] = None

    @classmethod
    def get_file_type(cls, path: Path) -> str:
        """Gets the type of `path` using FileTypeDecoder, following symlinks."""
        if not cls._FILETYPE_DECODER:
            cls._FILETYPE_DECODER = filetype.FileTypeDecoder()
        # Resolve symlinks (to avoid type=inode/symlink).
        return cls._FILETYPE_DECODER.GetType(str(path.resolve()))

    def __init__(self, message: str, path: Path, work_root: Path) -> None:
        """Loads from a .textpoto file contents.

        Args:
            message: The contents of the .textproto file.
            path: The source file.
            work_root: Location on disk where packages are built.
        """
        self.manifest_path = path
        self.package = subtools_pb2.SubtoolPackage()
        self.work_root = work_root
        self.is_valid: Optional[bool] = None
        self.parse_error: Optional[text_format.ParseError] = None

        # Set of c/p-v-r strings that provided the bundle contents.
        self._source_ebuilds: Set[str] = set()

        # Paths bundled, but not yet attributed to a source ebuild. Always
        # include the .textproto path: it may belong to a bespoke ebuild, so
        # this ensures it gets included on metadata tags as well.
        self._unmatched_paths = [str(path)]

        # Running digest of accumulated hashes from file contents, maps the
        # destination file to its hash. Not all destination files may be hashed:
        # only the ones whose hashes we care about. Hash is either a 16- or 40-
        # character hex string.
        self._content_hashes: Dict[str, str] = {}

        # A count of files matched against globs during bundling. This is
        # tracked while gathering files to provide an early exit for globs that
        # inadvertently match too many files.
        self._file_count = 0

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
        """Returns the path under work_root for creating files for upload."""
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
        assert self.package.type == subtools_pb2.SubtoolPackage.EXPORT_CIPD

        prefix = self.package.cipd_prefix or _DEFAULT_CIPD_PREFIX
        return f"{prefix.rstrip('/')}/{self.package.name}"

    @property
    def url(self) -> str:
        """A URL where the package can be found.

        This should be a URL for humans to go click on, and not necessarily the
        exact URL where the package will be uploaded.
        """
        if self.package.type == subtools_pb2.SubtoolPackage.EXPORT_CIPD:
            return f"http://go/cipd/{self.cipd_package}"
        elif self.package.type == subtools_pb2.SubtoolPackage.EXPORT_GCS:
            suburl = self.package.name
            if self.package.gcs_export_options.prefix:
                suburl = f"{self.package.gcs_export_options.prefix}/{suburl}"
            return gs_urls_util.GetGsURL(
                bucket=self.package.gcs_export_options.bucket,
                suburl=suburl,
                public=False,
            )
        raise NotImplementedError(
            f"URL not implemented for {self.package.type}"
        )

    @property
    def summary(self) -> str:
        """A one-line summary describing this package."""
        return f"{self.package.name} ({self.url})"

    @property
    def source_packages(self) -> List[str]:
        """The list of packages that contributed files during bundling."""
        return sorted(self._source_ebuilds)

    @functools.cached_property
    def manifest_package(self) -> package_info.PackageInfo:
        """The package which installed the textproto config for this subtool."""
        packages = portage_util.FindPackageNamesForFiles(
            str(self.manifest_path)
        )
        if len(packages) != 1:
            raise ValueError(
                f"Expected {self.manifest_path} to belong to exactly one "
                f"source package.  Belongs to: {packages}"
            )
        return packages[0]

    def stamp(self, kind: Literal["bundled", "uploaded"]) -> Path:
        """Returns the path to a "stamp" file that tracks export progress."""
        return self.metadata_dir / f".{kind}"

    def clean(self) -> None:
        """Resets export progress and removes the temporary bundle tree."""
        self.stamp("bundled").unlink(missing_ok=True)
        (self.metadata_dir / UPLOAD_METADATA_FILE).unlink(missing_ok=True)
        self.stamp("uploaded").unlink(missing_ok=True)
        osutils.RmDir(self.bundle_dir, ignore_missing=True)

    def bundle(self) -> None:
        """Collect and bundle files described in `package` in the work dir."""
        self._validate()
        self._collect_files()
        self._match_ebuilds()
        self._validate_cipd_prefix()
        self._collect_licenses()
        self.stamp("bundled").touch()

    def prepare_upload(self) -> None:
        """Prepares metadata required to upload the bundle, e.g., to cipd."""
        self._validate()
        self._validate_bundle()

        BUILDER_TAG = "builder_source"
        EBUILD_TAG = "ebuild_source"
        CHANGE_REVISION_ONLY = subtools_pb2.SubtoolPackage.CHANGE_REVISION_ONLY

        metadata = UploadMetadata()
        if self.package.type == subtools_pb2.SubtoolPackage.EXPORT_CIPD:
            metadata.cipd_package.package = self.cipd_package
            metadata.cipd_package.refs = ["latest"]
            metadata.cipd_package.tags = {
                BUILDER_TAG: "sdk_subtools",
                EBUILD_TAG: ",".join(self.source_packages),
                SUBTOOLS_HASH_TAG: self._calculate_digest(),
            }
            if self.package.upload_trigger == CHANGE_REVISION_ONLY:
                metadata.cipd_package.search_tags = [BUILDER_TAG, EBUILD_TAG]
        elif self.package.type == subtools_pb2.SubtoolPackage.EXPORT_GCS:
            compression = _ARCHIVE_FORMAT_MAP.get(
                self.package.gcs_export_options.archive_format
            )
            if not compression:
                raise NotImplementedError(
                    "Unsupported archive format: "
                    f"{self.package.gcs_export_options.archive_format}"
                )
            metadata.gcs_metadata = GcsMetadata(
                package_name=self.package.name,
                bucket=self.package.gcs_export_options.bucket,
                prefix=self.package.gcs_export_options.prefix or None,
                version=self.manifest_package.vr,
                digest=self._calculate_digest(),
                compression=compression,
            )
        else:
            raise NotImplementedError(f"Unknown type: {self.package.type}")

        metadata_path = self.metadata_dir / UPLOAD_METADATA_FILE
        with metadata_path.open("w", encoding="utf-8") as fp:
            json.dump(dataclasses.asdict(metadata), fp)

        logger.notice("%s: Wrote %s.", self.package.name, metadata_path)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Contents: `%s`", metadata_path.read_text())

    def _validate_bundle(self) -> str:
        """Validate the bundled contents."""
        if not self.stamp("bundled").exists():
            raise ManifestBundlingError("Bundling incomplete.", self)

        max_size = MAX_BUNDLE_SIZE_BYTES[self.package.type]
        apparent_size = 0
        for file in self.bundle_dir.rglob("*"):
            apparent_size += os.lstat(file).st_size
        if apparent_size > max_size:
            raise ManifestBundlingError(
                "Bundle is too big."
                f" Apparent size={apparent_size} bytes,"
                f" threshold={max_size}.",
                self,
            )

    def _calculate_digest(self) -> str:
        """Calculates the digest of the bundled contents."""
        hasher = hashlib.new(_DIGEST)
        # Sort by path before hashing.
        for _, hash_string in sorted(self._content_hashes.items()):
            hasher.update(bytes.fromhex(hash_string))
        return hasher.hexdigest()

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
        self,
        src: Path,
        destdir: Path,
        strip: re.Pattern,
        mapping: subtools_pb2.SubtoolPackage.PathMapping,
    ) -> None:
        """Copies a file on disk into the bundling folder.

        Copies only files (follows symlinks). Ensures files are not clobbered.
        """
        # Apply the regex, and ensure the result is not an absolute path.
        dest = destdir / strip.sub("", src.as_posix()).lstrip("/")

        if (
            src.is_symlink()
            and self.package.symlink_mode
            == subtools_pb2.SubtoolPackage.SYMLINK_PRESERVE
        ):
            target = Path(os.readlink(src))
            if target.is_absolute():
                raise ManifestBundlingError(
                    f"Absolute symlink not permitted: {src} -> {target}",
                    self,
                )
            dest.parent.mkdir(exist_ok=True, parents=True)
            osutils.SafeSymlink(target, dest)
            self._content_hashes[str(dest)] = hashlib.new(
                _DIGEST, str(target).encode("utf-8")
            ).hexdigest()
            self._increment_file_count()
            return

        if not src.is_file():
            return

        if dest.exists():
            if dest.read_bytes() == src.read_bytes():
                logger.warning(
                    "%s exists at %s but is identical, skipping copy",
                    src,
                    dest,
                )
                return
            raise ManifestBundlingError(
                f"{dest} exists and differs: refusing to copy {src}.", self
            )

        # Increment here: lddtree may add more than one file, but there will be
        # an upper bound, so no conerns about overly greedy globs.
        self._increment_file_count()

        osutils.SafeMakedirs(dest.parent)
        file_type = self.get_file_type(src)
        hash_string = extract_hash(src, file_type)
        self._content_hashes[str(dest)] = hash_string
        logger.debug("subtools_hash(%s) = '%s'", src, hash_string)

        if not mapping.opaque_data and file_type == "binary/elf/dynamic-bin":
            self._lddtree_into_bundle(src, dest)
            return

        logger.debug(
            "Copy file %s -> %s (type=%s, hash=%s).",
            src,
            dest,
            file_type,
            hash_string,
        )
        shutil.copy2(src, dest)

    def _lddtree_into_bundle(self, elf: Path, dest: Path) -> None:
        """Copies a dynamic elf into the bundle."""
        lddtree_args = [
            "--generate-wrappers",
            "--libdir",
            "/lib",
            "--bindir",
            str(Path("/") / dest.parent.relative_to(self.bundle_dir)),
            "--copy-to-tree",
            str(self.bundle_dir),
            str(elf),
        ]
        logger.debug(
            "Using lddtree to copy dynamic elf %s to %s (lddtree_args=%s)",
            elf,
            dest,
            lddtree_args,
        )
        lddtree.main(lddtree_args)

    def _increment_file_count(self) -> None:
        """Increment the file count, and raise an error if it violates spec."""
        self._file_count += 1
        if self._file_count > self.package.max_files:
            raise ManifestBundlingError(
                f"Max file count ({self.package.max_files}) exceeded.", self
            )

    def _bundle_mapping(
        self, mapping: subtools_pb2.SubtoolPackage.PathMapping
    ) -> None:
        """Bundle files for the provided `mapping`."""
        subdir = mapping.dest or _DEFAULT_DEST
        destdir = self.bundle_dir / subdir.lstrip("/")
        strip = re.compile(
            mapping.strip_prefix_regex or _DEFAULT_STRIP_PREFIX_REGEX
        )

        # Any leading '/' must be stripped from the glob (pathlib only supports
        # relative patterns when matching). Later steps effectively restore it.
        globs = [x.lstrip("/") for x in mapping.input]

        for glob in globs:
            # For each input, detect if it is usefully adding files. If it
            # matches nothing, the entry should be removed.
            file_count_before_entry = self._file_count

            if mapping.ebuild_filter:
                self._bundle_with_ebuild_filter(glob, destdir, strip, mapping)
            else:
                self._bundle_with_all_disk(glob, destdir, strip, mapping)

            if self._file_count == file_count_before_entry:
                raise ManifestBundlingError(
                    f"Input field {glob} matched no files.", self
                )

        logger.info("After %s, bundle has %d files.", globs, self._file_count)

    def _bundle_with_ebuild_filter(
        self,
        glob: str,
        destdir: Path,
        strip: re.Pattern,
        mapping: subtools_pb2.SubtoolPackage.PathMapping,
    ) -> None:
        """Matches `glob` against files installed by a portage package."""
        package = get_installed_package(mapping.ebuild_filter, self)
        for _file_type, relative_path in package.ListContents():
            if fnmatch.fnmatch(relative_path, glob):
                self._copy_into_bundle(
                    Path("/") / relative_path, destdir, strip, mapping
                )

        # Assumes something added. The entry is invalid (error raised) if not.
        self._source_ebuilds.add(package.package_info.cpvr)

    def _bundle_with_all_disk(
        self,
        glob: str,
        destdir: Path,
        strip: re.Pattern,
        mapping: subtools_pb2.SubtoolPackage.PathMapping,
    ) -> None:
        """Matches `glob` against all files on disk."""
        for path in Path("/").glob(glob):
            self._copy_into_bundle(path, destdir, strip, mapping)
            self._unmatched_paths.append(str(path))

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

        # Internal consistency checks. When collection of files begins, count of
        # bundled files should be 0, and there should be one unmatched file (the
        # textproto providing the subtool manifest).
        assert self._file_count == 0
        assert len(self._unmatched_paths) == 1

        self._source_ebuilds = set()
        for path in self.package.paths:
            self._bundle_mapping(path)

        self._validate_symlinks()

        logger.notice(
            "%s: Copied %d files.", self.package.name, self._file_count
        )

    def _validate_symlinks(self) -> None:
        """Ensure all installed symlinks resolve inside the bundle directory."""
        for path in self.bundle_dir.glob("**/*"):
            realpath = path.resolve(strict=True)
            if not compat.path_is_relative_to(realpath, self.bundle_dir):
                raise ManifestBundlingError(
                    f"{path} resolves to {realpath}, which is outside of "
                    f"{self.bundle_dir}",
                    self,
                )

    def _match_ebuilds(self) -> None:
        """Match up unmatched paths to the package names that provided them."""
        if self._unmatched_paths:
            logger.notice(
                "%s: Attributing contents to ebuilds. This can take a while...",
                self.package.name,
            )
            ebuilds = portage_util.FindPackageNamesForFiles(
                *self._unmatched_paths
            )
            # Assume all files were matched, and that it is not an error for any
            # file to not be matched to a package.
            self._unmatched_paths = []
            self._source_ebuilds.update(e.cpvr for e in ebuilds)
        if not self._source_ebuilds:
            raise ManifestBundlingError(
                "Bundle cannot be attributed to at least one package.", self
            )
        logger.notice("Contents provided by %s", self.source_packages)

    @functools.cached_property
    def private_packages(self) -> List[str]:
        """List of private ebuilds (as cpvr) used for this subtool."""
        if not self._source_ebuilds or self._unmatched_paths:
            self._match_ebuilds()

        source_ebuilds = list(self._source_ebuilds)
        overlays = portage_util.FindOverlaysForPackages(*source_ebuilds)
        private = set(overlays) - _KNOWN_PUBLIC_OVERLAYS
        ebuilds_idx = [i for i, v in enumerate(overlays) if v in private]
        return [source_ebuilds[i] for i in ebuilds_idx]

    def _validate_cipd_prefix(self) -> None:
        """Raise an error if the cipd_prefix is missing, but required."""
        if self.package.type != subtools_pb2.SubtoolPackage.EXPORT_CIPD:
            return

        if self.package.cipd_prefix:
            return

        if self.private_packages:
            raise ManifestInvalidError(
                "Contents may come from private sources."
                " An explicit `cipd_prefix` must be provided."
                f" ({self.private_packages=})",
                self,
            )

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
        private_only: True if only private packages should be uploaded.
    """

    def __init__(
        self,
        config_dir: Path,
        work_root: Path,
        glob: str = SUBTOOLS_EXPORTS_GLOB,
        private_only: bool = False,
    ) -> None:
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
        self.private_only = private_only

    def bundle_all(self) -> None:
        """Read .textprotos and bundle blobs into `work_root`."""
        self.work_root.mkdir(exist_ok=True)
        for subtool in self.subtools:
            subtool.bundle()

    def prepare_uploads(
        self, upload_filter: Optional[List[str]] = None
    ) -> List[Path]:
        """Read .textprotos and prepares valid bundles in `work_root`.

        Args:
            upload_filter: If provided, only upload subtools with these names.
        """
        prepared_bundles: List[Path] = []
        for subtool in self.subtools:
            if upload_filter and not any(
                fnmatch.fnmatch(subtool.package.name, x) for x in upload_filter
            ):
                logger.notice(
                    "Skip preparing upload for %s, as it matches none of %s.",
                    subtool.package.name,
                    upload_filter,
                )
                continue
            if self.private_only and not subtool.private_packages:
                logger.notice(
                    "Skip preparing upload for %s, as private_only is "
                    "requested and this subtool has no files built from "
                    "private sources.",
                    subtool.package.name,
                )
                continue
            subtool.prepare_upload()
            prepared_bundles.append(subtool.metadata_dir)
        return prepared_bundles


class BundledSubtools:
    """Wraps a list of paths with pre-bundled subtools.

    Attributes:
        bundles: Bundled paths, with the `bundle` file tree and metadata.
        built_packages: Updated with a path when the upload process creates a
            local .zip rather than performing an upload.
        uploaded_package_names: List of subtool names that were successfully
            uploaded.
        uploaded_instances_markdown: List of markdown-formatted strings for each
            package linking to the full URL of the uploaded instance.
    """

    def __init__(self, bundles: List[Path]) -> None:
        """Creates and initializes a BundledSubtools wrapper."""
        self.bundles = bundles
        self.built_packages: List[Path] = []
        self.uploaded_subtool_names: List[str] = []
        self.uploaded_instances_markdown: List[str] = []

    def upload(self, use_production: bool, dryrun: bool = False) -> None:
        """Uploads each valid, bundled subtool.

        Args:
            use_production: Whether to upload to production environments.
            dryrun: Build what would be uploaded, but don't upload it.
        """
        for bundle in self.bundles:
            self._upload_bundle(bundle, use_production, dryrun)

    def _upload_bundle(
        self, path: Path, use_production: bool, dryrun: bool
    ) -> None:
        """Uploads a single bundle."""
        with (path / UPLOAD_METADATA_FILE).open("rb") as fp:
            metadata = UploadMetadata.from_dict(json.load(fp))
        if metadata.cipd_package.package:
            self._upload_bundle_cipd(
                path=path,
                use_production=use_production,
                dryrun=dryrun,
                cipd_package=metadata.cipd_package,
            )
        elif metadata.gcs_metadata:
            bucket_override = None
            if not use_production:
                bucket_override = "chromeos-throw-away-bucket"
            self._upload_bundle_gcs(
                path=path,
                bucket_override=bucket_override,
                dryrun=dryrun,
                gcs_metadata=metadata.gcs_metadata,
            )
        else:
            logger.warning(
                "%s: Metadata not recognized as either CIPD or GCS.  Skipping.",
                path,
            )
            return

    def _upload_bundle_cipd(
        self,
        path: Path,
        use_production: bool,
        dryrun: bool,
        cipd_package: CipdMetadata,
    ) -> None:
        """Uploads a single bundle to CIPD."""
        service_url = None if use_production else cipd.STAGING_SERVICE_URL
        search_tags = cipd_package.tags
        if cipd_package.search_tags:
            search_tags = {k: search_tags[k] for k in cipd_package.search_tags}
        instances = cipd.search_instances(
            CIPD_PATH,
            cipd_package.package,
            search_tags,
            service_url=service_url,
        )
        if instances:
            logger.notice(
                "%s: ebuild and hash match instance %s. Not uploading.",
                cipd_package.package,
                instances,
            )
            # In dry-run, continue to build a package after emitting the notice.
            if not dryrun:
                return

        if dryrun:
            out = path / f"{path.name}.zip"
            cipd.build_package(
                CIPD_PATH,
                cipd_package.package,
                path / "bundle",
                out,
            )
            self.built_packages.append(out)
            return

        # NOTE: This will not create a new instance in CIPD if the hash of the
        # bundle contents matches an existing instance. In that case, CIPD will
        # still add the provided tags to the existing instance.
        cipd.CreatePackage(
            CIPD_PATH,
            cipd_package.package,
            path / "bundle",
            cipd_package.tags,
            cipd_package.refs,
            service_url=service_url,
        )
        (path / ".uploaded").touch()

        _, _, package_shortname = cipd_package.package.rpartition("/")
        origin = service_url or "https://chrome-infra-packages.appspot.com"
        subtools_hash = cipd_package.tags[SUBTOOLS_HASH_TAG]
        url = (
            f"{origin}/p/{cipd_package.package}"
            f"/+/{SUBTOOLS_HASH_TAG}:{subtools_hash}"
        )
        self.uploaded_subtool_names.append(package_shortname)
        self.uploaded_instances_markdown.append(f"[{package_shortname}]({url})")

    def _upload_bundle_gcs(
        self,
        path: Path,
        dryrun: bool,
        gcs_metadata: GcsMetadata,
        bucket_override: Optional[str] = None,
    ) -> None:
        """Uploads a single bundle to GCS."""
        bucket = bucket_override or gcs_metadata.bucket

        url_parts = []
        if gcs_metadata.prefix:
            url_parts.append(gcs_metadata.prefix)
        url_parts.append(gcs_metadata.package_name)
        url_parts.append(gcs_metadata.version)

        extension = _COMPRESSION_EXTENSIONS.get(gcs_metadata.compression)
        if not extension:
            raise ValueError(f"Unknown compression: {gcs_metadata.compression}")

        filename = f"{gcs_metadata.digest}{extension}"
        url_parts.append(filename)

        gs_uri = gs_urls_util.GetGsURL(
            bucket=bucket,
            suburl="/".join(url_parts),
            for_gsutil=True,
        )

        logger.debug("URI for %s: %s", gcs_metadata.package_name, gs_uri)

        context = gs.GSContext()
        if context.Exists(gs_uri):
            logger.notice(
                "%s: Exists in GCS.  Skipping.",
                gs_uri,
            )
            return

        dest_tarball = path / filename
        compression_lib.create_tarball(
            dest_tarball,
            path / "bundle",
            compression=gcs_metadata.compression,
        )

        if dryrun:
            logger.notice(
                "Dry run: would've uploaded %s to %s",
                dest_tarball,
                gs_uri,
            )
        else:
            context.Copy(dest_tarball, gs_uri, acl="public-read")

        http_url = gs_urls_util.GsUrlToHttp(gs_uri, public=False)
        self.uploaded_subtool_names.append(path.name)
        self.uploaded_instances_markdown.append(f"[{path.name}]({http_url})")
