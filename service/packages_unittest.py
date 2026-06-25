# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Packages service tests."""

import io
import json
import os
from pathlib import Path
import re
import shutil
from unittest import mock

import pytest

import chromite as cr
from chromite.lib import build_target_lib
from chromite.lib import chromeos_version
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import dependency_graph
from chromite.lib import depgraph
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import parallel_unittest
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import uprev_lib
from chromite.lib.parser import package_info
from chromite.service import android
from chromite.service import dependency
from chromite.service import packages


D = cros_test_lib.Directory
F = cros_test_lib.File


class UprevAndroidTest(cros_test_lib.RunCommandTestCase):
    """Uprev android tests."""

    def setUp(self) -> None:
        self.PatchObject(constants, "SOURCE_ROOT", new="[SOURCE_ROOT]")

    def _mock_successful_uprev(self) -> None:
        self.rc.AddCmdResult(
            partial_mock.In(
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable"
            ),
            stdout=(
                '{"revved": true,'
                ' "android_atom": "android/android-1.0",'
                ' "modified_files": ["file1", "file2"]}'
            ),
        )

    def test_success(self) -> None:
        """Test successful run handling."""
        self._mock_successful_uprev()
        build_targets = [
            build_target_lib.BuildTarget(t) for t in ["foo", "bar"]
        ]

        result = packages.uprev_android(
            "android/package", chroot_lib.Chroot(), build_targets=build_targets
        )
        self.assertCommandContains(
            [
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable",
                "--android_package=android/package",
                "--boards=foo bar",
            ]
        )
        self.assertCommandContains(["emerge-foo"])
        self.assertCommandContains(["emerge-bar"])

        self.assertTrue(result.revved)
        self.assertEqual(result.android_atom, "android/android-1.0")
        self.assertListEqual(result.modified_files, ["file1", "file2"])

    def test_android_build_branch(self) -> None:
        """Test specifying android_build_branch option."""
        self._mock_successful_uprev()

        packages.uprev_android(
            "android/package",
            chroot_lib.Chroot(),
            android_build_branch="android-build-branch",
        )
        self.assertCommandContains(
            [
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable",
                "--android_package=android/package",
                "--android_build_branch=android-build-branch",
            ]
        )

    def test_android_version(self) -> None:
        """Test specifying android_version option."""
        self._mock_successful_uprev()

        packages.uprev_android(
            "android/package", chroot_lib.Chroot(), android_version="7123456"
        )
        self.assertCommandContains(
            [
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable",
                "--android_package=android/package",
                "--force_version=7123456",
            ]
        )

    def test_skip_commit(self) -> None:
        """Test specifying skip_commit option."""
        self._mock_successful_uprev()

        packages.uprev_android(
            "android/package", chroot_lib.Chroot(), skip_commit=True
        )
        self.assertCommandContains(
            [
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable",
                "--android_package=android/package",
                "--skip_commit",
            ]
        )

    def test_no_uprev(self) -> None:
        """Test no uprev handling."""
        self.rc.AddCmdResult(
            partial_mock.In(
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable"
            ),
            stdout='{"revved": false}',
        )
        build_targets = [
            build_target_lib.BuildTarget(t) for t in ["foo", "bar"]
        ]
        result = packages.uprev_android(
            "android/package", chroot_lib.Chroot(), build_targets=build_targets
        )

        self.assertCommandContains(
            [
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable",
                "--boards=foo bar",
            ]
        )
        self.assertCommandContains(["emerge-foo"], expected=False)
        self.assertCommandContains(["emerge-bar"], expected=False)

        self.assertFalse(result.revved)

    def test_ignore_junk_in_stdout(self) -> None:
        """Test when stdout contains junk messages."""
        self.rc.AddCmdResult(
            partial_mock.In(
                "[SOURCE_ROOT]/chromite/bin/cros_mark_android_as_stable"
            ),
            stdout='foo\nbar\n{"revved": false}\n',
        )
        result = packages.uprev_android("android/package", chroot_lib.Chroot())

        self.assertFalse(result.revved)


class UprevAndroidLKGBTest(cros_test_lib.MockTestCase):
    """Tests for uprevving Android with LKGB."""

    def test_registered_handlers(self) -> None:
        """Test that each Android package has an uprev handler registered."""
        mock_handler = self.PatchObject(packages, "uprev_android_lkgb")

        for android_package in android.GetAllAndroidPackages():
            cpv = package_info.SplitCPV(
                "chromeos-base/" + android_package, strict=False
            )
            build_targets = [build_target_lib.BuildTarget("foo")]
            chroot = chroot_lib.Chroot()

            packages.uprev_versioned_package(cpv, build_targets, [], chroot)

            mock_handler.assert_called_once_with(
                android_package, build_targets, chroot
            )
            mock_handler.reset_mock()

    def test_success(self) -> None:
        """Test a successful uprev."""
        self.PatchObject(android, "OVERLAY_DIR", new="overlay-dir")
        self.PatchObject(
            android, "ReadLKGB", return_value={"build_id": "android-lkgb"}
        )
        self.PatchObject(
            packages,
            "uprev_android",
            return_value=packages.UprevAndroidResult(
                revved=True,
                android_atom="android-atom",
                modified_files=["file1", "file2"],
            ),
        )

        result = packages.uprev_android_lkgb(
            "android-package", [], chroot_lib.Chroot()
        )

        self.assertListEqual(
            result.modified,
            [
                uprev_lib.UprevVersionedModifications(
                    "android-lkgb",
                    [
                        os.path.join("overlay-dir", "file1"),
                        os.path.join("overlay-dir", "file2"),
                    ],
                )
            ],
        )

    def test_no_rev(self) -> None:
        """Test when nothing revved."""
        self.PatchObject(
            android, "ReadLKGB", return_value={"build_id": "android-lkgb"}
        )
        self.PatchObject(
            packages,
            "uprev_android",
            return_value=packages.UprevAndroidResult(revved=False),
        )

        result = packages.uprev_android_lkgb(
            "android-package", [], chroot_lib.Chroot()
        )

        self.assertListEqual(result.modified, [])


class UprevECUtilsTest(cros_test_lib.MockTestCase):
    """Tests for upreving ecutils."""

    def test_success(self) -> None:
        """Test a successful uprev."""

        def fakeRunTasks(func, inputs):
            results = []
            for args in inputs:
                results.append(func(*args))
            return results

        self.PatchObject(
            packages.uprev_lib.parallel,
            "RunTasksInProcessPool",
            side_effect=fakeRunTasks,
        )
        mock_devutils = mock.MagicMock(name="dev-utils")
        mock_ecutils = mock.MagicMock(name="ec-utils")
        mock_ecutilstest = mock.MagicMock(name="ec-utils-test")
        self.PatchObject(
            packages.uprev_lib.portage_util,
            "GetOverlayEBuilds",
            return_value=[
                mock_devutils,
                mock_ecutils,
                mock_ecutilstest,
            ],
        )
        mock_overlay_mgr = mock.MagicMock(name="overlay-manager")
        mock_overlay_mgr.modified_ebuilds = ["file1", "file2"]
        self.PatchObject(
            packages.uprev_lib,
            "UprevOverlayManager",
            return_value=mock_overlay_mgr,
        )

        for package in [
            "chromeos-base/ec-devutils",
            "chromeos-base/ec-utils",
            "chromeos-base/ec-utils-test",
        ]:
            cpv = package_info.SplitCPV(package, strict=False)
            assert cpv is not None
            build_targets = [build_target_lib.BuildTarget("foo")]
            refs = [
                uprev_lib.GitRef(
                    path="/platform/ec",
                    ref="main",
                    revision="123",
                )
            ]
            chroot = chroot_lib.Chroot()

            result = packages.uprev_versioned_package(
                cpv, build_targets, refs, chroot
            )

            self.assertEqual(1, len(result.modified))
            self.assertEqual("123", result.modified[0].new_version)
            self.assertListEqual(result.modified[0].files, ["file1", "file2"])

            mock_overlay_mgr.uprev.assert_called_with(
                package_list=[
                    package,
                ],
                force=True,
            )


class UprevBuildTargetsTest(cros_test_lib.RunCommandTestCase):
    """uprev_build_targets tests."""

    def test_invalid_type_fails(self) -> None:
        """Test invalid type fails."""
        with self.assertRaises(AssertionError):
            packages.uprev_build_targets(
                [build_target_lib.BuildTarget("foo")], "invalid"
            )

    def test_none_type_fails(self) -> None:
        """Test None type fails."""
        with self.assertRaises(AssertionError):
            packages.uprev_build_targets(
                [build_target_lib.BuildTarget("foo")], None
            )


