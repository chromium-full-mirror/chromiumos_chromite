# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the subtool_lib module."""

import dataclasses
import os
from pathlib import Path
import re
from typing import Dict, Iterator, List, Optional, Tuple, Union
from unittest import mock

from chromite.third_party.google.protobuf import text_format
import pytest

from chromite.api.gen.chromiumos.build.api import subtools_pb2
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock
from chromite.lib import subtool_lib
from chromite.licensing import licenses_lib


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

# Path used in unittests to refer to the cipd executable.
FAKE_CIPD_PATH = "/no_cipd_in_unittests"

# Fake package used when mocking results of `equery belongs`.
FAKE_BELONGS_PACKAGE = "some-category/some-package-0.1-r2"


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


def bundle_and_export(subtool: subtool_lib.Subtool) -> None:
    """Helper to perform e2e validation on a manifest."""
    subtool.bundle()
    subtool.export(use_production=False, cipd_path=FAKE_CIPD_PATH)


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
        return re.sub(pattern, repl, s) if pattern else s

    return sorted(clean(x) for x in subtool.bundle_dir.rglob("*"))


def set_run_results(
    run_mock: cros_test_lib.RunCommandMock,
    cipd: Optional[Dict[str, int]] = None,
    equery: Optional[Dict[str, str]] = None,
) -> None:
    """Set fake results for run calls in the test.

    Args:
        run_mock: The RunCommandMock test fixture.
        cipd: Map of cipd commands and the process return code.
        equery: Map of equery commands and the standard output.
    """
    cipd_results = cipd or {"create": 0}
    equery_stdout = equery or {"belongs": f"{FAKE_BELONGS_PACKAGE}\n"}
    for cmd, result in cipd_results.items():
        run_mock.AddCmdResult(
            partial_mock.InOrder([FAKE_CIPD_PATH, cmd]), returncode=result
        )
    for cmd, stdout in equery_stdout.items():
        run_mock.AddCmdResult(
            partial_mock.InOrder(["equery", cmd]),
            returncode=0 if stdout else 1,
            stdout=stdout,
        )


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

    def write_to_dir(self, config_dir="config_dir") -> Path:
        """Writes the current proto to $name.textproto in tmp/$config_dir."""
        config_path = self.tmp_path / config_dir
        config_path.mkdir(exist_ok=True)
        proto_path = config_path / f"{self.proto.name}.textproto"
        proto_path.write_text(text_format.MessageToString(self.proto))
        return config_path

    def export_e2e(self, writes_files: bool = False) -> subtool_lib.Subtool:
        """Bundles and exports the Subtool made by `create()`."""
        subtool = self.create(writes_files)
        bundle_and_export(subtool)
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
        bundle_and_export(subtool)
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


def test_bundle_and_export(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that stamp files are created upon a successful end-to-end export."""
    set_run_results(run_mock)
    template_proto.export_e2e(writes_files=True)
    assert (template_proto.work_root / "my_subtool" / ".bundled").exists()
    assert (template_proto.work_root / "my_subtool" / ".exported").exists()


def test_clean_after_bundle_and_export(
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
    assert bundle_result(subtool, has_ebuild_match=True) == [
        "bin",
        "bin/profile",
        str(subtool_lib.LICENSE_FILE),
    ]
    assert subtool.source_packages[0].startswith("sys-apps/baselayout-")
    # Verify the license bundling put something meaningful into the license file
    # by looking for sys-apps/baselayout's GPL-2 license preamble.
    contents = cros_build_lib.UncompressFile(
        subtool.bundle_dir / subtool_lib.LICENSE_FILE, True
    ).stdout
    assert b"Gentoo Package Stock License GPL-2" in contents


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
        "init.d",
        "init.d/functions.sh",
        str(subtool_lib.LICENSE_FILE),
    ]
    assert subtool.source_packages[0].startswith("sys-apps/baselayout-")


def test_ebuild_match_recursive_glob(template_proto: Wrapper) -> None:
    """Test that queries can match real package contents; recursive glob."""
    template_proto.set_paths(
        [path_mapping("**/*.conf", dest="/", ebuild_filter="baselayout")]
    )
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool, has_ebuild_match=True) == [
        "aliases.conf",
        "i386.conf",
        str(subtool_lib.LICENSE_FILE),
    ]
    assert subtool.source_packages[0].startswith("sys-apps/baselayout-")


def test_lddtree_bundling(template_proto: Wrapper) -> None:
    """Test that dynamic ELFs are wrapped with lddtree in the bundle."""
    template_proto.set_paths([path_mapping("/bin/cat")])
    subtool = template_proto.create(writes_files=True)
    assert bundle_result(subtool, has_ebuild_match=True, sed="[0-9]/#") == [
        "bin",
        "bin/cat",
        "bin/cat.elf",
        "lib",
        "lib/ld-linux-x##-##.so.#",
        "lib/libc.so.#",
        str(subtool_lib.LICENSE_FILE),
    ]
    assert subtool.source_packages[0].startswith("sys-apps/coreutils-")


@mock.patch("chromite.lib.subtool_lib.Subtool.export")
def test_export_filter(mock_export: mock.Mock, template_proto: Wrapper) -> None:
    """Test that InstalledSubtools filters exports."""
    for name in [f"subtool{i}" for i in range(5)]:
        template_proto.proto.name = name
        config_dir = template_proto.write_to_dir()
    subtools = subtool_lib.InstalledSubtools(
        config_dir, template_proto.work_root
    )
    # Export nothing.
    subtools.export(use_production=False, export_filter=[])
    assert mock_export.call_count == 0

    # Export all.
    mock_export.reset_mock()
    subtools.export(use_production=False)
    assert mock_export.call_count == 5

    # Export some.
    mock_export.reset_mock()
    subtools.export(
        use_production=False,
        export_filter=["subtool1", "subtool3", "not-a-subtool"],
    )
    assert mock_export.call_count == 2


def test_export_successful(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that an export invokes cipd properly."""
    set_run_results(run_mock)
    subtool = template_proto.export_e2e(writes_files=True)
    run_mock.assertCommandCalled(
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
            "-ref",
            "latest",
            "-service-url",
            "https://chrome-infra-packages-dev.appspot.com",
        ],
        capture_output=True,
    )


def test_export_fails_cipd(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that a CIPD create failure propagates an exception."""
    set_run_results(run_mock, cipd={"create": 1})
    with pytest.raises(cros_build_lib.RunCommandError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert f"command: {FAKE_CIPD_PATH} create" in str(error_info.value)


def test_export_no_ebuilds(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test when bundle contents correspond to multiple ebuilds."""
    set_run_results(run_mock, equery={"belongs": "a/b-0.1\nc/d-0.2-r3\n"})
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert "Bundle cannot be attributed" in str(error_info.value)
    assert "Candidates: ['a/b-0.1', 'c/d-0.2-r3']" in str(error_info.value)


def test_export_too_many_ebuilds(
    template_proto: Wrapper, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test when no bundle contents can be matched to an ebuild."""
    set_run_results(run_mock, equery={"belongs": ""})
    with pytest.raises(subtool_lib.ManifestBundlingError) as error_info:
        template_proto.export_e2e(writes_files=True)
    assert "Bundle cannot be attributed" in str(error_info.value)
    assert "Candidates: []" in str(error_info.value)
