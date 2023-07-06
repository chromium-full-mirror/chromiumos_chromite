# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods for reading and building manifests exported by the subtools builder.

Loads and interprets subtools export manifests defined by the proto at
https://crsrc.org/o/src/config/proto/chromiumos/build/api/subtools.proto
"""

from pathlib import Path
import re
from typing import Literal, Optional

from chromite.third_party.google import protobuf
from chromite.third_party.google.protobuf import text_format

from chromite import ChromiteLogger
from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import osutils


logger = ChromiteLogger.getLogger(__name__)


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

# Valid names. A stricter version of `packageNameRe` in
# https://crsrc.org/i/go/src/go.chromium.org/luci/cipd/common/common.go
# Diallows slashes and starting with a ".".
_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9_\-]+[a-z0-9_\-\.]*$")


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

    def stamp(self, kind: Literal["bundled", "exported"]) -> Path:
        """Returns the path to a "stamp" file that tracks export progress."""
        return self.metadata_dir / f".{kind}"

    def clean(self):
        """Resets export progress and removes the temporary bundle tree."""
        self.stamp("bundled").unlink(missing_ok=True)
        self.stamp("exported").unlink(missing_ok=True)
        osutils.RmDir(self.bundle_dir, ignore_missing=True)

    def bundle(self):
        """Collect and bundle files described in `package` in the work dir."""
        self._validate()
        self.clean()
        self.metadata_dir.mkdir(exist_ok=True)
        self.bundle_dir.mkdir()
        logger.notice(
            "Bundling subtool '%s' under %s", self.package.name, self.bundle_dir
        )
        logger.info(self)
        # TODO(b/277992359): Actually copy files and bundle them.
        self.stamp("bundled").touch()

    def export(self):
        """Export the bundle, e.g., to cipd."""
        self._validate()
        if not self.stamp("bundled").exists():
            raise ManifestBundlingError("Bundling incomplete.", self)
        # TODO(b/277992359): Actually export something.
        self.stamp("exported").touch()

    def _validate(self):
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

    def export_all(self) -> None:
        """Read .textprotos and export valid bundles in `work_root`."""
        for subtool in self.subtools:
            subtool.export()
