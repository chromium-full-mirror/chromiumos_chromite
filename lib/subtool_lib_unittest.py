# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the subtool_lib module."""

from pathlib import Path

from chromite.third_party.google.protobuf import text_format
import pytest

from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import subtool_lib


# Placeholder path PathMapping message (a path on the system to bundle).
TEST_PATH_MAPPING = subtools_pb2.SubtoolPackage.PathMapping(
    input="/etc/profile",
)


def BundleAndExport(subtool: subtool_lib.Subtool) -> None:
    """Helper to perform e2e validation on a manifest."""
    subtool.bundle()
    subtool.export()


class Wrapper:
    """Wraps a "template" proto with helpers to test it.

    Attributes:
        proto: The proto instance to customize before creating a Subtool.
        tmp_path: Temporary path from fixture.
        work_root: Path under tmp_path for bundling.
    """

    def __init__(self, tmp_path: Path):
        """Creates a Wrapper using `tmp_path` for work."""
        self.tmp_path = tmp_path
        self.work_root = tmp_path / "work_root"
        self.proto = subtools_pb2.SubtoolPackage(
            name="my_subtool",
            type=subtools_pb2.SubtoolPackage.EXPORT_CIPD,
            max_files=1,
            paths=[TEST_PATH_MAPPING],
        )

    def create(self) -> subtool_lib.Subtool:
        """Emits the wrapped proto message and creates a Subtool from it."""
        return subtool_lib.Subtool(
            text_format.MessageToString(self.proto),
            Path("test_subtool_package.textproto"),
            self.work_root,
        )

    def export_e2e(self, writes_files: bool = False) -> subtool_lib.Subtool:
        """Bundles and exports the Subtool made by `create()`."""
        # InstalledSubtools is normally responsible for making the work root.
        if writes_files:
            self.work_root.mkdir()
        subtool = self.create()
        BundleAndExport(subtool)
        return subtool


@pytest.fixture(name="template_proto")
def template_proto_fixture(tmp_path) -> Wrapper:
    """Helper to build a test proto with meaningful defaults."""
    return Wrapper(tmp_path)


def test_invalid_textproto() -> None:
    """Test that .textproto files that fail to parse throw an error."""
    # Pass "unused" to flush out cases that may attempt to modify `work_root`.
    subtool = subtool_lib.Subtool(
        "notafield: invalid\n", Path("invalid.txtproto"), Path("/i/am/unused")
    )
    with pytest.raises(subtool_lib.ManifestInvalidError) as error_info:
        BundleAndExport(subtool)
    assert (
        '"chromiumos.build.api.SubtoolPackage" has no field named "notafield"'
        in str(error_info.value)
    )
    assert error_info.value.__cause__.GetLine() == 1
    assert error_info.value.__cause__.GetColumn() == 1


def test_error_on_invalid_name(template_proto: Wrapper) -> None:
    """Test that a manifest with an invalid name throws ManifestInvalidError."""
    template_proto.proto.name = "Invalid"
    with pytest.raises(subtool_lib.ManifestInvalidError) as error_info:
        template_proto.export_e2e()
    assert "Subtool name must match" in str(error_info.value)


def test_error_on_missing_paths(template_proto: Wrapper) -> None:
    """Test that a manifest with no paths throws ManifestInvalidError."""
    del template_proto.proto.paths[:]
    with pytest.raises(subtool_lib.ManifestInvalidError) as error_info:
        template_proto.export_e2e()
    assert "At least one path is required" in str(error_info.value)


def test_loads_all_configs(template_proto: Wrapper) -> None:
    """Test that InstalledSubtools globs protos from `config_dir`."""
    config_dir = template_proto.tmp_path / "config_dir"
    config_dir.mkdir()
    proto_path = config_dir / "test_subtool_package.textproto"
    proto_path.write_text(text_format.MessageToString(template_proto.proto))
    subtools = subtool_lib.InstalledSubtools(
        config_dir, template_proto.work_root
    )
    assert len(subtools.subtools) == 1
    assert subtools.subtools[0].package.name == "my_subtool"


def test_clean_before_bundle(template_proto: Wrapper) -> None:
    """Test that clean doesn't throw errors on an empty work dir."""
    template_proto.create().clean()
    assert not template_proto.work_root.exists()


def test_bundle_and_export(template_proto: Wrapper) -> None:
    """Test that stamp files are created upon a successful end-to-end export."""
    template_proto.export_e2e(writes_files=True)
    assert (template_proto.work_root / "my_subtool" / ".bundled").exists()
    assert (template_proto.work_root / "my_subtool" / ".exported").exists()


def test_clean_after_bundle_and_export(template_proto: Wrapper) -> None:
    """Test that clean cleans, leaving only the root metadata dir."""
    subtool = template_proto.export_e2e(writes_files=True)
    subtool.clean()
    assert template_proto.work_root.exists()
    assert [p.name for p in template_proto.work_root.rglob("**")] == [
        "work_root",
        "my_subtool",
    ]
