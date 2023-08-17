# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the subtool_lib module."""

import dataclasses
import os
from pathlib import Path
from typing import List, Optional, Tuple, Union
from unittest import mock

from chromite.third_party.google.protobuf import text_format
import pytest

from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import cros_test_lib
from chromite.lib import subtool_lib


def path_mapping(
    inputs: Union[Path, str, None],
    dest: Union[Path, str, None] = None,
    strip_regex: Union[Path, str, None] = None,
    ebuild_filter: Optional[str] = None,
) -> subtools_pb2.SubtoolPackage.PathMapping:
    """Helper to make a PathMapping message from paths."""
    return subtools_pb2.SubtoolPackage.PathMapping(
        input=None if inputs is None else str(inputs),
        dest=None if dest is None else str(dest),
        strip_prefix_regex=None if strip_regex is None else str(strip_regex),
        ebuild_filter=ebuild_filter,
    )


# Placeholder path PathMapping message (a path on the system to bundle).
TEST_PATH_MAPPING = path_mapping("/etc/profile")


@dataclasses.dataclass
class FakeChrootDiskLayout:
    """Entries in the Fake filesystem, rooted at `root`.

    Normally subtools are bundled from entries in the chroot. This dataclass
    helps configure a known disk layout created under a pytest tmp_path.
    """

    root: Path

    globdir = Path("globdir")
    twindir = Path("twindir")
    glob_subdir = globdir / "subdir"
    empty_subdir = globdir / "empty_subdir"

    regular_file = globdir / "regular.file"
    another_file = globdir / "another.file"
    symlink = globdir / "symlink"
    duplicate_file = twindir / "another.file"

    subdir_file = glob_subdir / "subdir.file"
    ebuild_owned_file = glob_subdir / "ebuild_owned.file"

    @staticmethod
    def subtree_file_structure() -> Tuple[cros_test_lib.Directory, ...]:
        """Recursive structure with the regular files and directories."""
        D = cros_test_lib.Directory
        return (
            D("twindir", ("regular.file", "another.file")),
            D(
                "globdir",
                (
                    "regular.file",
                    "another.file",
                    D("empty_subdir", ()),
                    D("subdir", ("ebuild_owned.file", "subdir.file")),
                ),
            ),
        )

    def __getattribute__(self, name) -> Path:
        """Return an absolute Path relative to the current `root`."""
        return object.__getattribute__(self, "root") / object.__getattribute__(
            self, name
        )


def BundleAndExport(subtool: subtool_lib.Subtool) -> None:
    """Helper to perform e2e validation on a manifest."""
    subtool.bundle()
    subtool.export()


def bundle_result(subtool: subtool_lib.Subtool) -> List[str]:
    """Bundles the manifest and returns the contents, sorted, as strings."""
    subtool.bundle()
    contents = [
        str(child.relative_to(subtool.bundle_dir))
        for child in subtool.bundle_dir.rglob("*")
    ]
    contents.sort()
    return contents


class Wrapper:
    """Wraps a "template" proto with helpers to test it.

    Attributes:
        proto: The proto instance to customize before creating a Subtool.
        tmp_path: Temporary path from fixture.
        work_root: Path under tmp_path for bundling.
        fake_rootfs: Path under tmp_path holding a test filesystem tree.
    """

    def __init__(self, tmp_path: Path):
        """Creates a Wrapper using `tmp_path` for work."""
        self.tmp_path = tmp_path
        self.work_root = tmp_path / "work_root"
        self.fake_rootfs = tmp_path / "fake_rootfs"
        self.proto = subtools_pb2.SubtoolPackage(
            name="my_subtool",
            type=subtools_pb2.SubtoolPackage.EXPORT_CIPD,
            max_files=100,
            paths=[TEST_PATH_MAPPING],
        )

    def create(self, writes_files: bool = False) -> subtool_lib.Subtool:
        """Emits the wrapped proto message and creates a Subtool from it."""
        # InstalledSubtools is normally responsible for making the work root.
        if writes_files:
            self.work_root.mkdir()
        return subtool_lib.Subtool(
            text_format.MessageToString(self.proto),
            Path("test_subtool_package.textproto"),
            self.work_root,
        )

    def export_e2e(self, writes_files: bool = False) -> subtool_lib.Subtool:
        """Bundles and exports the Subtool made by `create()`."""
        subtool = self.create(writes_files)
        BundleAndExport(subtool)
        return subtool

    def set_paths(
        self, paths: List[subtools_pb2.SubtoolPackage.PathMapping]
    ) -> None:
        """Helper to set the `paths` field on the proto."""
        # "RepeatedCompositeFieldContainer" does not support item assignment.
        # So `[:] = ...` fails, but it can be cleared with `del`, then extended.
        del self.proto.paths[:]
        self.proto.paths.extend(paths)

    def create_fake_rootfs(self) -> FakeChrootDiskLayout:
        """Creates a variety of test entries in the fake rootfs."""
        cros_test_lib.CreateOnDiskHierarchy(
            self.fake_rootfs, FakeChrootDiskLayout.subtree_file_structure()
        )
        fs = FakeChrootDiskLayout(self.fake_rootfs)
        os.symlink(fs.regular_file, fs.symlink)
        return fs


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


def test_bundle_bundles_single_file(template_proto: Wrapper) -> None:
    """Test that a boring, regular file is bundle when named exactly."""
    fs = template_proto.create_fake_rootfs()
    template_proto.proto.max_files = 1
    template_proto.set_paths([path_mapping(fs.regular_file)])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == ["bin", "bin/regular.file"]


