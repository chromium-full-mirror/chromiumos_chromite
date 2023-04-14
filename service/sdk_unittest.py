# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SDK service tests."""

import os
from pathlib import Path
from typing import List

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import binpkg
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import sdk_builder_lib
from chromite.service import sdk


class BuildSdkTarballTest(cros_test_lib.MockTestCase):
    """Tests for BuildSdkTarball function."""

    def testSuccess(self):
        builder_lib = self.PatchObject(sdk_builder_lib, "BuildSdkTarball")
        sdk.BuildSdkTarball(chroot_lib.Chroot("/test/chroot"))
        builder_lib.assert_called_with(Path("/test/chroot/build/amd64-host"))


class CreateManifestFromSdkTest(cros_test_lib.MockTempDirTestCase):
    """Tests for CreateManifestFromSdk."""

    def setUp(self):
        """Set up the test case by populating a tempdir for the packages."""
        self._portage_db = portage_util.PortageDB()
        osutils.WriteFile(
            os.path.join(self.tempdir, "dev-python/django-1.5.12-r3.ebuild"),
            "EAPI=6",
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "dev-python/urllib3-1.25.10.ebuild"),
            "EAPI=7",
            makedirs=True,
        )
        self._installed_packages = [
            portage_util.InstalledPackage(
                self._portage_db,
                os.path.join(self.tempdir, "dev-python"),
                category="dev-python",
                pf="django-1.5.12-r3",
            ),
            portage_util.InstalledPackage(
                self._portage_db,
                os.path.join(self.tempdir, "dev-python"),
                category="dev-python",
                pf="urllib3-1.25.10",
            ),
        ]

    def testSuccess(self):
        """Test a standard, successful function call."""
        dest_dir = Path("/my_build_root")
        self.PatchObject(
            portage_util.PortageDB,
            "InstalledPackages",
            return_value=self._installed_packages,
        )
        write_file_patch = self.PatchObject(osutils, "WriteFile")
        manifest_path = sdk.CreateManifestFromSdk(self.tempdir, dest_dir)
        expected_manifest_path = (
            dest_dir / f"{constants.SDK_TARBALL_NAME}.Manifest"
        )
        expected_json_input = '{"version": "1", "packages": {"dev-python/django": [["1.5.12-r3", {}]], "dev-python/urllib3": [["1.25.10", {}]]}}'
        write_file_patch.assert_called_with(
            expected_manifest_path,
            expected_json_input,
        )
        self.assertEqual(manifest_path, expected_manifest_path)


class CreateArgumentsTest(cros_test_lib.MockTestCase):
    """CreateArguments tests."""

    def _GetArgsList(self, **kwargs):
        """Helper to simplify getting the argument list."""
        instance = sdk.CreateArguments(**kwargs)
        return instance.GetArgList()

    def testGetArgList(self):
        """Test the GetArgsList method."""
        # Check the variations of replace.
        self.assertIn("--replace", self._GetArgsList(replace=True))
        self.assertIn("--create", self._GetArgsList(replace=False))

        # Check the other flags get added when the correct argument passed.
        self.assertListEqual(
            [
                "--create",
                "--sdk-version",
                "foo",
                "--skip-chroot-upgrade",
            ],
            self._GetArgsList(
                replace=False,
                bootstrap=False,
                sdk_version="foo",
                skip_chroot_upgrade=True,
            ),
        )

        self.assertListEqual(
            ["--create", "--bootstrap"],
            self._GetArgsList(replace=False, bootstrap=True),
        )


class CreateBinhostCLsTest(cros_test_lib.RunCommandTestCase):
    """Tests for CreateBinhostCLs."""

    def testCreateBinhostCLs(self):
        def fake_run(cmd, *_args, **__kwargs):
            i = cmd.index("--output")
            self.assertGreater(len(cmd), i + 1, "no filename after --output")
            name = cmd[i + 1]
            with open(name, "w", encoding="utf-8") as f:
                f.write(
                    '{ "created_cls": ["the_cl"'
                    ', "https://crrev.com/another/42"]\n}\n'
                )

        self.rc.AddCmdResult(
            partial_mock.ListRegex("upload_prebuilts"),
            side_effect=fake_run,
        )

        def mock_rev(_filename, _data, report=None, *_args, **_kwargs):
            if report is None:
                return
            report.setdefault("created_cls", []).append("sdk_version/18")

        self.PatchObject(
            binpkg, "UpdateAndSubmitKeyValueFile", side_effect=mock_rev
        )

        cls = sdk.CreateBinhostCLs(
            prepend_version="unittest",
            version="2022.02.22",
            upload_location="gs://unittest/createbinhostcls",
            sdk_tarball_template="2022/02/%(target)s-2022.02.22.tar.xz",
        )
        self.assertEqual(
            cls, ["the_cl", "https://crrev.com/another/42", "sdk_version/18"]
        )


