# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the subtool_lib module."""

import dataclasses
import json
import os
from pathlib import Path
import re
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union
from unittest import mock

from chromite.third_party.google.protobuf import text_format
import pytest

from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import compression_lib
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import subtool_lib
from chromite.lib import unittest_lib
from chromite.lib.parser import package_info
from chromite.licensing import licenses_lib


def path_mapping(
    glob: Union[Path, str, None],
    dest: Union[Path, str, None] = None,
    strip_regex: Union[Path, str, None] = None,
    ebuild_filter: Optional[str] = None,
) -> subtools_pb2.SubtoolPackage.PathMapping:
    """Helper to make a PathMapping message from paths."""
    return subtools_pb2.SubtoolPackage.PathMapping(
        input=None if glob is None else [str(glob)],
        dest=None if dest is None else str(dest),
        strip_prefix_regex=None if strip_regex is None else str(strip_regex),
        ebuild_filter=ebuild_filter,
    )


# Placeholder path PathMapping message (a path on the system to bundle).
TEST_PATH_MAPPING = path_mapping("/etc/profile")

# Path used in unittests to refer to the cipd executable.
FAKE_CIPD_PATH = "/no_cipd_in_unittests"

# Fake package used when mocking results of `equery belongs`.
FAKE_BELONGS_PACKAGE = "some-category/some-package-0.1-r2"

# Default overlay reported for `equery list` invocations. A real "public"
# overlay is used to avoid tripping private-sources checks.
FAKE_OVERLAY = "amd64-host"

# A proto for a package which should be exported to GCS.
GCS_PACKAGE_PROTO = subtools_pb2.SubtoolPackage(
    name="my_subtool",
    type=subtools_pb2.SubtoolPackage.EXPORT_GCS,
    max_files=100,
    paths=[TEST_PATH_MAPPING],
    gcs_export_options=subtools_pb2.SubtoolPackage.GcsExportOptions(
        bucket="some_bucket",
        prefix="some_prefix",
        # pylint: disable-next=line-too-long
        archive_format=subtools_pb2.SubtoolPackage.GcsExportOptions.ARCHIVE_FORMAT_TAR_ZST,
    ),
)


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

    def __getattribute__(self, name: str) -> Path:
        """Return an absolute Path relative to the current `root`."""
        return object.__getattribute__(self, "root") / object.__getattribute__(
            self, name
        )


def bundle_and_upload(
    subtool: subtool_lib.Subtool, dryrun: bool = False
) -> subtool_lib.BundledSubtools:
    """Helper to perform e2e validation on a manifest."""
    subtool.bundle()
    subtool.prepare_upload()
    uploader = subtool_lib.BundledSubtools([subtool.metadata_dir])
    uploader.upload(use_production=False, dryrun=dryrun)
    return uploader


def bundle_result(
    subtool: subtool_lib.Subtool, has_ebuild_match: bool = False, sed: str = "/"
) -> List[str]:
    """Collects files and returns the contents, sorted, as strings.

    Args:
        subtool: The subtool to bundle.
        has_ebuild_match: Whether inputs can be mapped with equery belongs.
        sed: A sed-like script of the form "pattern/repl" to filter out unstable
            components from path strings (e.g. version numbers or extensions).
    """
    if has_ebuild_match:
        subtool.bundle()
    else:
        # Skip the _match_ebuilds step because for tests that use entries from a
        # fake filesystem that won't map to ebuilds.
        with mock.patch("chromite.lib.subtool_lib.Subtool._match_ebuilds"):
            subtool.bundle()

    pattern, repl = sed.split("/")

    def clean(child: Path) -> str:
        s = str(child.relative_to(subtool.bundle_dir))
        # Decouple from whatever extension licensing uses.
        s = re.sub(r"^license\..*", "<license>", s)
        return re.sub(pattern, repl, s) if pattern else s

    return sorted(clean(x) for x in subtool.bundle_dir.rglob("*"))