class PatchEbuildVarsTest(cros_test_lib.MockTestCase):
    """patch_ebuild_vars test."""

    def setUp(self) -> None:
        self.mock_input = self.PatchObject(packages.fileinput, "input")
        self.mock_stdout_write = self.PatchObject(packages.sys.stdout, "write")
        self.ebuild_path = "/path/to/ebuild"
        self.old_var_value = "R100-5678.0.123456789"
        self.new_var_value = "R102-5678.0.234566789"

    def test_patch_ebuild_vars_var_only(self) -> None:
        """patch_ebuild_vars changes ^var=value$."""
        ebuild_contents = (
            "This line does not change.\n"
            'AFDO_PROFILE_VERSION="{var_value}"\n'
            "\n"
            "# The line with AFDO_PROFILE_VERSION is also unchanged."
        )
        # Ebuild contains old_var_value.
        self.mock_input.return_value = io.StringIO(
            ebuild_contents.format(var_value=self.old_var_value)
        )
        expected_calls = []
        # Expect the line with new_var_value.
        for line in io.StringIO(
            ebuild_contents.format(var_value=self.new_var_value)
        ):
            expected_calls.append(mock.call(line))

        packages.patch_ebuild_vars(
            self.ebuild_path, {"AFDO_PROFILE_VERSION": self.new_var_value}
        )

        self.mock_stdout_write.assert_has_calls(expected_calls)

    def test_patch_ebuild_vars_ignore_export(self) -> None:
        """patch_ebuild_vars changes ^export var=value$ and keeps export."""
        ebuild_contents = (
            "This line does not change.\n"
            'export AFDO_PROFILE_VERSION="{var_value}"\n'
            "# This line is also unchanged."
        )
        # Ebuild contains old_var_value.
        self.mock_input.return_value = io.StringIO(
            ebuild_contents.format(var_value=self.old_var_value)
        )
        expected_calls = []
        # Expect the line with new_var_value.
        for line in io.StringIO(
            ebuild_contents.format(var_value=self.new_var_value)
        ):
            expected_calls.append(mock.call(line))

        packages.patch_ebuild_vars(
            self.ebuild_path, {"AFDO_PROFILE_VERSION": self.new_var_value}
        )

        self.mock_stdout_write.assert_has_calls(expected_calls)

    def test_patch_ebuild_vars_partial_match(self) -> None:
        """patch_ebuild_vars ignores ^{prefix}var=value$."""
        ebuild_contents = (
            'This and the line below do not change.\nNEW_AFDO="{var_value}"'
        )
        # Ebuild contains old_var_value.
        self.mock_input.return_value = io.StringIO(
            ebuild_contents.format(var_value=self.old_var_value)
        )
        expected_calls = []
        # Expect the line with UNCHANGED old_var_value.
        for line in io.StringIO(
            ebuild_contents.format(var_value=self.old_var_value)
        ):
            expected_calls.append(mock.call(line))

        # Note that the var name partially matches the ebuild var and hence it
        # has to be ignored.
        packages.patch_ebuild_vars(
            self.ebuild_path, {"AFDO": self.new_var_value}
        )

        self.mock_stdout_write.assert_has_calls(expected_calls)

    def test_patch_ebuild_vars_no_vars(self) -> None:
        """patch_ebuild_vars keeps ebuild intact if there are no vars."""
        ebuild_contents = (
            "This line does not change.\n"
            "The line with AFDO_PROFILE_VERSION is also unchanged."
        )
        self.mock_input.return_value = io.StringIO(ebuild_contents)
        expected_calls = []
        for line in io.StringIO(ebuild_contents):
            expected_calls.append(mock.call(line))

        packages.patch_ebuild_vars(
            self.ebuild_path, {"AFDO_PROFILE_VERSION": self.new_var_value}
        )

        self.mock_stdout_write.assert_has_calls(expected_calls)


class UprevsVersionedPackageTest(cros_test_lib.MockTestCase):
    """uprevs_versioned_package decorator test."""

    @packages.uprevs_versioned_package("category/package")
    def uprev_category_package(self, *args, **kwargs) -> None:
        """Registered function for testing."""

    def test_calls_function(self) -> None:
        """Test calling a registered function."""
        self.PatchObject(self, "uprev_category_package")

        cpv = package_info.SplitCPV("category/package", strict=False)
        packages.uprev_versioned_package(cpv, [], [], chroot_lib.Chroot())

        # TODO(crbug/1065172): Invalid assertion that was previously mocked.
        # patch.assert_called()

    def test_unregistered_package(self) -> None:
        """Test calling with an unregistered package."""
        cpv = package_info.SplitCPV("does-not/exist", strict=False)

        with self.assertRaises(packages.UnknownPackageError):
            packages.uprev_versioned_package(cpv, [], [], chroot_lib.Chroot())


class UprevEbuildFromPinTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests uprev_ebuild_from_pin function"""

    package = "category/package"
    version = "1.2.3"
    new_version = "1.2.4"
    ebuild_template = "package-%s-r1.ebuild"
    ebuild = ebuild_template % version
    unstable_ebuild = "package-9999.ebuild"
    manifest = "Manifest"

    def test_uprev_ebuild(self) -> None:
        """Tests uprev of ebuild with version path"""
        file_layout = (
            D(self.package, [self.ebuild, self.unstable_ebuild, self.manifest]),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        package_path = os.path.join(self.tempdir, self.package)

        ebuild_path = os.path.join(package_path, self.ebuild)
        self.WriteTempFile(ebuild_path, 'KEYWORDS="*"\n')

        result = uprev_lib.uprev_ebuild_from_pin(
            package_path, self.new_version, chroot=chroot_lib.Chroot()
        )
        self.assertEqual(
            len(result.modified),
            1,
            "unexpected number of results: %s" % len(result.modified),
        )

        mod = result.modified[0]
        self.assertEqual(
            mod.new_version,
            self.new_version + "-r1",
            "unexpected version number: %s" % mod.new_version,
        )

        old_ebuild_path = os.path.join(
            package_path, self.ebuild_template % self.version
        )
        new_ebuild_path = os.path.join(
            package_path, self.ebuild_template % self.new_version
        )
        manifest_path = os.path.join(package_path, "Manifest")

        expected_modified_files = [
            old_ebuild_path,
            new_ebuild_path,
            manifest_path,
        ]
        self.assertCountEqual(mod.files, expected_modified_files)

        self.assertCommandContains(["ebuild", "manifest"])

    def test_uprev_ebuild_same_version(self) -> None:
        """Tests uprev of ebuild with version path with unchanged version.

        This should result in bumping the revision number.
        """
        file_layout = (
            D(self.package, [self.ebuild, self.unstable_ebuild, self.manifest]),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        package_path = os.path.join(self.tempdir, self.package)

        ebuild_path = os.path.join(package_path, self.ebuild)
        self.WriteTempFile(ebuild_path, 'KEYWORDS="*"\n')

        result = uprev_lib.uprev_ebuild_from_pin(
            package_path, self.version, chroot=chroot_lib.Chroot()
        )
        self.assertEqual(
            len(result.modified),
            1,
            "unexpected number of results: %s" % len(result.modified),
        )

        mod = result.modified[0]
        self.assertEqual(
            mod.new_version,
            self.version + "-r2",
            "unexpected version number: %s" % mod.new_version,
        )

        old_ebuild_path = os.path.join(
            package_path, self.ebuild_template % self.version
        )
        new_ebuild_path = os.path.join(
            package_path, "package-%s-r2.ebuild" % self.version
        )
        manifest_path = os.path.join(package_path, "Manifest")

        expected_modified_files = [
            old_ebuild_path,
            new_ebuild_path,
            manifest_path,
        ]
        self.assertCountEqual(mod.files, expected_modified_files)

        self.assertCommandContains(["ebuild", "manifest"])

    def test_no_ebuild(self) -> None:
        """Tests assertion is raised if package has no ebuilds"""
        file_layout = (D(self.package, [self.manifest]),)
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        package_path = os.path.join(self.tempdir, self.package)

        with self.assertRaises(uprev_lib.EbuildUprevError):
            uprev_lib.uprev_ebuild_from_pin(
                package_path, self.new_version, chroot=chroot_lib.Chroot()
            )

    def test_multiple_stable_ebuilds(self) -> None:
        """Tests assertion is raised if multiple stable ebuilds are present"""
        file_layout = (
            D(
                self.package,
                [self.ebuild, self.ebuild_template % "1.2.1", self.manifest],
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        package_path = os.path.join(self.tempdir, self.package)

        ebuild_path = os.path.join(package_path, self.ebuild)
        self.WriteTempFile(ebuild_path, 'KEYWORDS="*"\n')

        ebuild_path = os.path.join(package_path, self.ebuild_template % "1.2.1")
        self.WriteTempFile(ebuild_path, 'KEYWORDS="*"\n')

        with self.assertRaises(uprev_lib.EbuildUprevError):
            uprev_lib.uprev_ebuild_from_pin(
                package_path, self.new_version, chroot=chroot_lib.Chroot()
            )

    def test_multiple_unstable_ebuilds(self) -> None:
        """Tests assertion is raised if multiple unstable ebuilds are present"""
        file_layout = (
            D(
                self.package,
                [self.ebuild, self.ebuild_template % "1.2.1", self.manifest],
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        package_path = os.path.join(self.tempdir, self.package)

        with self.assertRaises(uprev_lib.EbuildUprevError):
            uprev_lib.uprev_ebuild_from_pin(
                package_path, self.new_version, chroot=chroot_lib.Chroot()
            )


class GetBestVisibleTest(cros_test_lib.MockTestCase):
    """get_best_visible tests."""

    def test_empty_atom_fails(self) -> None:
        """Test empty atom raises an error."""
        with self.assertRaises(AssertionError):
            packages.get_best_visible("")


class HasPrebuiltTest(cros_test_lib.MockTestCase):
    """has_prebuilt tests."""

    def test_empty_atom_fails(self) -> None:
        """Test an empty atom results in an error."""
        with self.assertRaises(AssertionError):
            packages.has_prebuilt("")

    def test_use_flags(self) -> None:
        """Test use flags get propagated correctly."""
        # We don't really care about the result, just the env handling.
        patch = self.PatchObject(portage_util, "HasPrebuilt", return_value=True)
        # Ignore any flags that may be in the environment.
        self.PatchObject(os.environ, "get", return_value="")

        packages.has_prebuilt("cat/pkg-1.2.3", useflags="useflag")
        patch.assert_called_with(
            "cat/pkg-1.2.3", board=None, extra_env={"USE": "useflag"}
        )

    def test_env_use_flags(self) -> None:
        """Test env use flags get propagated correctly with passed useflags."""
        # We don't really care about the result, just the env handling.
        patch = self.PatchObject(portage_util, "HasPrebuilt", return_value=True)
        # Add some flags to the environment.
        existing_flags = "already set flags"
        self.PatchObject(os.environ, "get", return_value=existing_flags)

        new_flags = "useflag"
        packages.has_prebuilt("cat/pkg-1.2.3", useflags=new_flags)
        expected = "%s %s" % (existing_flags, new_flags)
        patch.assert_called_with(
            "cat/pkg-1.2.3", board=None, extra_env={"USE": expected}
        )


class AndroidVersionsTest(cros_test_lib.MockTestCase):
    """Tests getting android versions."""

    def setUp(self) -> None:
        package_result = [
            "chromeos-base/android-vm-tm-4717008-r1",
            "chromeos-base/update_engine-0.0.3-r3408",
        ]
        self.PatchObject(
            portage_util, "GetPackageDependencies", return_value=package_result
        )
        self.board = "board"
        self.PatchObject(
            portage_util,
            "FindEbuildForBoardPackage",
            return_value="chromeos-base/android-vm-tm",
        )
        FakeEnvironment = {
            "ARM64_TARGET": "3-linux-target",
        }
        self.PatchObject(
            osutils, "SourceEnvironment", return_value=FakeEnvironment
        )

        # Clear the LRU cache for the function. We mock the function that
        # provides the data this function processes to produce its result, so we
        # need to clear it manually.
        packages.determine_android_package.cache_clear()

    def test_determine_android_version(self) -> None:
        """Tests that a valid android version is returned."""
        version = packages.determine_android_version(self.board)
        self.assertEqual(version, "4717008")

    def test_determine_android_version_when_not_present(self) -> None:
        """Test None is returned for version when android is not present."""
        package_result = ["chromeos-base/update_engine-0.0.3-r3408"]
        self.PatchObject(
            portage_util, "GetPackageDependencies", return_value=package_result
        )
        version = packages.determine_android_version(self.board)
        self.assertEqual(version, None)

    def test_determine_android_branch(self) -> None:
        """Tests that a valid android branch is returned."""
        branch = packages.determine_android_branch(self.board)
        self.assertEqual(branch, "3")

    def test_determine_android_branch_64bit_targets(self) -> None:
        """Tests a valid android branch is returned with only 64bit targets."""
        self.PatchObject(
            osutils,
            "SourceEnvironment",
            return_value={"ARM64_TARGET": "3-linux-target"},
        )
        branch = packages.determine_android_branch(self.board)
        self.assertEqual(branch, "3")

    def test_determine_android_branch_when_not_present(self) -> None:
        """Tests a None is returned for branch when android is not present."""
        package_result = ["chromeos-base/update_engine-0.0.3-r3408"]
        self.PatchObject(
            portage_util, "GetPackageDependencies", return_value=package_result
        )
        branch = packages.determine_android_branch(self.board)
        self.assertEqual(branch, None)

    def test_determine_android_target(self) -> None:
        """Tests that a valid android target is returned."""
        target = packages.determine_android_target(self.board)
        self.assertEqual(target, "bertha")

    def test_determine_android_target_when_not_present(self) -> None:
        """Tests a None is returned for target when android is not present."""
        package_result = ["chromeos-base/update_engine-0.0.3-r3408"]
        self.PatchObject(
            portage_util, "GetPackageDependencies", return_value=package_result
        )
        target = packages.determine_android_target(self.board)
        self.assertEqual(target, None)

    def test_determine_android_version_handle_exception(self) -> None:
        """Tests handling RunCommandError inside determine_android_version."""
        # Mock what happens when portage returns that bubbles up (via
        # RunCommand) inside portage_util.GetPackageDependencies.
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            side_effect=cros_build_lib.RunCommandError("error"),
        )
        target = packages.determine_android_version(self.board)
        self.assertEqual(target, None)

    def test_determine_android_package_handle_exception(self) -> None:
        """Tests handling RunCommandError inside determine_android_package."""
        # Mock what happens when portage returns that bubbles up (via
        # RunCommand) inside portage_util.GetPackageDependencies.
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            side_effect=cros_build_lib.RunCommandError("error"),
        )
        target = packages.determine_android_package(self.board)
        self.assertEqual(target, None)

    def test_determine_android_package_callers_handle_exception(self) -> None:
        """Tests RunCommandError caught by determine_android_package callers."""
        # Mock what happens when portage returns that bubbles up (via
        # RunCommand) inside portage_util.GetPackageDependencies.
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            side_effect=cros_build_lib.RunCommandError("error"),
        )
        # Verify that target is None, as expected.
        target = packages.determine_android_package(self.board)
        self.assertEqual(target, None)
        # determine_android_branch calls determine_android_package
        branch = packages.determine_android_branch(self.board)
        self.assertEqual(branch, None)
        # determine_android_target calls determine_android_package
        target = packages.determine_android_target(self.board)
        self.assertEqual(target, None)


@pytest.mark.usefixtures("testcase_caplog", "testcase_monkeypatch")
class FindFingerprintsTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for find_fingerprints."""

    def setUp(self) -> None:
        self.board = "test-board"
        # Create cheets-fingerprints.txt based on tempdir/src...
        self.fingerprint_contents = (
            "google/test-board/test-board_cheets"
            ":9/R99-12345.0.9999/123456:user/release-keys"
        )
        fingerprint_path = os.path.join(
            self.tempdir,
            "src/build/images/test-board/latest/cheets-fingerprint.txt",
        )
        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot", out_path=self.tempdir / "out"
        )
        osutils.WriteFile(
            fingerprint_path, self.fingerprint_contents, makedirs=True
        )

    def test_find_fingerprints_with_test_path(self) -> None:
        """Tests get_firmware_versions with mocked output."""
        self.monkeypatch.setattr(constants, "SOURCE_ROOT", self.tempdir)
        build_target = build_target_lib.BuildTarget(self.board)
        result = packages.find_fingerprints(build_target)
        self.assertEqual(result, [self.fingerprint_contents])
        self.assertIn("Reading fingerprint file", self.caplog.text)

    def test_find_fingerprints(self) -> None:
        """Tests get_firmware_versions with mocked output."""
        # Use board name whose path for fingerprint file does not exist.
        # Verify that fingerprint file is not found and None is returned.
        build_target = build_target_lib.BuildTarget("wrong-boardname")
        self.monkeypatch.setattr(constants, "SOURCE_ROOT", self.tempdir)
        result = packages.find_fingerprints(build_target)
        self.assertEqual(result, [])
        self.assertIn("Fingerprint file not found", self.caplog.text)


class GetAllFirmwareVersionsTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for get_firmware_versions."""

    def setUp(self) -> None:
        self.board = "test-board"
        # This is the result of running
        # "/build/hana/usr/sbin/chromeos-firmwareupdate --manifest" inside the
        # CrOS SDK on 2025-04-30.
        #
        # pylint: disable=line-too-long
        self.rc.SetDefaultCmdResult(
            stdout="""{
  "birch": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hana": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hanawl": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hanawl-PHOEBE": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hanawl-PROWISE": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "maple": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "maple14": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "sycamore": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "sycamore360": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "telesu": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  }
}
"""
        )
        # pylint: enable=line-too-long

    def test_get_firmware_versions(self) -> None:
        """Tests get_firmware_versions with mocked output."""
        build_target = build_target_lib.BuildTarget(self.board)
        result = packages.get_all_firmware_versions(build_target)

        self.assertEqual(len(result), 10)
        self.assertEqual(
            result["birch"],
            packages.FirmwareVersions(
                "birch",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["hana"],
            packages.FirmwareVersions(
                "hana",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["hanawl"],
            packages.FirmwareVersions(
                "hanawl",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["hanawl-PHOEBE"],
            packages.FirmwareVersions(
                "hanawl-PHOEBE",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["hanawl-PROWISE"],
            packages.FirmwareVersions(
                "hanawl-PROWISE",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["maple"],
            packages.FirmwareVersions(
                "maple",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["maple14"],
            packages.FirmwareVersions(
                "maple14",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["sycamore"],
            packages.FirmwareVersions(
                "sycamore",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["sycamore360"],
            packages.FirmwareVersions(
                "sycamore360",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )
        self.assertEqual(
            result["telesu"],
            packages.FirmwareVersions(
                "telesu",
                "Google_Hana.8438.206.0",
                "Google_Hana.8438.235.0",
                "hana_v1.1.4824-d58e50539",
                "hana_v1.1.4825-1473136d99",
            ),
        )

    def test_get_firmware_versions_error(self) -> None:
        """Tests get_firmware_versions with no output."""
        # Throw an exception when running the command.
        self.rc.SetDefaultCmdResult(returncode=1)
        build_target = build_target_lib.BuildTarget(self.board)
        result = packages.get_all_firmware_versions(build_target)
        self.assertEqual(result, {})


class GetFirmwareVersionsTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for get_firmware_versions."""

    def setUp(self) -> None:
        self.board = "test-board"
        # This is the result of running
        # "/build/hana/usr/sbin/chromeos-firmwareupdate --manifest" inside the
        # CrOS SDK on 2025-04-30.
        #
        # pylint: disable=line-too-long
        self.rc.SetDefaultCmdResult(
            stdout="""{
  "birch": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hana": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hanawl": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hanawl-PHOEBE": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "hanawl-PROWISE": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "maple": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "maple14": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "sycamore": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "sycamore360": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  },
  "telesu": {
    "host": {
      "versions": {
        "ro": "Google_Hana.8438.206.0",
        "rw": "Google_Hana.8438.235.0"
      },
      "keys": { "root": "b11d74edd286c144e1135b49e7f0bc20cf041f10", "recovery": "c14bd720b70d97394257e3e826bd8f43de48d4ed" },
      "image": "images/bios-hana.ro-8438-206-0.rw-8438-235-0.bin"
    },
    "ec": {
      "versions": {
        "ro": "hana_v1.1.4824-d58e50539",
        "rw": "hana_v1.1.4825-1473136d99"
      },
      "image": "images/ec-hana.ro-8438-206-0.rw-8438-235-0.bin"
    }
  }
}
"""
        )
        # pylint: enable=line-too-long

    def test_get_firmware_versions(self) -> None:
        """Tests get_firmware_versions with mocked output."""
        build_target = build_target_lib.BuildTarget(self.board)
        result = packages.get_firmware_versions(build_target)
        versions = packages.FirmwareVersions(
            "birch",
            "Google_Hana.8438.206.0",
            "Google_Hana.8438.235.0",
            "hana_v1.1.4824-d58e50539",
            "hana_v1.1.4825-1473136d99",
        )
        self.assertEqual(result, versions)


class DetermineKernelVersionTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for determine_kernel_version."""

    def setUp(self) -> None:
        self.board = "test-board"
        self.build_target = build_target_lib.BuildTarget(self.board)

    def test_determine_kernel_version(self) -> None:
        """Tests that a valid kernel version is returned."""
        kernel_candidates = [
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
            "sys-kernel/socfpga-kernel-4.20-r34",
        ]
        self.PatchObject(
            portage_util,
            "GetFlattenedDepsForPackage",
            return_value=kernel_candidates,
        )

        installed_pkgs = [
            "sys-kernel/linux-firmware-0.0.1-r594",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "virtual/linux-sources-1-r30",
        ]
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            return_value=installed_pkgs,
        )

        result = packages.determine_kernel_version(self.build_target)
        self.assertEqual(result, "4.4.223-r2209")

    def test_determine_kernel_version_ignores_exact_duplicates(self) -> None:
        """Tests that multiple results for candidates is ignored."""
        # Depgraph is evaluated for version as well as revision, so graph will
        # return all results twice.
        kernel_candidates = [
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
            "sys-kernel/socfpga-kernel-4.20-r34",
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
            "sys-kernel/socfpga-kernel-4.20-r34",
        ]
        self.PatchObject(
            portage_util,
            "GetFlattenedDepsForPackage",
            return_value=kernel_candidates,
        )

        installed_pkgs = [
            "sys-kernel/linux-firmware-0.0.1-r594",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "virtual/linux-sources-1-r30",
        ]
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            return_value=installed_pkgs,
        )

        result = packages.determine_kernel_version(self.build_target)
        self.assertEqual(result, "4.4.223-r2209")

    def test_determine_kernel_version_ignores_virtual_package(self) -> None:
        """Tests that top-level package is ignored as potential kernel pkg."""
        # Depgraph results include the named package at level 0 as well as its
        # first-order dependencies, so verify that the virtual package is not
        # included as a kernel package.
        kernel_candidates = [
            "virtual/linux-sources-1",
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
            "sys-kernel/socfpga-kernel-4.20-r34",
            "virtual/linux-sources-1-r30",
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
            "sys-kernel/socfpga-kernel-4.20-r34",
        ]
        self.PatchObject(
            portage_util,
            "GetFlattenedDepsForPackage",
            return_value=kernel_candidates,
        )

        installed_pkgs = [
            "sys-kernel/linux-firmware-0.0.1-r594",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "virtual/linux-sources-1-r30",
        ]
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            return_value=installed_pkgs,
        )

        result = packages.determine_kernel_version(self.build_target)
        self.assertEqual(result, "4.4.223-r2209")

    def test_determine_kernel_version_too_many(self) -> None:
        """Tests that an exception is thrown with too many matching packages."""
        package_result = [
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
            "sys-kernel/socfpga-kernel-4.20-r34",
        ]
        self.PatchObject(
            portage_util,
            "GetFlattenedDepsForPackage",
            return_value=package_result,
        )

        installed_pkgs = [
            "sys-kernel/linux-firmware-0.0.1-r594",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "virtual/linux-sources-1-r30",
        ]
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            return_value=installed_pkgs,
        )

        with self.assertRaises(packages.KernelVersionError):
            packages.determine_kernel_version(self.build_target)

    def test_determine_kernel_version_no_kernel_match(self) -> None:
        """Tests that an exception is thrown with 0-sized intersection."""
        package_result = [
            "sys-kernel/chromeos-kernel-experimental-4.18_rc2-r23",
            "sys-kernel/chromeos-kernel-4_4-4.4.223-r2209",
            "sys-kernel/chromeos-kernel-5_15-5.15.65-r869",
            "sys-kernel/upstream-kernel-next-9999",
        ]
        self.PatchObject(
            portage_util,
            "GetFlattenedDepsForPackage",
            return_value=package_result,
        )

        installed_pkgs = [
            "sys-kernel/linux-firmware-0.0.1-r594",
            "sys-kernel/socfpga-kernel-4.20-r34",
            "virtual/linux-sources-1-r30",
        ]
        self.PatchObject(
            portage_util,
            "GetPackageDependencies",
            return_value=installed_pkgs,
        )

        with self.assertRaises(packages.KernelVersionError):
            packages.determine_kernel_version(self.build_target)

    def test_determine_kernel_version_exception(self) -> None:
        """Tests that portage_util exceptions result in returning empty str."""
        self.PatchObject(
            portage_util,
            "GetFlattenedDepsForPackage",
            side_effect=cros_build_lib.RunCommandError("error"),
        )
        result = packages.determine_kernel_version(self.build_target)
        self.assertEqual(result, "")


class ChromeVersionsTest(cros_test_lib.MockTestCase):
    """Tests getting chrome version."""

    def setUp(self) -> None:
        self.build_target = build_target_lib.BuildTarget("board")

    def test_determine_chrome_version(self) -> None:
        """Tests that a valid chrome version is returned."""
        # Mock PortageqBestVisible to return a valid chrome version string.
        r1_cpf = "chromeos-base/chromeos-chrome-78.0.3900.0_rc-r1"
        pkg_info = package_info.parse(r1_cpf)
        self.PatchObject(
            portage_util, "PortageqBestVisible", return_value=pkg_info
        )
        self.PatchObject(
            portage_util,
            "FindEbuildForBoardPackage",
            return_value=f"/path/to/{r1_cpf}.ebuild",
        )
        self.PatchObject(
            osutils,
            "SourceEnvironment",
            return_value={"GIT_COMMIT": "deadbeef"},
        )

        chrome_version, variables = packages.determine_package_version(
            constants.CHROME_CP,
            self.build_target,
            ["GIT_COMMIT"],
        )
        version_numbers = chrome_version.split(".")
        self.assertEqual(len(version_numbers), 4)
        self.assertEqual(int(version_numbers[0]), 78)
        self.assertEqual(variables["GIT_COMMIT"], "deadbeef")

    def test_determine_chrome_version_handle_exception(self) -> None:
        # Mock what happens when portage throws an exception that bubbles up
        # (via RunCommand)inside portage_util.PortageqBestVisible.
        self.PatchObject(
            portage_util,
            "PortageqBestVisible",
            side_effect=cros_build_lib.RunCommandError("error"),
        )
        target = packages.determine_package_version(
            constants.CHROME_CP, self.build_target
        )
        self.assertEqual(target, None)


class PlatformVersionsTest(cros_test_lib.MockTestCase):
    """Tests getting platform version."""

    def test_determine_platform_version(self) -> None:
        """Test checking that a valid platform version is returned."""
        platform_version = packages.determine_platform_version()
        # The returned platform version is something like 12603.0.0.
        version_string_list = platform_version.split(".")
        self.assertEqual(len(version_string_list), 3)
        # We don't want to check an exact version, but the first number should
        # be non-zero.
        self.assertGreaterEqual(int(version_string_list[0]), 1)

    def test_determine_milestone_version(self) -> None:
        """Test checking that a valid milestone version is returned."""
        milestone_version = packages.determine_milestone_version()
        # Milestone version should be non-zero
        self.assertGreaterEqual(int(milestone_version), 1)

    def test_determine_full_version(self) -> None:
        """Test checking that a valid full version is returned."""
        full_version = packages.determine_full_version()
        pattern = r"^R(\d+)-(\d+.\d+.\d+(-rc\d+)*)"
        m = re.match(pattern, full_version)
        self.assertTrue(m)
        milestone_version = m.group(1)
        self.assertGreaterEqual(int(milestone_version), 1)

    def test_versions_based_on_mock(self) -> None:
        # Create a test version_info object, and then mock VersionInfo.from_repo
        # return it.
        test_platform_version = "12575.0.0"
        test_chrome_branch = "75"
        version_info_mock = chromeos_version.VersionInfo(test_platform_version)
        version_info_mock.chrome_branch = test_chrome_branch
        self.PatchObject(
            chromeos_version.VersionInfo,
            "from_repo",
            return_value=version_info_mock,
        )
        test_full_version = (
            "R" + test_chrome_branch + "-" + test_platform_version
        )
        platform_version = packages.determine_platform_version()
        milestone_version = packages.determine_milestone_version()
        full_version = packages.determine_full_version()
        self.assertEqual(platform_version, test_platform_version)
        self.assertEqual(milestone_version, test_chrome_branch)
        self.assertEqual(full_version, test_full_version)


# Each of the columns in the following table is a separate dimension along
# which Chrome uprev test cases can vary in behavior. The full test space would
# be the Cartesian product of the possible values of each column.
# 'CHROME_EBUILD' refers to the relationship between the version of the existing
# Chrome ebuild vs. the requested uprev version. 'FOLLOWER_EBUILDS' refers to
# the same relationship but for the packages defined in OTHER_CHROME_PACKAGES.
# 'EBUILDS MODIFIED' refers to whether any of the existing 9999 ebuilds have
# modified contents relative to their corresponding stable ebuilds.
#
# CHROME_EBUILD            FOLLOWER_EBUILDS           EBUILDS_MODIFIED
#
# HIGHER                   HIGHER                     YES
# SAME                     SAME                       NO
# LOWER                    LOWER
#                          DOESN'T EXIST YET

# These test cases cover both CHROME & FOLLOWER ebuilds being identically
# higher, lower, or the same versions, with no modified ebuilds.
UPREV_VERSION_CASES = (
    # Uprev.
    pytest.param(
        "80.0.8080.0",
        "81.0.8181.0",
        # One added and one deleted for chrome and each "other" package.
        2 * (1 + len(constants.OTHER_CHROME_PACKAGES)),
        False,
        id="newer_chrome_version",
    ),
    # Revbump.
    pytest.param(
        "80.0.8080.0",
        "80.0.8080.0",
        2,
        True,
        id="chrome_revbump",
    ),
    # No files should be changed in these cases.
    pytest.param(
        "80.0.8080.0",
        "80.0.8080.0",
        0,
        False,
        id="same_chrome_version",
    ),
    pytest.param(
        "80.0.8080.0",
        "79.0.7979.0",
        0,
        False,
        id="older_chrome_version",
    ),
)


@pytest.mark.parametrize(
    "old_version, new_version, expected_count, modify_unstable",
    UPREV_VERSION_CASES,
)
def test_uprev_chrome_all_files_already_exist(
    old_version,
    new_version,
    expected_count,
    modify_unstable,
    monkeypatch,
    overlay_stack,
) -> None:
    """Test Chrome uprevs work as expected when all packages already exist."""
    (overlay,) = overlay_stack(1)
    monkeypatch.setattr(uprev_lib, "_CHROME_OVERLAY_PATH", overlay.path)

    unstable_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="9999", keywords="~*"
    )
    if modify_unstable:
        # Add some field not set in stable.
        unstable_chrome.depend = "foo/bar"

    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version=f"{old_version}_rc-r1",
        GIT_COMMIT=f"{old_version}_commit",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    for pkg_str in constants.OTHER_CHROME_PACKAGES:
        category, pkg_name = pkg_str.split("/")
        unstable_pkg = cr.test.Package(
            category, pkg_name, version="9999", keywords="~*"
        )
        stable_pkg = cr.test.Package(
            category,
            pkg_name,
            version=f"{old_version}_rc-r1",
            GIT_COMMIT=f"{old_version}_commit",
        )

        overlay.add_package(unstable_pkg)
        overlay.add_package(stable_pkg)

    git_refs = [
        uprev_lib.GitRef(
            path="/foo",
            ref=f"refs/tags/{new_version}",
            revision=f"{new_version}_commit",
        )
    ]
    res = packages.uprev_chrome_from_ref(None, git_refs, None)

    modified_file_count = sum(len(m.files) for m in res.modified)
    assert modified_file_count == expected_count


@pytest.mark.usefixtures("testcase_monkeypatch")
class GetModelsTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for get_models."""

    def setUp(self) -> None:
        self.board = "test-board"
        self.rc.SetDefaultCmdResult(stdout="pyro\nreef\nsnappy\n")
        self.monkeypatch.setattr(constants, "SOURCE_ROOT", self.tempdir)
        build_bin = os.path.join(
            self.tempdir, constants.DEFAULT_CHROOT_DIR, "usr", "bin"
        )
        osutils.Touch(
            os.path.join(build_bin, "cros_config_host"), makedirs=True
        )

    def testGetModels(self) -> None:
        """Test get_models."""
        build_target = build_target_lib.BuildTarget(self.board)
        result = packages.get_models(build_target)
        self.assertEqual(result, ["pyro", "reef", "snappy"])