class UpdateArgumentsTest(cros_test_lib.TestCase):
    """UpdateArguments tests."""

    def _GetArgList(self, **kwargs):
        """Helper to simplify getting the argument list."""
        instance = sdk.UpdateArguments(**kwargs)
        return instance.GetArgList()

    def testBuildSource(self):
        """Test the build_source argument."""
        self.assertIn("--nousepkg", self._GetArgList(build_source=True))

    def testNoBuildSource(self):
        """Test using binpkgs."""
        self.assertNotIn("--nousepkg", self._GetArgList(build_source=False))

    def testToolchainTargets(self):
        """Test the toolchain boards argument."""
        expected = ["--toolchain_boards", "board1,board2"]
        result = self._GetArgList(toolchain_targets=["board1", "board2"])
        for arg in expected:
            self.assertIn(arg, result)

    def testToolchainTargetsIgnoredForSource(self):
        """Test the toolchain boards argument."""
        expected = ["--nousepkg"]
        result = self._GetArgList(
            toolchain_targets=["board1", "board2"], build_source=True
        )
        self.assertNotIn("--toolchain_boards", result)
        for arg in expected:
            self.assertIn(arg, result)

    def testNoToolchainTargets(self):
        """Test no toolchain boards argument."""
        self.assertEqual(
            [], self._GetArgList(build_source=False, toolchain_targets=None)
        )


class GetLatestVersionTest(cros_test_lib.MockTestCase):
    """Test case for GetLatestVersion()."""

    def testSuccess(self):
        """Test an ordinary, successful call."""
        expected_latest_version = "1970.01.01.000000"
        file_contents = f'LATEST_SDK="{expected_latest_version}"'.encode()
        cat_patch = self.PatchObject(
            gs.GSContext,
            "Cat",
            return_value=file_contents,
        )
        returned_version = sdk.GetLatestVersion()
        self.assertEqual(expected_latest_version, returned_version)
        cat_patch.assert_called_with("gs://chromiumos-sdk/cros-sdk-latest.conf")

    def testInvalidFileContents(self):
        """Test a response if the file contents are malformed."""
        file_contents = b"Latest SDK version: 1970.01.01.000000"
        self.PatchObject(gs.GSContext, "Cat", return_value=file_contents)
        with self.assertRaises(ValueError):
            sdk.GetLatestVersion()


class UnmountTest(
    cros_test_lib.RunCommandTempDirTestCase, cros_test_lib.MockTestCase
):
    """Unmount tests."""

    def testUnmountPath(self):
        self.PatchObject(osutils, "UmountTree", return_value=True)
        sdk.UnmountPath("/some/path")

    def testUnmountPathFails(self):
        self.PatchObject(
            osutils,
            "UmountTree",
            side_effect=cros_build_lib.RunCommandError("umount failure"),
        )
        with self.assertRaises(sdk.UnmountError) as unmount_assert:
            sdk.UnmountPath("/some/path")
        # Unpack the underlying (thrown) exception from the assertRaises context
        # manager exception attribute.
        unmount_exception = unmount_assert.exception
        self.assertIn("Umount failed:", str(unmount_exception))


class CreateTest(cros_test_lib.RunCommandTempDirTestCase):
    """Create function tests."""

    def testCreate(self):
        """Test the create function builds the command correctly."""
        arguments = sdk.CreateArguments(replace=True)
        arguments.chroot_path = os.path.join(self.tempdir, "chroot")
        expected_args = ["--arg", "--other", "--with-value", "value"]
        expected_version = 1

        self.PatchObject(arguments, "GetArgList", return_value=expected_args)
        self.PatchObject(sdk, "GetChrootVersion", return_value=expected_version)
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        version = sdk.Create(arguments)

        self.assertCommandContains(expected_args)
        self.assertEqual(expected_version, version)

    def testCreateInsideFails(self):
        """Test Create raises an error when called inside the chroot."""
        # Make sure it fails inside the chroot.
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=True)
        arguments = sdk.CreateArguments()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            sdk.Create(arguments)