def set_run_results(
    run_mock: cros_test_lib.RunCommandMock,
    cipd: Optional[Dict[str, cros_build_lib.CompletedProcess]] = None,
    equery: Optional[Dict[str, cros_build_lib.CompletedProcess]] = None,
) -> None:
    """Set fake results for run calls in the test.

    Args:
        run_mock: The RunCommandMock test fixture.
        cipd: Map of cipd commands and corresponding run results.
        equery: Map of equery commands and corresponding run results.
    """
    cipd_results = cipd or {
        "create": cros_build_lib.CompletedProcess(),
        "search": cros_build_lib.CompletedProcess(),
    }
    equery = equery or {}
    equery_results = {
        "belongs": equery.get(
            "belongs",
            cros_build_lib.CompletedProcess(stdout=f"{FAKE_BELONGS_PACKAGE}\n"),
        ),
        "list": equery.get(
            "list",
            cros_build_lib.CompletedProcess(stdout=f"{FAKE_OVERLAY}\n"),
        ),
    }
    for cmd, result in cipd_results.items():
        run_mock.AddCmdResult(
            partial_mock.InOrder([FAKE_CIPD_PATH, cmd]),
            returncode=result.returncode or 0,
            stdout=result.stdout or "",
        )
    for cmd, result in equery_results.items():
        run_mock.AddCmdResult(
            partial_mock.InOrder(["equery", cmd]),
            returncode=result.returncode or 0,
            stdout=result.stdout or "",
        )


def get_cipd_search_tag_keys(
    run_mock: cros_test_lib.RunCommandMock,
) -> Set[str]:
    """Returns all -tag keys passed to the first `cipd search` invocation."""
    CMD = [FAKE_CIPD_PATH, "search"]
    run_mock.assertCommandContains(CMD)
    cmd_args = [x.args[0] for x in run_mock.call_args_list]
    cmd: List[str] = next((x for x in cmd_args if x[:2] == CMD), [])
    return set(
        x.split(":")[0] for i, x in enumerate(cmd) if i and cmd[i - 1] == "-tag"
    )


class Wrapper:
    """Wraps a "template" proto with helpers to test it.

    Attributes:
        proto: The proto instance to customize before creating a Subtool.
        tmp_path: Temporary path from fixture.
        work_root: Path under tmp_path for bundling.
        fake_rootfs: Path under tmp_path holding a test filesystem tree.
    """

    def __init__(self, tmp_path: Path) -> None:
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

    def write_to_dir(self, config_dir="config_dir") -> Path:
        """Writes the current proto to $name.textproto in tmp/$config_dir."""
        config_path = self.tmp_path / config_dir
        config_path.mkdir(exist_ok=True)
        proto_path = config_path / f"{self.proto.name}.textproto"
        proto_path.write_text(text_format.MessageToString(self.proto))
        return config_path

    def export_e2e(self, writes_files: bool = False) -> subtool_lib.Subtool:
        """Bundles and uploads the Subtool made by `create()`."""
        subtool = self.create(writes_files)
        bundle_and_upload(subtool)
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
        osutils.SafeSymlink("regular.file", fs.symlink)
        return fs

    def load_upload_metadata_json(self) -> Dict:
        """Loads the JSON metadata passed to the upload phase as a dict."""
        with (
            self.work_root / self.proto.name / subtool_lib.UPLOAD_METADATA_FILE
        ).open(mode="rb") as fp:
            return json.load(fp)


@pytest.fixture(autouse=True)
def use_fake_cipd() -> Iterator:
    with mock.patch.object(subtool_lib, "CIPD_PATH", FAKE_CIPD_PATH):
        yield