class GetKeyIdTest(cros_test_lib.MockTestCase):
    """Tests for get_key_id."""

    def setUp(self) -> None:
        self.board = "test-board"
        self.build_target = build_target_lib.BuildTarget(self.board)

    def testGetKeyId(self) -> None:
        """Test get_key_id when _run_cros_config_host returns a key."""
        self.PatchObject(
            packages, "_run_cros_config_host", return_value=["key"]
        )
        result = packages.get_key_id(self.build_target, "model")
        self.assertEqual(result, "key")

    def testGetKeyIdNoKey(self) -> None:
        """Test get_key_id when None should be returned."""
        self.PatchObject(
            packages, "_run_cros_config_host", return_value=["key1", "key2"]
        )
        result = packages.get_key_id(self.build_target, "model")
        self.assertEqual(result, None)


class GetLatestVersionTest(cros_test_lib.TestCase):
    """Tests for get_latest_version_from_refs."""

    def setUp(self) -> None:
        self.prefix = "refs/tags/drivefs_"
        # The tag ref template.
        ref_tpl = self.prefix + "%s"

        self.latest = "44.0.20"
        self.versions = ["42.0.1", self.latest, "44.0.19", "39.0.15"]
        self.latest_ref = uprev_lib.GitRef(
            "/path", ref_tpl % self.latest, "abc123"
        )
        self.refs = [
            uprev_lib.GitRef("/path", ref_tpl % v, "abc123")
            for v in self.versions
        ]

    def test_single_ref(self) -> None:
        """Test a single ref is supplied."""
        # pylint: disable=protected-access
        self.assertEqual(
            self.latest,
            packages._get_latest_version_from_refs(
                self.prefix, [self.latest_ref]
            ),
        )

    def test_multiple_ref_versions(self) -> None:
        """Test multiple refs supplied."""
        # pylint: disable=protected-access
        self.assertEqual(
            self.latest,
            packages._get_latest_version_from_refs(self.prefix, self.refs),
        )

    def test_no_refs_returns_none(self) -> None:
        """Test no refs supplied."""
        # pylint: disable=protected-access
        self.assertEqual(
            packages._get_latest_version_from_refs(self.prefix, []), None
        )

    def test_ref_prefix(self) -> None:
        """Test refs with a different prefix isn't used"""
        # pylint: disable=protected-access
        # Add refs/tags/foo_100.0.0 to the refs, which should be ignored in
        # _get_latest_version_from_refs because the prefix doesn't match, even
        # if its version number is larger.
        refs = self.refs + [
            uprev_lib.GitRef("/path", "refs/tags/foo_100.0.0", "abc123")
        ]
        self.assertEqual(
            self.latest,
            packages._get_latest_version_from_refs(self.prefix, refs),
        )


class NeedsChromeSourceTest(cros_test_lib.MockTestCase):
    """Tests for needs_chrome_source."""

    def _build_graph(self, with_chrome: bool, with_followers: bool):
        root = "/build/build_target"
        foo_bar = package_info.parse("foo/bar-1")
        chrome = package_info.parse(f"{constants.CHROME_CP}-1.2.3.4")
        followers = [
            package_info.parse(f"{pkg}-1.2.3.4")
            for pkg in constants.OTHER_CHROME_PACKAGES
        ]
        nodes = [dependency_graph.PackageNode(foo_bar, root)]
        root_pkgs = ["foo/bar-1"]
        if with_chrome:
            nodes.append(dependency_graph.PackageNode(chrome, root))
            root_pkgs.append(chrome.cpvr)
        if with_followers:
            nodes.extend(
                [dependency_graph.PackageNode(f, root) for f in followers]
            )
            root_pkgs.extend([f.cpvr for f in followers])

        return dependency_graph.DependencyGraph(nodes, root, root_pkgs)

    def test_needs_all(self) -> None:
        """Verify we need source when we have no prebuilts."""
        graph = self._build_graph(with_chrome=True, with_followers=True)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=False)
        self.PatchObject(
            packages,
            "uprev_chrome",
            return_value=uprev_lib.UprevVersionedResult(),
        )

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target)

        self.assertTrue(result.needs_chrome_source)
        self.assertTrue(result.builds_chrome)
        self.assertTrue(result.packages)
        self.assertEqual(
            len(result.packages), len(constants.OTHER_CHROME_PACKAGES) + 1
        )
        self.assertTrue(result.missing_chrome_prebuilt)
        self.assertTrue(result.missing_follower_prebuilt)
        self.assertFalse(result.local_uprev)

    def test_needs_none(self) -> None:
        """Verify not building any chrome packages prevents needing it."""
        graph = self._build_graph(with_chrome=False, with_followers=False)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=False)
        self.PatchObject(
            packages,
            "uprev_chrome",
            return_value=uprev_lib.UprevVersionedResult(),
        )

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target)

        self.assertFalse(result.needs_chrome_source)
        self.assertFalse(result.builds_chrome)
        self.assertFalse(result.packages)
        self.assertFalse(result.missing_chrome_prebuilt)
        self.assertFalse(result.missing_follower_prebuilt)
        self.assertFalse(result.local_uprev)

    def test_needs_chrome_only(self) -> None:
        """Verify only chrome triggers needs chrome source."""
        graph = self._build_graph(with_chrome=True, with_followers=False)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=False)
        self.PatchObject(
            packages,
            "uprev_chrome",
            return_value=uprev_lib.UprevVersionedResult(),
        )

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target)

        self.assertTrue(result.needs_chrome_source)
        self.assertTrue(result.builds_chrome)
        self.assertTrue(result.packages)
        self.assertEqual(
            {p.atom for p in result.packages}, {constants.CHROME_CP}
        )
        self.assertTrue(result.missing_chrome_prebuilt)
        self.assertFalse(result.missing_follower_prebuilt)
        self.assertFalse(result.local_uprev)

    def test_needs_followers_only(self) -> None:
        """Verify only chrome followers triggers needs chrome source."""
        graph = self._build_graph(with_chrome=False, with_followers=True)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=False)
        self.PatchObject(
            packages,
            "uprev_chrome",
            return_value=uprev_lib.UprevVersionedResult(),
        )

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target)

        self.assertTrue(result.needs_chrome_source)
        self.assertFalse(result.builds_chrome)
        self.assertTrue(result.packages)
        self.assertEqual(
            {p.atom for p in result.packages},
            set(constants.OTHER_CHROME_PACKAGES),
        )
        self.assertFalse(result.missing_chrome_prebuilt)
        self.assertTrue(result.missing_follower_prebuilt)
        self.assertFalse(result.local_uprev)

    def test_has_prebuilts(self) -> None:
        """Test prebuilts prevent us from needing chrome source."""
        graph = self._build_graph(with_chrome=True, with_followers=True)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=True)
        self.PatchObject(
            packages,
            "uprev_chrome",
            return_value=uprev_lib.UprevVersionedResult(),
        )

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target)

        self.assertFalse(result.needs_chrome_source)
        self.assertTrue(result.builds_chrome)
        self.assertFalse(result.packages)
        self.assertFalse(result.missing_chrome_prebuilt)
        self.assertFalse(result.missing_follower_prebuilt)
        self.assertFalse(result.local_uprev)

    def test_compile_source(self) -> None:
        """Test compile source ignores prebuilts."""
        graph = self._build_graph(with_chrome=True, with_followers=True)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=True)
        self.PatchObject(
            packages,
            "uprev_chrome",
            return_value=uprev_lib.UprevVersionedResult(),
        )

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target, compile_source=True)

        self.assertTrue(result.needs_chrome_source)
        self.assertTrue(result.builds_chrome)
        self.assertTrue(result.packages)
        self.assertEqual(
            len(result.packages), len(constants.OTHER_CHROME_PACKAGES) + 1
        )
        self.assertTrue(result.missing_chrome_prebuilt)
        self.assertTrue(result.missing_follower_prebuilt)
        self.assertFalse(result.local_uprev)

    def test_local_uprev(self) -> None:
        """Test compile source ignores prebuilts."""
        graph = self._build_graph(with_chrome=True, with_followers=True)
        self.PatchObject(
            depgraph, "get_sysroot_dependency_graph", return_value=graph
        )
        self.PatchObject(packages, "has_prebuilt", return_value=False)

        uprev_result = uprev_lib.UprevVersionedResult()
        uprev_result.add_result("1.2.3.4", ["/tmp/foo"])
        self.PatchObject(packages, "uprev_chrome", return_value=uprev_result)

        build_target = build_target_lib.BuildTarget("build_target")

        result = packages.needs_chrome_source(build_target, compile_source=True)

        self.assertTrue(result.needs_chrome_source)
        self.assertTrue(result.builds_chrome)
        self.assertTrue(result.packages)
        self.assertEqual(
            len(result.packages), len(constants.OTHER_CHROME_PACKAGES) + 1
        )
        self.assertTrue(result.missing_chrome_prebuilt)
        self.assertTrue(result.missing_follower_prebuilt)
        self.assertTrue(result.local_uprev)