class DeleteTest(cros_test_lib.RunCommandTestCase):
    """Delete function tests."""

    def testDeleteNoChroot(self):
        """Test no chroot provided."""
        sdk.Delete()
        # cros_sdk --delete.
        self.assertCommandContains(["--delete"])
        # No chroot specified for cros_sdk --delete.
        self.assertCommandContains(["--chroot"], expected=False)

    def testDeleteWithChroot(self):
        """Test with chroot provided."""
        path = "/some/path"
        sdk.Delete(chroot=chroot_lib.Chroot(path))
        self.assertCommandContains(["--delete", "--chroot", path])

    def testDeleteWithChrootAndForce(self):
        """Test with chroot and force provided."""
        path = "/some/path"
        sdk.Delete(chroot=chroot_lib.Chroot(path), force=True)
        self.assertCommandContains(["--delete", "--force", "--chroot", path])


class UpdateTest(cros_test_lib.RunCommandTestCase):
    """Update function tests."""

    def setUp(self):
        # Needs to be run inside the chroot right now.
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=True)

    def testUpdate(self):
        """Test the update method."""
        arguments = sdk.UpdateArguments()
        expected_args = ["--arg", "--other", "--with-value", "value"]
        expected_version = 1
        self.PatchObject(arguments, "GetArgList", return_value=expected_args)
        self.PatchObject(sdk, "GetChrootVersion", return_value=expected_version)

        version = sdk.Update(arguments)

        self.assertCommandContains(expected_args)
        self.assertEqual(expected_version, version)


class BuildSdkToolchainTest(cros_test_lib.RunCommandTestCase):
    """Test the implementation of BuildSdkToolchain()."""

    _chroot_path = "/test/chroot"
    _filenames_to_find = ["foo.tar.gz", "bar.txt"]

    @staticmethod
    def _Chroot() -> chroot_lib.Chroot:
        """Return a mock chroot for testing."""
        return chroot_lib.Chroot(BuildSdkToolchainTest._chroot_path)

    @staticmethod
    def _ExpectedFoundFiles() -> List[common_pb2.Path]:
        return [
            common_pb2.Path(
                path=os.path.join(
                    "/",
                    constants.SDK_TOOLCHAINS_OUTPUT,
                    filename,
                ),
                location=common_pb2.Path.INSIDE,
            )
            for filename in BuildSdkToolchainTest._filenames_to_find
        ]

    def testSuccess(self):
        """Check that a standard call performs expected logic.

        Look for the following behavior:
        1. Call `cros_setup_toolchain --nousepkg`
        2. Clear any existing files in the output dir
        3. Call `cros_setup_toolchain --debug --create-packages --output-dir`
        4. Return any generated filepaths
        """
        # Arrange
        output_dir = os.path.join(
            self._chroot_path, constants.SDK_TOOLCHAINS_OUTPUT
        )
        rmdir_patch = self.PatchObject(osutils, "RmDir")
        listdir_patch = self.PatchObject(os, "listdir")
        listdir_patch.return_value = self._filenames_to_find

        # Act
        found_files = sdk.BuildSdkToolchain(self._Chroot())

        # Assert
        self.assertCommandCalled(
            ["sudo", "--", "cros_setup_toolchains", "--nousepkg"],
            enter_chroot=True,
        )
        rmdir_patch.assert_any_call(output_dir, ignore_missing=True, sudo=True)
        self.assertCommandCalled(
            [
                "sudo",
                "--",
                "cros_setup_toolchains",
                "--debug",
                "--create-packages",
                "--output-dir",
                os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT),
            ],
            enter_chroot=True,
        )
        self.assertEqual(found_files, self._ExpectedFoundFiles())

    def testSuccessWithUseFlags(self):
        """Check that a standard call with USE flags performs expected logic.

        The call to `cros_setup_toolchain --nousepkg` should use the USE flag.
        However, the call to `cros_setup_toolchain ... --create-packages ...`
        should NOT use the USE flag.
        """
        # Arrange
        output_dir = os.path.join(
            self._chroot_path, constants.SDK_TOOLCHAINS_OUTPUT
        )
        rmdir_patch = self.PatchObject(osutils, "RmDir")
        listdir_patch = self.PatchObject(os, "listdir")
        listdir_patch.return_value = self._filenames_to_find

        # Act
        found_files = sdk.BuildSdkToolchain(
            self._Chroot(), extra_env={"USE": "llvm-next"}
        )

        # Assert
        self.assertCommandCalled(
            [
                "sudo",
                "USE=llvm-next",
                "--",
                "cros_setup_toolchains",
                "--nousepkg",
            ],
            enter_chroot=True,
        )
        rmdir_patch.assert_any_call(output_dir, ignore_missing=True, sudo=True)
        self.assertCommandCalled(
            [
                "sudo",
                "--",
                "cros_setup_toolchains",
                "--debug",
                "--create-packages",
                "--output-dir",
                os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT),
            ],
            enter_chroot=True,
        )
        self.assertEqual(found_files, self._ExpectedFoundFiles())