@pytest.fixture(name="template_proto")
def template_proto_fixture(tmp_path: Path) -> Iterator[Wrapper]:
    """Helper to build a test proto with meaningful defaults."""
    # Skip license generation for the fake some-category/... package. It will
    # match no licenses and raise an exception from licenses_lib.
    with mock.patch.object(
        licenses_lib,
        "SKIPPED_CATEGORIES",
        [FAKE_BELONGS_PACKAGE.split("/", maxsplit=1)[0]],
    ):
        yield Wrapper(tmp_path)


def test_invalid_textproto() -> None:
    """Test that .textproto files that fail to parse throw an error."""
    # Pass "unused" to flush out cases that may attempt to modify `work_root`.
    subtool = subtool_lib.Subtool(
        "notafield: invalid\n", Path("invalid.txtproto"), Path("/i/am/unused")
    )
    with pytest.raises(subtool_lib.ManifestInvalidError) as error_info:
        bundle_and_upload(subtool)
    assert (
        '"chromiumos.build.api.SubtoolPackage" has no field named "notafield"'
        in str(error_info.value)
    )
    assert error_info.value.__cause__.GetLine() == 1
    assert error_info.value.__cause__.GetColumn() == 1


def test_subtool_properties(template_proto: Wrapper) -> None:
    """Test that property values are meaningful."""
    default_subtool = template_proto.create()
    assert (
        default_subtool.bundle_dir
        == template_proto.work_root / "my_subtool" / "bundle"
    )
    assert default_subtool.cipd_package == "chromiumos/infra/tools/my_subtool"
    assert "my_subtool" in default_subtool.summary

    # Test overriding the default CIPD prefix.
    template_proto.proto.cipd_prefix = "elsewhere"
    assert template_proto.create().cipd_package == "elsewhere/my_subtool"
    template_proto.proto.cipd_prefix = "elsewhere/"
    assert template_proto.create().cipd_package == "elsewhere/my_subtool"


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
    config_dir = template_proto.write_to_dir("config_dir")
    subtools = subtool_lib.InstalledSubtools(
        config_dir, template_proto.work_root
    )
    assert len(subtools.subtools) == 1
    assert subtools.subtools[0].package.name == "my_subtool"


def test_clean_before_bundle(template_proto: Wrapper) -> None:
    """Test that clean doesn't throw errors on an empty work dir."""
    template_proto.create().clean()
    assert not template_proto.work_root.exists()


def test_bundle_prepare_upload(template_proto: Wrapper) -> None:
    """Test that preparing for upload creates the expected metadata file."""
    subtool = template_proto.create(writes_files=True)
    subtool.bundle()
    subtool.prepare_upload()
    metadata_dict = template_proto.load_upload_metadata_json()

    cipd_dict = metadata_dict["cipd_package"]
    assert metadata_dict["upload_metadata_version"] >= 1
    # NOTE: If the assertions here need updating due to failures, it probably
    # indicates that upload_metadata_version should be incremented.
    assert cipd_dict["package"] == "chromiumos/infra/tools/my_subtool"
    assert "latest" in cipd_dict["refs"]
    assert cipd_dict["tags"]["builder_source"] == "sdk_subtools"
    assert "ebuild_source" in cipd_dict["tags"]