class GetTargetVersionTest(cros_test_lib.RunCommandTestCase):
    """Tests for get_target_version."""

    def setUp(self) -> None:
        self.build_target = build_target_lib.BuildTarget("build_target")

    def test_default_empty(self) -> None:
        """Default behavior with mostly stub empty data."""

        def GetBuildDependency(sysroot_path, board, mock_packages):
            assert sysroot_path == self.build_target.root
            assert board == self.build_target.name
            assert list(mock_packages) == [
                package_info.parse(constants.TARGET_OS_PKG)
            ]
            return {"package_deps": []}, {}

        self.PatchObject(
            dependency, "GetBuildDependency", side_effect=GetBuildDependency
        )
        ret = packages.get_target_versions(self.build_target)
        assert ret.android_version is None
        assert ret.android_branch is None
        assert ret.android_target is None
        assert ret.chrome_version is None
        assert isinstance(ret.platform_version, str)
        assert isinstance(ret.milestone_version, str)
        assert isinstance(ret.full_version, str)


class UprevDrivefsTest(cros_test_lib.MockTestCase):
    """Tests for uprev_drivefs."""

    def setUp(self) -> None:
        self.refs = [
            uprev_lib.GitRef(
                path="/chromeos/platform/drivefs-google3/",
                ref="refs/tags/drivefs_45.0.2",
                revision="123",
            )
        ]
        self.MOCK_DRIVEFS_EBUILD_PATH = "drivefs.45.0.2-r1.ebuild"

    def revisionBumpOutcome(self, ebuild_path):
        return uprev_lib.UprevResult(
            uprev_lib.Outcome.REVISION_BUMP, [ebuild_path]
        )

    def majorBumpOutcome(self, ebuild_path):
        return uprev_lib.UprevResult(
            uprev_lib.Outcome.VERSION_BUMP, [ebuild_path]
        )

    def sameVersionOutcome(self):
        return uprev_lib.UprevResult(uprev_lib.Outcome.SAME_VERSION_EXISTS)

    def test_latest_version_returns_none(self) -> None:
        """Test no refs were supplied"""
        output = packages.uprev_drivefs(None, [], chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_drivefs_uprev_fails(self) -> None:
        """Test a single ref is supplied."""
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=[None, None],
        )
        output = packages.uprev_drivefs(None, self.refs, chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_same_version_exists(self) -> None:
        """Test the same version exists uprev should not happen."""
        drivefs_outcome = self.sameVersionOutcome()
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=[drivefs_outcome],
        )
        output = packages.uprev_drivefs(None, self.refs, chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_revision_bump_both_packages(self) -> None:
        """Test both packages uprev, should succeed."""
        drivefs_outcome = self.revisionBumpOutcome(
            self.MOCK_DRIVEFS_EBUILD_PATH
        )
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=[drivefs_outcome],
        )
        output = packages.uprev_drivefs(None, self.refs, chroot_lib.Chroot())
        self.assertTrue(output.uprevved)

    def test_major_bump_both_packages(self) -> None:
        """Test both packages uprev, should succeed."""
        drivefs_outcome = self.majorBumpOutcome(self.MOCK_DRIVEFS_EBUILD_PATH)
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=[drivefs_outcome],
        )
        output = packages.uprev_drivefs(None, self.refs, chroot_lib.Chroot())
        self.assertTrue(output.uprevved)