def test_bundle_symlinks_followed(template_proto: Wrapper) -> None:
    """Test that a symlink in "input" is copied as a file, not a symlink."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.symlink)])
    subtool = template_proto.create(writes_files=True)
    bundle_symlink_file = subtool.bundle_dir / "bin" / "symlink"
    assert bundle_result(subtool) == ["bin", "bin/symlink"]
    assert bundle_symlink_file.is_file()
    assert not bundle_symlink_file.is_symlink()
    assert fs.symlink.is_symlink()  # Consistency check.


def test_bundle_multiple_paths(template_proto: Wrapper) -> None:
    """Test multiple path entries."""
    fs = template_proto.create_fake_rootfs()
    template_proto.proto.max_files = 2
    template_proto.set_paths(
        [path_mapping(fs.regular_file), path_mapping(fs.another_file)]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "bin",
        "bin/another.file",
        "bin/regular.file",
    ]


def test_bundle_bundles_glob(template_proto: Wrapper) -> None:
    """Test non-recursive globbing."""
    fs = template_proto.create_fake_rootfs()
    # Validate `max_files` edge case here.
    template_proto.proto.max_files = 2
    template_proto.set_paths([path_mapping(fs.globdir / "*.file")])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "bin",
        "bin/another.file",
        "bin/regular.file",
    ]


def test_bundle_max_file_count(template_proto: Wrapper) -> None:
    """Test max file count exceeded."""
    fs = template_proto.create_fake_rootfs()
    template_proto.proto.max_files = 1
    template_proto.set_paths([path_mapping(fs.globdir / "*.file")])
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        subtool.bundle()
    assert "Max file count (1) exceeded" in str(error_info.value)


def test_bundle_custom_destination(template_proto: Wrapper) -> None:
    """Test a custom destination path (not /bin); multiple components."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths(
        [path_mapping(fs.globdir / "*.file", dest="foo/bar")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "foo",
        "foo/bar",
        "foo/bar/another.file",
        "foo/bar/regular.file",
    ]


def test_bundle_root_destination(template_proto: Wrapper) -> None:
    """Test a custom destination path that is "the root"."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.globdir / "*.file", dest="/")])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "another.file",
        "regular.file",
    ]


def test_bundle_bundles_recursive_glob(template_proto: Wrapper) -> None:
    """Test recursive globbing."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.globdir / "**/*.file")])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "bin",
        "bin/another.file",
        "bin/ebuild_owned.file",
        "bin/regular.file",
        "bin/subdir.file",
    ]


def test_bundle_custom_strip_prefix(template_proto: Wrapper) -> None:
    """Test a custom strip prefix."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths(
        [path_mapping(fs.globdir / "**/*.file", strip_regex=f"^{fs.globdir}")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "bin",
        "bin/another.file",
        "bin/regular.file",
        "bin/subdir",
        "bin/subdir/ebuild_owned.file",
        "bin/subdir/subdir.file",
    ]


def test_bundle_duplicate_files_raises_error(template_proto: Wrapper) -> None:
    """Test that attempting to copy a file twice raises an error."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.root / "**/another.file")])
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        subtool.bundle()
    assert "another.file exists: refusing to copy" in str(error_info.value)


def test_bundle_no_files_raises_error(template_proto: Wrapper) -> None:
    """Test that a paths entry that matches nothing raises an error."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.root / "non-existent.file")])
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        subtool.bundle()
    assert "non-existent.file matched no files" in str(error_info.value)


def test_ebuild_package_not_found_raises_error(template_proto: Wrapper) -> None:
    """Test that an invalid package name raises an error."""
    template_proto.set_paths(
        [path_mapping("/etc/profile", ebuild_filter="invalid-category/foo-bar")]
    )
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        subtool.bundle()
    assert "'invalid-category/foo-bar' must match exactly one package" in str(
        error_info.value
    )


def test_ebuild_multiple_packages_raises_error(template_proto: Wrapper) -> None:
    """Test that queries matching multiple packages raise an error."""
    template_proto.set_paths(
        [path_mapping("/etc/profile", ebuild_filter="binutils")]
    )
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        subtool.bundle()
    assert "'binutils' must match exactly one package" in str(error_info.value)


def test_ebuild_match_real_package(template_proto: Wrapper) -> None:
    """Test that queries can match a real package; single file."""
    template_proto.set_paths(
        [path_mapping("/etc/profile", ebuild_filter="sys-apps/baselayout")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "bin",
        "bin/profile",
    ]


def test_ebuild_not_installed_raises_error(template_proto: Wrapper) -> None:
    """Test that matching a real but uninstalled package raise an error."""
    template_proto.set_paths(
        [path_mapping("/etc/profile", ebuild_filter="baselayout")]
    )
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(
        subtool_lib.ManifestBundlingError
    ) as error_info, mock.patch(
        "chromite.lib.portage_util.PortageDB.GetInstalledPackage"
    ) as mock_get_installed_package:
        mock_get_installed_package.return_value = None
        subtool.bundle()

    assert "Failed to map baselayout=>sys-apps/baselayout" in str(
        error_info.value
    )


def test_ebuild_match_globs_files(template_proto: Wrapper) -> None:
    """Test that queries can match real package contents; glob."""
    template_proto.set_paths(
        # Also cover ebuild_filter + strip_prefix + dest.
        [
            path_mapping(
                "/etc/init.d/*",
                dest="/",
                strip_regex="^.*/etc/",
                ebuild_filter="sys-apps/baselayout",
            )
        ]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "init.d",
        "init.d/functions.sh",
    ]


def test_ebuild_match_recursive_glob(template_proto: Wrapper) -> None:
    """Test that queries can match real package contents; recursive glob."""
    template_proto.set_paths(
        [path_mapping("**/*.conf", dest="/", ebuild_filter="baselayout")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "aliases.conf",
        "i386.conf",
    ]