def test_bundle_and_upload(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that stamp files are created upon a successful end-to-end export."""
    set_run_results(run_mock)
    template_proto.export_e2e(writes_files=True)
    assert (template_proto.work_root / "my_subtool" / ".bundled").exists()
    assert (template_proto.work_root / "my_subtool" / ".uploaded").exists()


@mock.patch.object(
    subtool_lib,
    "MAX_BUNDLE_SIZE_BYTES",
    {subtools_pb2.SubtoolPackage.EXPORT_CIPD: 1},
)
def test_bundle_max_size(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that the maximum size is enforced."""
    set_run_results(run_mock)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert "Bundle is too big." in str(error_info.value)


def test_clean_after_bundle_and_upload(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that clean cleans, leaving only the root metadata dir."""
    set_run_results(run_mock)
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


def test_bundle_symlinks_preserve(template_proto: Wrapper) -> None:
    """Test bundling a basic symlink with SYMLINK_PRESERVE."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths(
        [
            path_mapping(fs.symlink),
            path_mapping(fs.regular_file),
        ]
    )
    template_proto.proto.symlink_mode = (
        subtools_pb2.SubtoolPackage.SYMLINK_PRESERVE
    )
    subtool = template_proto.create(writes_files=True)
    bundle_symlink_file = subtool.bundle_dir / "bin" / "symlink"
    assert bundle_result(subtool) == ["bin", "bin/regular.file", "bin/symlink"]
    assert bundle_symlink_file.is_symlink()
    assert os.readlink(bundle_symlink_file) == "regular.file"


def test_bundle_symlinks_preserve_absolute(template_proto: Wrapper) -> None:
    """Test bundling an absolute symlink fails with SYMLINK_PRESERVE."""
    fs = template_proto.create_fake_rootfs()
    osutils.SafeSymlink("/bin/cat", fs.symlink)
    template_proto.set_paths([path_mapping(fs.symlink)])
    template_proto.proto.symlink_mode = (
        subtools_pb2.SubtoolPackage.SYMLINK_PRESERVE
    )
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError):
        bundle_result(subtool)


def test_bundle_symlinks_preserve_bad(template_proto: Wrapper) -> None:
    """Test bundling a bad symlink fails with SYMLINK_PRESERVE."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.symlink)])
    template_proto.proto.symlink_mode = (
        subtools_pb2.SubtoolPackage.SYMLINK_PRESERVE
    )
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(FileNotFoundError):
        bundle_result(subtool)


def test_bundle_symlinks_preserve_outside_bundle(
    template_proto: Wrapper,
) -> None:
    """Test bundling a symlink out of the bundle fails with SYMLINK_PRESERVE."""
    fs = template_proto.create_fake_rootfs()
    osutils.SafeSymlink("../../..", fs.symlink)
    template_proto.set_paths([path_mapping(fs.symlink)])
    template_proto.proto.symlink_mode = (
        subtools_pb2.SubtoolPackage.SYMLINK_PRESERVE
    )
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError):
        bundle_result(subtool)


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


def test_bundle_plural_inputs(template_proto: Wrapper) -> None:
    """Test a manifest using the list version of `inputs`."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([])
    template_proto.proto.paths.add().input.extend(
        [str(fs.regular_file), str(fs.subdir_file)]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == [
        "bin",
        "bin/regular.file",
        "bin/subdir.file",
    ]


def test_bundle_identical_files_ok(template_proto: Wrapper) -> None:
    """Test copying identical files to the same destination is OK."""
    fs = template_proto.create_fake_rootfs()
    template_proto.set_paths([path_mapping(fs.root / "**/another.file")])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool) == ["bin", "bin/another.file"]


def test_bundle_duplicate_files_raises_error(template_proto: Wrapper) -> None:
    """Test copying differing files to the same destination raises an error."""
    fs = template_proto.create_fake_rootfs()
    fs.duplicate_file.write_text("different\n", encoding="utf-8")
    template_proto.set_paths([path_mapping(fs.root / "**/another.file")])
    subtool = template_proto.create(writes_files=True)
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        subtool.bundle()
    assert "another.file exists and differs: refusing to copy" in str(
        error_info.value
    )


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
    fake_matches = [
        package_info.parse(p)
        for p in ["sys-devel/binutils-2.39-r3", "cross-foo/binutils-0.1"]
    ]
    with pytest.raises(
        subtool_lib.ManifestBundlingError
    ) as error_info, mock.patch(
        "chromite.lib.portage_util.FindPackageNameMatches"
    ) as mock_find_package_name_matches:
        mock_find_package_name_matches.return_value = fake_matches
        subtool.bundle()
    assert "'binutils' must match exactly one package" in str(error_info.value)