class UprevKernelAfdo(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for uprev_kernel_afdo."""

    def setUp(self) -> None:
        # patch_ebuild_vars is tested separately.
        self.mock_patch = self.PatchObject(packages, "patch_ebuild_vars")
        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)
        self.metadata_dir = os.path.join(
            "src",
            "third_party",
            "toolchain-utils",
            "afdo_metadata",
        )
        osutils.SafeMakedirs(os.path.join(self.tempdir, self.metadata_dir))

    def test_uprev_kernel_afdo_version(self) -> None:
        """Test kernel afdo version uprev."""
        json_files = {
            "kernel_afdo.json": (
                "{\n"
                '  "chromeos-kernel-5_4": {\n'
                '    "name": "R106-12345.0-0123456789"\n'
                "  }\n"
                "}"
            ),
            "kernel_arm_afdo.json": (
                "{\n"
                '  "chromeos-kernel-5_15": {\n'
                '    "name": "R107-67890.0-0123456789"\n'
                "  }\n"
                "}"
            ),
        }
        for f, contents in json_files.items():
            self.WriteTempFile(os.path.join(self.metadata_dir, f), contents)

        returned_output = packages.uprev_kernel_afdo(
            None, [], chroot_lib.Chroot()
        )

        package_root = os.path.join(
            constants.SOURCE_ROOT,
            constants.CHROMIUMOS_OVERLAY_DIR,
            "sys-kernel",
        )
        expect_result = [
            uprev_lib.UprevVersionedModifications(
                new_version="R106-12345.0-0123456789",
                files=[
                    os.path.join(
                        package_root,
                        "chromeos-kernel-5_4",
                        "chromeos-kernel-5_4-9999.ebuild",
                    ),
                    os.path.join(
                        package_root, "chromeos-kernel-5_4", "Manifest"
                    ),
                ],
            ),
            uprev_lib.UprevVersionedModifications(
                new_version="R107-67890.0-0123456789",
                files=[
                    os.path.join(
                        package_root,
                        "chromeos-kernel-5_15",
                        "chromeos-kernel-5_15-9999.ebuild",
                    ),
                    os.path.join(
                        package_root, "chromeos-kernel-5_15", "Manifest"
                    ),
                ],
            ),
        ]
        self.assertTrue(returned_output.uprevved)
        self.assertEqual(returned_output.modified, expect_result)

    def test_uprev_kernel_afdo_empty_json(self) -> None:
        """Test kernel afdo version unchanged."""
        json_files = {
            "kernel_afdo.json": "{}",
            "kernel_arm_afdo.json": "{}",
        }
        for f, contents in json_files.items():
            self.WriteTempFile(os.path.join(self.metadata_dir, f), contents)

        returned_output = packages.uprev_kernel_afdo(
            None, [], chroot_lib.Chroot()
        )
        self.assertFalse(returned_output.uprevved)

    def test_uprev_kernel_afdo_empty_file(self) -> None:
        """Test malformed json raises."""
        json_files = {
            "kernel_afdo.json": "",
            "kernel_arm_afdo.json": "",
        }
        for f, contents in json_files.items():
            self.WriteTempFile(os.path.join(self.metadata_dir, f), contents)

        with self.assertRaisesRegex(
            json.decoder.JSONDecodeError, "Expecting value"
        ):
            packages.uprev_kernel_afdo(None, [], chroot_lib.Chroot())

    def test_uprev_kernel_afdo_manifest_raises(self) -> None:
        """Test manifest update raises."""
        json_files = {
            "kernel_afdo.json": (
                "{\n"
                '  "chromeos-kernel-5_4": {\n'
                '    "name": "R106-12345.0-0123456789"\n'
                "  }\n"
                "}"
            ),
        }
        for f, contents in json_files.items():
            self.WriteTempFile(os.path.join(self.metadata_dir, f), contents)
        # run() raises exception.
        self.rc.SetDefaultCmdResult(
            side_effect=cros_build_lib.RunCommandError("error")
        )

        with self.assertRaises(uprev_lib.EbuildManifestError):
            packages.uprev_kernel_afdo(None, [], chroot_lib.Chroot())


# TODO(chenghaoyang): Shouldn't use uprev_workon_ebuild_to_version.
class UprevPerfettoTest(cros_test_lib.MockTestCase):
    """Tests for uprev_perfetto."""

    def setUp(self) -> None:
        self.refs = [
            uprev_lib.GitRef(path="/foo", ref="refs/tags/v12.0", revision="123")
        ]
        self.MOCK_PERFETTO_EBUILD_PATH = "perfetto-12.0-r1.ebuild"
        self.MOCK_PERFETTO_PROTO_EBUILD_PATH = "perfetto-protos-12.0-r1.ebuild"

    def revisionBumpOutcome(self):
        return [
            uprev_lib.UprevResult(
                uprev_lib.Outcome.REVISION_BUMP,
                [self.MOCK_PERFETTO_EBUILD_PATH],
            ),
            uprev_lib.UprevResult(
                uprev_lib.Outcome.REVISION_BUMP,
                [self.MOCK_PERFETTO_PROTO_EBUILD_PATH],
            ),
        ]

    def majorBumpOutcome(self):
        return [
            uprev_lib.UprevResult(
                uprev_lib.Outcome.VERSION_BUMP, [self.MOCK_PERFETTO_EBUILD_PATH]
            ),
            uprev_lib.UprevResult(
                uprev_lib.Outcome.VERSION_BUMP,
                [self.MOCK_PERFETTO_PROTO_EBUILD_PATH],
            ),
        ]

    def newerVersionOutcome(self):
        return uprev_lib.UprevResult(uprev_lib.Outcome.NEWER_VERSION_EXISTS)

    def sameVersionOutcome(self):
        return uprev_lib.UprevResult(uprev_lib.Outcome.SAME_VERSION_EXISTS)

    def test_latest_version_returns_none(self) -> None:
        """Test no refs were supplied"""
        output = packages.uprev_perfetto(None, [], chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_perfetto_uprev_fails(self) -> None:
        """Test a single ref is supplied."""
        self.PatchObject(
            uprev_lib, "uprev_workon_ebuild_to_version", side_effect=[None]
        )
        output = packages.uprev_perfetto(None, self.refs, chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_newer_version_exists(self) -> None:
        """Test the newer version exists uprev should not happen."""
        perfetto_outcome = self.newerVersionOutcome()
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=[perfetto_outcome],
        )
        output = packages.uprev_perfetto(None, self.refs, chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_same_version_exists(self) -> None:
        """Test the same version exists uprev should not happen."""
        perfetto_outcome = self.sameVersionOutcome()
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=[perfetto_outcome],
        )
        output = packages.uprev_perfetto(None, self.refs, chroot_lib.Chroot())
        self.assertFalse(output.uprevved)

    def test_revision_bump_perfetto_package(self) -> None:
        """Test perfetto package uprev."""
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=self.revisionBumpOutcome(),
        )
        output = packages.uprev_perfetto(None, self.refs, chroot_lib.Chroot())
        self.assertTrue(output.uprevved)
        self.assertEqual(
            output.modified[0].files, [self.MOCK_PERFETTO_EBUILD_PATH]
        )
        self.assertEqual(
            output.modified[1].files, [self.MOCK_PERFETTO_PROTO_EBUILD_PATH]
        )

    def test_major_bump_perfetto_package(self) -> None:
        """Test perfetto package uprev."""
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=self.majorBumpOutcome(),
        )
        output = packages.uprev_perfetto(None, self.refs, chroot_lib.Chroot())
        self.assertTrue(output.uprevved)
        self.assertEqual(
            output.modified[0].files, [self.MOCK_PERFETTO_EBUILD_PATH]
        )
        self.assertEqual(
            output.modified[1].files, [self.MOCK_PERFETTO_PROTO_EBUILD_PATH]
        )

    def test_revision_bump_trunk(self) -> None:
        """Test revision bump on receiving non-versioned trunk refs."""
        refs = [
            uprev_lib.GitRef(
                path="/foo", ref="refs/heads/main", revision="0123456789abcdef"
            )
        ]
        self.PatchObject(
            uprev_lib, "get_stable_ebuild_version", return_value="12.0"
        )
        self.PatchObject(
            uprev_lib,
            "uprev_workon_ebuild_to_version",
            side_effect=self.revisionBumpOutcome(),
        )
        output = packages.uprev_perfetto(None, refs, chroot_lib.Chroot())

        self.assertTrue(output.uprevved)
        self.assertEqual(
            output.modified[0].files, [self.MOCK_PERFETTO_EBUILD_PATH]
        )
        self.assertEqual(output.modified[0].new_version, "12.0-012345678")
        self.assertEqual(
            output.modified[1].files, [self.MOCK_PERFETTO_PROTO_EBUILD_PATH]
        )
        self.assertEqual(output.modified[1].new_version, "12.0-012345678")


class UprevStarbaseArtifactsTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests of uprev of starbase artifacts ebuild."""

    simple_name = "apps"
    component = "chromeos-base"
    package_name = f"starbase-{simple_name}"
    version = "2.4.6"
    revision = "111"
    tarfile_name = f"starbase_{simple_name}_tarfile.tar.zst"
    tarfile_hash = "42"
    ebuild_name_format = f"starbase-{simple_name}-%s%s.ebuild"
    rev0_ebuild_name = ebuild_name_format % (version, "")
    old_ebuild_name = ebuild_name_format % (version, f"-r{revision}")
    ebuild_content_format = """# Buildable ebuild
foo
bar
baz
SRC_URI="${DISTFILES}/%s"
zab
rab
oof
"""
    manifest_content = f"DIST {tarfile_name} 7 BLAH 123 SHA512 42"

    def uprev(self, version_id) -> None:
        """Test that the ebuild is modified and uprevved."""

        # Create ebuild directory.
        directory_tree = (
            D(
                self.component,
                [
                    D(
                        self.package_name,
                        [
                            self.rev0_ebuild_name,
                            self.old_ebuild_name,
                            "Manifest",
                        ],
                    ),
                ],
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, directory_tree)
        package_path = os.path.join(
            self.tempdir, self.component, self.package_name
        )
        old_ebuild_content = self.ebuild_content_format % "to-be-clobbered"
        rev0_ebuild_path = os.path.join(package_path, self.rev0_ebuild_name)
        old_ebuild_path = os.path.join(package_path, self.old_ebuild_name)

        # Create mock ebuild to be uprevved.
        self.WriteTempFile(rev0_ebuild_path, old_ebuild_content)
        manifest_path = os.path.join(package_path, "Manifest")
        self.WriteTempFile(manifest_path, self.manifest_content)

        # Run the function under test.
        modified = packages.starbase_find_and_uprev(
            self.tarfile_name,
            self.tarfile_hash,
            self.component,
            self.package_name,
            version_id,
            self.tempdir,
            chroot_lib.Chroot(),
        )

        # Check that the expected files were modified.
        new_rev = f"-r{str(int(self.revision) + 1)}"
        new_ebuild_name = self.ebuild_name_format % (self.version, new_rev)
        new_ebuild_path = os.path.join(package_path, new_ebuild_name)

        self.assertEqual(modified[0], manifest_path)
        self.assertEqual(modified[1], rev0_ebuild_path)
        self.assertEqual(modified[2], old_ebuild_path)
        self.assertEqual(modified[3], new_ebuild_path)

        tarfile_path = f"starbase-{version_id}/{self.tarfile_name}"

        # Check that the new ebuild file contains the expected content.
        new_ebuild_content = self.ebuild_content_format % tarfile_path
        found_content = osutils.ReadFile(new_ebuild_path)
        self.assertEqual(new_ebuild_content, found_content)

    def test_uprev_head(self) -> None:
        self.uprev("head-20230101-rc123")

    def test_uprev_release(self) -> None:
        self.uprev("release-20230101-rc123")


class UprevHeliumArtifactsTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests of uprev of Helium artifacts ebuild."""

    component = "chromeos-base"
    package_name = "chromeos-board-default-arc-apps-selphie"
    version = "0.0.1"
    revision = "1"
    tarfile_name = "starbase_helium-arcvm-artifacts_tarfile.tar.zst"
    tarfile_hash = "42"
    ebuild_name_format = "chromeos-board-default-arc-apps-selphie-%s%s.ebuild"
    rev0_ebuild_name = ebuild_name_format % (version, "")
    old_ebuild_name = ebuild_name_format % (version, f"-r{revision}")
    ebuild_content_format = """# Buildable ebuild
foo
bar
baz
SRC_URI="${DISTFILES}/%s"
zab
rab
oof
"""
    manifest_content = f"DIST {tarfile_name} 7 BLAH 123 SHA512 42"

    def uprev(self, version_id) -> None:
        """Test that the ebuild is modified and uprevved."""

        # Create ebuild directory.
        directory_tree = (
            D(
                self.component,
                [
                    D(
                        self.package_name,
                        [
                            self.rev0_ebuild_name,
                            self.old_ebuild_name,
                            "Manifest",
                        ],
                    ),
                ],
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, directory_tree)
        package_path = os.path.join(
            self.tempdir, self.component, self.package_name
        )
        old_ebuild_content = self.ebuild_content_format % "to-be-clobbered"
        rev0_ebuild_path = os.path.join(package_path, self.rev0_ebuild_name)
        old_ebuild_path = os.path.join(package_path, self.old_ebuild_name)

        # Create mock ebuild to be uprevved.
        self.WriteTempFile(rev0_ebuild_path, old_ebuild_content)
        manifest_path = os.path.join(package_path, "Manifest")
        self.WriteTempFile(manifest_path, self.manifest_content)

        # Run the function under test.
        modified = packages.starbase_find_and_uprev(
            self.tarfile_name,
            self.tarfile_hash,
            self.component,
            self.package_name,
            version_id,
            self.tempdir,
            chroot_lib.Chroot(),
        )

        # Check that the expected files were modified.
        new_rev = f"-r{str(int(self.revision) + 1)}"
        new_ebuild_name = self.ebuild_name_format % (self.version, new_rev)
        new_ebuild_path = os.path.join(package_path, new_ebuild_name)

        self.assertEqual(modified[0], manifest_path)
        self.assertEqual(modified[1], rev0_ebuild_path)
        self.assertEqual(modified[2], old_ebuild_path)
        self.assertEqual(modified[3], new_ebuild_path)

        tarfile_path = f"starbase-{version_id}/{self.tarfile_name}"

        # Check that the new ebuild file contains the expected content.
        new_ebuild_content = self.ebuild_content_format % tarfile_path
        found_content = osutils.ReadFile(new_ebuild_path)
        self.assertEqual(new_ebuild_content, found_content)

    def test_uprev_head(self) -> None:
        self.uprev("head-20230101-rc123")

    def test_uprev_release(self) -> None:
        self.uprev("release-20230101-r42-rc123")


class UprevCroshTest(cros_test_lib.MockTempDirTestCase):
    """Tests of uprev of crosh packages."""

    # pylint: disable=protected-access

    def setUp(self) -> None:
        self.StartPatcher(parallel_unittest.ParallelMock())

        manifest_contents = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <default revision="refs/heads/main" remote="cros" />
  <remote name="cros" fetch="http://localhost" />
  <project path="src/third_party/libapps" name="apps/libapps" />
  <project path="src/third_party/chromiumos-overlay" name="chromiumos/overlays/chromiumos-overlay" />
</manifest>
"""
        # Exact values here don't really need.
        cros_version_contents = """
CHROME_BRANCH=145
CHROME_VERSION=
CHROMEOS_BUILD=16515
CHROMEOS_BRANCH=0
CHROMEOS_PATCH=0
CHROMEOS_VERSION_STRING=16515.0.0
"""
        nassh_fetch_contents = """
{
  "_version": 0,
  "ignore": {
    "size": "0",
    "url": "http://",
    "hashes": {}
  },
  "inc": {
    "crosh": true,
    "size": "123",
    "url": "http://foo/bar.zip",
    "hashes": {"sha256": "abcd"}
  }
}
"""
        file_layout = (
            # Internal manifest layout.
            D(
                ".repo",
                [D("manifests", []), F("manifest.xml", manifest_contents)],
            ),
            # The libapps source tree.
            D(
                "src/third_party/libapps",
                [
                    D(
                        "nassh",
                        [
                            F("fetch.json", nassh_fetch_contents),
                            F(
                                "manifest.json",
                                '{\n"version": "1.0"\n}\n',
                            ),
                        ],
                    )
                ],
            ),
            # The ebuild overlay.
            D(
                constants.CHROMIUMOS_OVERLAY_DIR,
                [
                    F(
                        "chromeos/config/chromeos_version.sh",
                        cros_version_contents,
                    ),
                    D(
                        packages._CROSH_CP,
                        [D("files")],
                    ),
                ],
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        # Copy real files over that are used to uprev.
        for efile in (
            "crosh-extension-9999.ebuild",
            "Manifest",
            "files/chromeos-version.sh",
        ):
            subpath = (
                Path(constants.CHROMIUMOS_OVERLAY_DIR)
                / packages._CROSH_CP
                / efile
            )
            shutil.copy(constants.SOURCE_ROOT / subpath, self.tempdir / subpath)

        # Init skeleton libapps tree for uprev lib.
        libapps_root = self.tempdir / "src" / "third_party" / "libapps"
        git.Init(libapps_root)
        git.AddPath(libapps_root / "nassh")
        git.Commit(libapps_root, "init")

        # No need to test this code path.
        self.PatchObject(uprev_lib, "clean_stale_packages")

    def test_initial_uprev(self) -> None:
        """Verify initial uprev works."""
        result = packages.uprev_libapps(
            None,
            [
                uprev_lib.GitRef(
                    "src/third_party/libapps",
                    "refs/heads/main",
                    "HEAD",
                )
            ],
            None,
            source_root=self.tempdir,
        )

        # Check generated ebuild.
        assert result.uprevved
        new_ebuild = (
            self.tempdir
            / constants.CHROMIUMOS_OVERLAY_DIR
            / packages._CROSH_CP
            / "crosh-extension-1.0-r1.ebuild"
        )
        self.assertExists(new_ebuild)

        assert (
            """PUPR_SRC_URI="\n\thttp://foo/bar.zip\n"\n"""
            in new_ebuild.read_text(encoding="utf-8")
        )

        # Check updated files
        assert str(new_ebuild.with_name("Manifest")) in result.modified[0].files
        assert (
            str(new_ebuild.with_name("crosh-extension-9999.ebuild"))
            in result.modified[0].files
        )
        assert str(new_ebuild) in result.modified[0].files

        # Check generated Manifest.
        manifest = (
            self.tempdir
            / constants.CHROMIUMOS_OVERLAY_DIR
            / packages._CROSH_CP
            / "Manifest"
        )
        assert "DIST bar.zip 123 SHA256 abcd\n" in manifest.read_text(
            encoding="utf-8"
        )


class UprevLkgmFileTest(cros_test_lib.MockTempDirTestCase):
    """uprev_cros_lkgm_file_on_chrome_repo tests."""

    def test_invalid_ref(self) -> None:
        """Verify invalid ref raises error."""
        with self.assertRaises(packages.UprevError):
            packages.uprev_cros_lkgm_file_on_chrome_repo(
                [
                    uprev_lib.GitRef(
                        "manifest-internal",
                        "refs/heads/invalid",
                        "deadbeef12345678901234567890123456789012",
                    )
                ],
                None,
            )

    def test_success(self) -> None:
        """Verify successful uprev."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="1.2.3-12345",
        )
        self.PatchObject(
            uprev_lib,
            "validate_lkgm_builds_succeeded",
            return_value=True,
        )

        res = packages.uprev_cros_lkgm_file_on_chrome_repo(
            [
                uprev_lib.GitRef(
                    "manifest-internal",
                    "refs/heads/snapshot",
                    "deadbeef12345678901234567890123456789012",
                )
            ],
            chroot,
        )
        self.assertTrue(res)
        self.assertEqual(res.modified[0].new_version, "1.2.3-12345")
        lkgm_path = lkgm_dir / "CHROMEOS_LKGM"
        self.assertEqual(lkgm_path.read_text(encoding="utf-8"), "1.2.3-12345")

    def test_missing_image(self) -> None:
        """Verify uprev is skipped if build validation fails."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="1.2.3-12345",
        )
        self.PatchObject(
            uprev_lib,
            "validate_lkgm_builds_succeeded",
            return_value=False,
        )

        res = packages.uprev_cros_lkgm_file_on_chrome_repo(
            [
                uprev_lib.GitRef(
                    "manifest-internal",
                    "refs/heads/snapshot",
                    "deadbeef12345678901234567890123456789012",
                )
            ],
            chroot,
        )
        self.assertFalse(res)
        lkgm_path = lkgm_dir / "CHROMEOS_LKGM"
        self.assertFalse(lkgm_path.exists())

    def test_infra_error(self) -> None:
        """Verify uprev fails if build validation has infra error."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="1.2.3-12345",
        )
        self.PatchObject(
            uprev_lib,
            "validate_lkgm_builds_succeeded",
            side_effect=uprev_lib.EbuildUprevError("RPC error"),
        )

        with self.assertRaises(packages.UprevError):
            packages.uprev_cros_lkgm_file_on_chrome_repo(
                [
                    uprev_lib.GitRef(
                        "manifest-internal",
                        "refs/heads/snapshot",
                        "deadbeef12345678901234567890123456789012",
                    )
                ],
                chroot,
            )

    def test_stable_ref_calls_validation(self) -> None:
        """Verify stable ref calls build validation."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="1.2.3-12345",
        )
        mock_validate = self.PatchObject(
            uprev_lib,
            "validate_lkgm_builds_succeeded",
            return_value=True,
        )

        res = packages.uprev_cros_lkgm_file_on_chrome_repo(
            [
                uprev_lib.GitRef(
                    "manifest-internal",
                    "refs/heads/stable",
                    "deadbeef12345678901234567890123456789012",
                )
            ],
            chroot,
        )
        self.assertTrue(res)
        self.assertEqual(res.modified[0].new_version, "1.2.3-12345")
        lkgm_path = lkgm_dir / "CHROMEOS_LKGM"
        self.assertEqual(lkgm_path.read_text(encoding="utf-8"), "1.2.3-12345")
        mock_validate.assert_called_once_with(
            "1.2.3-12345", "deadbeef12345678901234567890123456789012"
        )

    def test_skip_older_version(self) -> None:
        """Verify uprev is skipped if target version is older."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        lkgm_path = lkgm_dir / "CHROMEOS_LKGM"
        osutils.WriteFile(lkgm_path, "2.0.0-12345")

        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="1.0.0-12345",
        )
        res = packages.uprev_cros_lkgm_file_on_chrome_repo(
            [uprev_lib.GitRef("path", "refs/heads/snapshot", "HEAD")],
            chroot,
        )
        self.assertFalse(res)
        self.assertEqual(lkgm_path.read_text(encoding="utf-8"), "2.0.0-12345")

    def test_skip_same_version(self) -> None:
        """Verify uprev is skipped if target version is equal."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        lkgm_path = lkgm_dir / "CHROMEOS_LKGM"
        osutils.WriteFile(lkgm_path, "2.0.0-12345")

        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="2.0.0-12345",
        )
        res = packages.uprev_cros_lkgm_file_on_chrome_repo(
            [uprev_lib.GitRef("path", "refs/heads/snapshot", "HEAD")],
            chroot,
        )
        self.assertFalse(res)
        self.assertEqual(lkgm_path.read_text(encoding="utf-8"), "2.0.0-12345")

    def test_newer_version_success(self) -> None:
        """Verify uprev succeeds if target version is newer."""
        chroot = mock.Mock()
        chroot.chrome_root = str(self.tempdir)
        lkgm_dir = self.tempdir / "src" / "chromeos"
        osutils.SafeMakedirs(lkgm_dir)
        lkgm_path = lkgm_dir / "CHROMEOS_LKGM"
        osutils.WriteFile(lkgm_path, "1.0.0-12345")

        self.PatchObject(
            uprev_lib,
            "get_version_with_snapshot_from_manifest",
            return_value="2.0.0-12345",
        )
        self.PatchObject(
            uprev_lib,
            "validate_lkgm_builds_succeeded",
            return_value=True,
        )
        res = packages.uprev_cros_lkgm_file_on_chrome_repo(
            [uprev_lib.GitRef("path", "refs/heads/snapshot", "HEAD")],
            chroot,
        )
        self.assertTrue(res)
        self.assertEqual(res.modified[0].new_version, "2.0.0-12345")
        self.assertEqual(lkgm_path.read_text(encoding="utf-8"), "2.0.0-12345")