def test_ebuild_match_real_package(template_proto: Wrapper) -> None:
    """Test that queries can match a real package; single file."""
    template_proto.set_paths(
        [path_mapping("/etc/profile", ebuild_filter="sys-apps/baselayout")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool, has_ebuild_match=True) == [
        "<license>",
        "bin",
        "bin/profile",
    ]
    assert subtool.source_packages[0].startswith("sys-apps/baselayout-")
    # Verify the license bundling put something meaningful into the license file
    # by looking for sys-apps/baselayout's GPL-2 license preamble.
    contents = compression_lib.decompress_file(
        subtool.bundle_dir / subtool_lib.LICENSE_FILE, True
    ).stdout
    assert b"Gentoo Package Stock License GPL-2" in contents


def test_bundle_idempontence(template_proto: Wrapper) -> None:
    """Ensure generating twice (with licensing) is idempotent."""
    template_proto.set_paths(
        [path_mapping("/etc/profile", ebuild_filter="sys-apps/baselayout")]
    )

    def create_glob_and_concat() -> bytes:
        """Glob and concatenate all files in the bundle."""
        subtool = template_proto.create(writes_files=True)
        assert "<license>" in bundle_result(subtool, has_ebuild_match=True)
        data: List[bytes] = []
        for entry in subtool.bundle_dir.rglob("*"):
            if entry.is_file():
                data.append(entry.read_bytes())
        return b"".join(data)

    first_data = create_glob_and_concat()
    # Move the first work dir out of the way so another can be made.
    template_proto.work_root.rename(template_proto.work_root.parent / ".first")
    second_data = create_glob_and_concat()
    assert first_data == second_data, "Bundle not idempontent."


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
    assert bundle_result(subtool, has_ebuild_match=True) == [
        "<license>",
        "init.d",
        "init.d/functions.sh",
    ]
    assert subtool.source_packages[0].startswith("sys-apps/baselayout-")


@pytest.mark.parametrize(
    ("glob", "expected_files"),
    (
        ("**/*.conf", ["<license>", "aliases.conf", "i386.conf"]),
        (
            "/usr/**",
            ["<license>", "fstab", "group", "issue.devfix", "passwd", "shadow"],
        ),
    ),
)
def test_ebuild_match_recursive_glob(
    glob: str, expected_files: List[str], template_proto: Wrapper
) -> None:
    """Test that queries can match real package contents; recursive glob."""
    template_proto.set_paths(
        [path_mapping(glob, dest="/", ebuild_filter="baselayout")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool, has_ebuild_match=True) == expected_files
    assert subtool.source_packages[0].startswith("sys-apps/baselayout-")


def test_lddtree_bundling(template_proto: Wrapper) -> None:
    """Test that dynamic ELFs are wrapped with lddtree in the bundle."""
    # Verify that both binaries and symlinks to binaries are wrapped with
    # lddtree (bin/foo.elf will be missing if not).
    template_proto.fake_rootfs.mkdir()
    symcat = template_proto.fake_rootfs / "symcat"
    symcat.symlink_to("/bin/cat")
    template_proto.set_paths([path_mapping("/bin/cat"), path_mapping(symcat)])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool, has_ebuild_match=True, sed="[0-9]/#") == [
        "<license>",
        "bin",
        "bin/cat",
        "bin/cat.elf",
        "bin/symcat",
        "bin/symcat.elf",
        "lib",
        "lib/ld-linux-x##-##.so.#",
        "lib/libc.so.#",
    ]
    assert subtool.source_packages[0].startswith("sys-apps/coreutils-")


def test_lddtree_skipped_for_opqaque_data(template_proto: Wrapper) -> None:
    """Test dynamic ELFs are copied as-is if in an opaque_data PathMapping."""
    entry = path_mapping("/bin/cat")
    entry.opaque_data = True
    template_proto.set_paths([entry])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool, has_ebuild_match=True) == [
        "<license>",
        "bin",
        "bin/cat",
    ]


@mock.patch("chromite.lib.subtool_lib.Subtool.prepare_upload")
def test_upload_filter(mock_upload: mock.Mock, template_proto: Wrapper) -> None:
    """Test that InstalledSubtools filters uploads."""
    for name in [f"subtool{i}" for i in range(5)]:
        template_proto.proto.name = name
        config_dir = template_proto.write_to_dir()
    subtools = subtool_lib.InstalledSubtools(
        config_dir, template_proto.work_root
    )
    # Upload all.
    mock_upload.reset_mock()
    subtools.prepare_uploads()
    assert mock_upload.call_count == 5

    # Upload some.
    mock_upload.reset_mock()
    subtools.prepare_uploads(
        upload_filter=["subtool1", "subtool3", "not-a-subtool"],
    )
    assert mock_upload.call_count == 2


@mock.patch.object(subtool_lib.Subtool, "prepare_upload")
def test_upload_filter_glob(
    mock_upload: mock.Mock, template_proto: Wrapper
) -> None:
    """Test that InstalledSubtools with a globbing upload filter."""
    accept_names = [f"subtool-{i}" for i in range(5)]
    reject_names = [f"different-subtool-{i}" for i in range(3)]

    for name in accept_names + reject_names:
        template_proto.proto.name = name
        config_dir = template_proto.write_to_dir()

    subtools = subtool_lib.InstalledSubtools(
        config_dir, template_proto.work_root
    )
    subtools.prepare_uploads(
        upload_filter=["subtool-*"],
    )
    assert mock_upload.call_count == len(accept_names)


def test_upload_successful(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that an upload invokes cipd properly."""
    set_run_results(run_mock)
    subtool = template_proto.export_e2e(writes_files=True)
    # pylint: disable-next=protected-access
    expected_hash = subtool._calculate_digest()
    # Hash should be a 160-bit hex string.
    assert re.fullmatch("[0-9a-f]{40}", expected_hash)
    run_mock.assertCommandContains(
        [
            FAKE_CIPD_PATH,
            "create",
            "-name",
            "chromiumos/infra/tools/my_subtool",
            "-in",
            subtool.bundle_dir,
            "-tag",
            "builder_source:sdk_subtools",
            "-tag",
            "ebuild_source:some-category/some-package-0.1-r2",
            "-tag",
            f"subtools_hash:{expected_hash}",
            "-ref",
            "latest",
            "-service-url",
            "https://chrome-infra-packages-dev.appspot.com",
        ]
    )
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "search"])
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "create"])


def test_upload_skipped_when_instance_found(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test no upload attempt if CIPD search reports matching instance."""
    search_result = "Instances:\n  some/package:instance-hash\n"
    set_run_results(
        run_mock,
        cipd={"search": cros_build_lib.CompletedProcess(stdout=search_result)},
    )
    template_proto.export_e2e(writes_files=True)
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "search"])
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "create"], expected=False)
    assert get_cipd_search_tag_keys(run_mock) == set(
        ("builder_source", "ebuild_source", "subtools_hash")
    )


def test_search_excludes_hash_with_revision_only(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test search excludes subtools_hash with CHANGE_REVISION_ONLY."""
    set_run_results(run_mock)
    template_proto.proto.upload_trigger = (
        subtools_pb2.SubtoolPackage.CHANGE_REVISION_ONLY
    )
    template_proto.export_e2e(writes_files=True)
    assert get_cipd_search_tag_keys(run_mock) == set(
        ("builder_source", "ebuild_source")
    )


def test_upload_dryrun_builds_package(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test upload with dryrun skips "create" and reports package built."""
    set_run_results(run_mock)
    uploader = bundle_and_upload(
        template_proto.create(writes_files=True), dryrun=True
    )
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "search"])
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "create"], expected=False)
    run_mock.assertCommandContains([FAKE_CIPD_PATH, "pkg-build"])
    assert uploader.built_packages == [
        Path(template_proto.work_root / "my_subtool" / "my_subtool.zip")
    ]
    assert not uploader.uploaded_subtool_names
    assert not uploader.uploaded_instances_markdown


def test_upload_reports_summary(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test upload includes summary of upload results."""
    set_run_results(run_mock)
    uploader = bundle_and_upload(template_proto.create(writes_files=True))
    assert not uploader.built_packages
    assert uploader.uploaded_subtool_names == ["my_subtool"]
    assert len(uploader.uploaded_instances_markdown) == 1
    assert uploader.uploaded_instances_markdown[0].startswith(
        "[my_subtool](https://chrome-infra-packages-dev.appspot.com/"
        "p/chromiumos/infra/tools/my_subtool/+/subtools_hash:"
    )


def test_upload_fails_cipd(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that a CIPD create failure propagates an exception."""
    set_run_results(
        run_mock, cipd={"create": cros_build_lib.CompletedProcess(returncode=1)}
    )
    with pytest.raises(cros_build_lib.RunCommandError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert f"command: {FAKE_CIPD_PATH} create" in str(error_info.value)


def test_export_checks_textproto_ebuild(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that the .textproto path is queried for belongs when not bundled."""
    set_run_results(run_mock)
    template_proto.export_e2e(writes_files=True)
    run_mock.assertCommandContains(
        ["equery", "belongs", "test_subtool_package.textproto", "/etc/profile"]
    )


def test_export_multiple_ebuilds(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test when bundle contents correspond to multiple ebuilds."""
    # Use the "fake" some-category/ packages to skip attempts to find licenses.
    fake_belongs_package2 = "some-category/other-pkg-0.1-r3"
    set_run_results(
        run_mock,
        equery={
            "belongs": cros_build_lib.CompletedProcess(
                stdout=f"{FAKE_BELONGS_PACKAGE}\n{fake_belongs_package2}\n"
            ),
            "list": cros_build_lib.CompletedProcess(
                stdout=f"{FAKE_OVERLAY}\n{FAKE_OVERLAY}\n"
            ),
        },
    )
    template_proto.export_e2e(writes_files=True)
    metadata_dict = template_proto.load_upload_metadata_json()
    cipd_tags = metadata_dict["cipd_package"]["tags"]
    assert (
        cipd_tags["ebuild_source"]
        == "some-category/other-pkg-0.1-r3,some-category/some-package-0.1-r2"
    )


def test_export_no_ebuilds(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test when no bundle contents can be matched to an ebuild."""
    set_run_results(
        run_mock,
        equery={"belongs": cros_build_lib.CompletedProcess(returncode=1)},
    )
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert "Bundle cannot be attributed" in str(error_info.value)


def test_private_ebuild_no_prefix(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test error raised if contents match an ebuild from a private overlay."""
    set_run_results(
        run_mock,
        equery={"list": cros_build_lib.CompletedProcess(stdout="chromeos\n")},
    )
    with pytest.raises(subtool_lib.ManifestInvalidError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert "Contents may come from private sources" in str(error_info.value)


def test_private_ebuild_with_explicit_prefix(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test private contents accepted if explicit cipd_prefix given."""
    set_run_results(
        run_mock,
        equery={"list": cros_build_lib.CompletedProcess(stdout="chromeos\n")},
    )
    template_proto.proto.cipd_prefix = "foo_internal"
    template_proto.export_e2e(writes_files=True)
    metadata_dict = template_proto.load_upload_metadata_json()
    assert metadata_dict["cipd_package"]["package"] == "foo_internal/my_subtool"


def test_upload_skips_empty_metadata(tmp_path: Path, caplog) -> None:
    """Ensure uploading quietly skips a path with empty metadata."""
    # It's currently an error for an "unbundled" path to be provided to
    # BundledSubtools: the json file must exist. But the upload logic must be
    # robust to "old" metadata. That's tested here by testing an empty, but
    # valid, JSON file.
    (tmp_path / subtool_lib.UPLOAD_METADATA_FILE).write_bytes(b"{}")
    subtool_lib.BundledSubtools([tmp_path]).upload(False)
    assert (
        "Metadata not recognized as either CIPD or GCS.  Skipping."
        in caplog.text
    )


def test_extract_hash_from_elf(tmp_path: Path) -> None:
    """Test a build ID can be extracted from an elf file."""
    abc = tmp_path / "abc"
    unittest_lib.BuildELF(
        str(abc), build_id="0xaaaaaaaa11111111bbbbbbbb22222222cccccccc"
    )
    file_type = subtool_lib.Subtool.get_file_type(abc)
    assert file_type == "binary/elf/dynamic-so"
    assert (
        subtool_lib.extract_hash(abc, file_type)
        == "aaaaaaaa11111111bbbbbbbb22222222cccccccc"
    )


def test_extract_hash_from_data(tmp_path: Path) -> None:
    """Test a build ID can be extracted from a non-elf file."""
    abc = tmp_path / "abc"
    abc.write_text("hashme")
    file_type = subtool_lib.Subtool.get_file_type(abc)
    assert file_type == "text/oneline"
    assert (
        subtool_lib.extract_hash(abc, file_type)
        == "fb78992e561929a6967d5328f49413fa99048d06"
    )


def test_gs_url(tmp_path: Path) -> None:
    """Test getting the URL for a EXPORT_GCS package."""
    subtool = subtool_lib.Subtool(
        message=text_format.MessageToString(GCS_PACKAGE_PROTO),
        path=tmp_path / "my_subtool.proto",
        work_root=tmp_path,
    )
    assert subtool.url == (
        "https://storage.cloud.google.com/some_bucket/some_prefix/my_subtool"
    )


def test_gcs_prepare_upload(tmp_path: Path) -> None:
    """Test prepare_upload() for a EXPORT_GCS package."""
    subtool = subtool_lib.Subtool(
        message=text_format.MessageToString(GCS_PACKAGE_PROTO),
        path=tmp_path / "my_subtool.proto",
        work_root=tmp_path,
    )
    subtool.bundle()
    with mock.patch.object(
        portage_util,
        "FindPackageNamesForFiles",
        return_value=[package_info.parse("cat/pkg-1.2.3-r4")],
    ):
        subtool.prepare_upload()
    metadata_contents = (
        subtool.metadata_dir / subtool_lib.UPLOAD_METADATA_FILE
    ).read_text(encoding="utf-8")
    metadata = subtool_lib.UploadMetadata.from_dict(
        json.loads(metadata_contents)
    )
    assert metadata.gcs_metadata.package_name == "my_subtool"
    assert metadata.gcs_metadata.version == "1.2.3-r4"
    assert (
        metadata.gcs_metadata.compression
        == compression_lib.CompressionType.ZSTD
    )


@pytest.mark.parametrize(
    ["exists", "dryrun"],
    [
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ],
)
def test_gcs_bundle_and_upload(
    tmp_path: Path, exists: bool, dryrun: bool
) -> None:
    """End-to-end test bundling and uploading a GCS_EXPORT package."""
    subtool = subtool_lib.Subtool(
        message=text_format.MessageToString(GCS_PACKAGE_PROTO),
        path=tmp_path / "my_subtool.proto",
        work_root=tmp_path,
    )

    subtool.bundle()

    with mock.patch.object(
        portage_util,
        "FindPackageNamesForFiles",
        return_value=[package_info.parse("cat/pkg-1.2.3-r4")],
    ):
        subtool.prepare_upload()

    uploader = subtool_lib.BundledSubtools([subtool.metadata_dir])

    with mock.patch.object(
        gs.GSContext, "Exists", return_value=exists
    ), mock.patch.object(gs.GSContext, "Copy") as copy:
        uploader.upload(use_production=False, dryrun=dryrun)
        if dryrun or exists:
            copy.assert_not_called()
        else:
            copy.assert_called_once()
