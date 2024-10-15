# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SDK service tests."""

import os
from pathlib import Path
import textwrap
from typing import List, Optional, Tuple

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import binpkg
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import sdk_builder_lib
from chromite.lib.parser import package_info
from chromite.service import binhost
from chromite.service import sdk


class BuildSdkTarballTest(cros_test_lib.MockTestCase):
    """Tests for BuildSdkTarball function."""

    def testSuccess(self) -> None:
        builder_lib = self.PatchObject(sdk_builder_lib, "BuildSdkTarball")
        chroot = chroot_lib.Chroot("/test/chroot", out_path="/test/out")
        sdk.BuildSdkTarball(chroot, "FAKE_VERSION")
        builder_lib.assert_called_with(
            Path(chroot.full_path("/build/amd64-host")),
            "FAKE_VERSION",
        )


class CreateManifestFromSdkTest(cros_test_lib.MockTempDirTestCase):
    """Tests for CreateManifestFromSdk."""

    def setUp(self) -> None:
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

    def testSuccess(self) -> None:
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
        expected_json_input = (
            '{"version": "1", "packages": {"dev-python/django": '
            '[["1.5.12-r3", {}]], "dev-python/urllib3": [["1.25.10", {}]]}}'
        )
        write_file_patch.assert_called_with(
            expected_manifest_path,
            expected_json_input,
        )
        self.assertEqual(manifest_path, expected_manifest_path)


class CreateArgumentsTest(cros_test_lib.MockTestCase):
    """CreateArguments tests."""

    def _GetArgsList(self, **kwargs):
        """Helper to simplify getting the argument list."""
        self.PatchObject(
            cros_sdk_lib.SdkVersionConfig,
            "load",
            return_value=cros_sdk_lib.SdkVersionConfig(
                "LATEST_VER", "BOOTSTRAP_VER"
            ),
        )
        instance = sdk.CreateArguments(**kwargs)
        return instance.GetArgList()

    def testGetEntryArgList(self) -> None:
        """Test that GetEntryArgList contains all chroot-y locations."""

        # Check the other flags get added when the correct argument passed.
        self.assertListEqual(
            [
                "--chroot",
                constants.DEFAULT_CHROOT_PATH,
                "--out-dir",
                str(constants.DEFAULT_OUT_PATH),
                "--read-only",
                "--read-only-sticky",
                "--sdk-version",
                "foo",
            ],
            sdk.CreateArguments(
                sdk_version="foo",
                ccache_disable=True,
            ).GetEntryArgList(),
        )

    def testGetArgList(self) -> None:
        """Test the GetArgsList method."""
        self.assertIn("--replace", self._GetArgsList())

        # Check the variations of force.
        self.assertNotIn("--force", self._GetArgsList())
        self.assertIn("--force", self._GetArgsList(force=True))

        # Check the other flags get added when the correct argument passed.
        self.assertListEqual(
            [
                "--replace",
                "--delete-out-dir",
                "--chroot",
                constants.DEFAULT_CHROOT_PATH,
                "--out-dir",
                str(constants.DEFAULT_OUT_PATH),
                "--read-only",
                "--read-only-sticky",
                "--sdk-version",
                "foo",
            ],
            self._GetArgsList(sdk_version="foo"),
        )

        self.assertListEqual(
            [
                "--replace",
                "--delete-out-dir",
                "--chroot",
                constants.DEFAULT_CHROOT_PATH,
                "--out-dir",
                str(constants.DEFAULT_OUT_PATH),
                "--read-only",
                "--read-only-sticky",
                "--sdk-version",
                "BOOTSTRAP_VER",
            ],
            self._GetArgsList(bootstrap=True),
        )


class CreateBinhostCLsTest(cros_test_lib.RunCommandTestCase):
    """Tests for CreateBinhostCLs."""

    def testCreateBinhostCLs(self) -> None:
        def fake_run(cmd, *_args, **__kwargs) -> None:
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

        def mock_rev(filename, _data, report=None, *_args, **_kwargs) -> None:
            # binpkg.UpdateAndSubmitKeyValueFile() wants the filename to
            # be an absolute path, so fail if it isn't.
            self.assertTrue(os.path.isabs(filename))
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

    def testBuildSource(self) -> None:
        """Test the build_source argument."""
        args = self._GetArgList(build_source=True)
        self.assertIn("--nousepkg", args)
        self.assertNotIn("--usepkg", args)

    def testNoBuildSource(self) -> None:
        """Test using binpkgs."""
        args = self._GetArgList(build_source=False)
        self.assertNotIn("--nousepkg", args)
        self.assertIn("--usepkg", args)


class get_latest_version_test(cros_test_lib.MockTestCase):
    """Test case for get_latest_version()."""

    def testSuccess(self) -> None:
        """Test an ordinary, successful call."""
        expected_latest_version = "1970.01.01.000000"
        file_contents = f'LATEST_SDK="{expected_latest_version}"'.encode()
        cat_patch = self.PatchObject(
            gs.GSContext,
            "Cat",
            return_value=file_contents,
        )
        returned_version = sdk.get_latest_version()
        self.assertEqual(expected_latest_version, returned_version)
        cat_patch.assert_called_with("gs://chromiumos-sdk/cros-sdk-latest.conf")

    def testInvalidFileContents(self) -> None:
        """Test a response if the file contents are malformed."""
        file_contents = b"Latest SDK version: 1970.01.01.000000"
        self.PatchObject(gs.GSContext, "Cat", return_value=file_contents)
        with self.assertRaises(ValueError):
            sdk.get_latest_version()


class UnmountTest(
    cros_test_lib.RunCommandTempDirTestCase, cros_test_lib.MockTestCase
):
    """Unmount tests."""

    def testUnmountPath(self) -> None:
        self.PatchObject(osutils, "UmountTree", return_value=True)
        sdk.UnmountPath("/some/path")

    def testUnmountPathFails(self) -> None:
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


class CleanTest(cros_test_lib.RunCommandTestCase):
    """Delete function tests."""

    def testClean(self) -> None:
        """Test with chroot provided."""
        path = "/some/path"
        out_path = "/some/out"
        sdk.Clean(
            chroot=chroot_lib.Chroot(path, out_path=out_path),
            safe=True,
            sysroots=True,
        )
        self.assertCommandContains(["--safe", "--sysroots"])


class CreateTest(cros_test_lib.RunCommandTempDirTestCase):
    """Create function tests."""

    def testCreate(self) -> None:
        """Test the create function builds the command correctly."""
        arguments = sdk.CreateArguments()
        arguments.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        expected_args = ["--arg", "--other", "--with-value", "value"]
        expected_version = 1

        self.PatchObject(arguments, "GetArgList", return_value=expected_args)
        self.PatchObject(sdk, "GetChrootVersion", return_value=expected_version)
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        version = sdk.Create(arguments)
        self.assertEqual(expected_version, version)
        self.assertCommandContains(expected_args)

    def runCreateExtractingCcacheSetting(self, ccache_disable):
        """Run `sdk.Create`, extracting the ccache enable/disable command."""
        arguments = sdk.CreateArguments(ccache_disable=ccache_disable)
        arguments.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )

        expected_version = 1
        self.PatchObject(sdk, "GetChrootVersion", return_value=expected_version)
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        chroot_args = arguments.GetEntryArgList()
        version = sdk.Create(arguments)
        self.assertEqual(expected_version, version)

        found_ccache_setting = None
        for i, call_args in enumerate(self.rc.call_args_list):
            positionals = call_args.args[0]
            self.assertTrue(
                partial_mock.ListContains(
                    chroot_args, positionals, strict=True
                ),
                f"Call {positionals} (#{i+1}) does not contain {chroot_args}",
            )

            str_positionals = [x for x in positionals if isinstance(x, str)]
            if not any("CCACHE_DIR=" in x for x in str_positionals):
                continue

            ccache_setting = next(
                (
                    x
                    for x in reversed(str_positionals)
                    if x.startswith("--set-config=disable=")
                ),
                None,
            )

            if not ccache_setting:
                continue

            self.assertIsNone(
                found_ccache_setting,
                f"Found multiple ccache commands in {self.rc.call_args_list}",
            )
            found_ccache_setting = ccache_setting

        self.assertIsNotNone(
            found_ccache_setting,
            f"No ccache invocation found in any of {self.rc.call_args_list}",
        )
        return found_ccache_setting

    def testDisablingCcacheWorks(self) -> None:
        """Ensure we issue a ccache disable command if it's requested."""
        ccache_setting = self.runCreateExtractingCcacheSetting(
            ccache_disable=True
        )
        self.assertIn("disable=true", ccache_setting)

    def testCcacheIsReenabledIfDisablingIsntRequested(self) -> None:
        """Ensure we issue a ccache enable command if it's requested."""
        ccache_setting = self.runCreateExtractingCcacheSetting(
            ccache_disable=False
        )
        self.assertIn("disable=false", ccache_setting)

    def testCreateInsideFails(self) -> None:
        """Test Create raises an error when called inside the chroot."""
        # Make sure it fails inside the chroot.
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=True)
        arguments = sdk.CreateArguments()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            sdk.Create(arguments)


class DeleteTest(cros_test_lib.RunCommandTestCase):
    """Delete function tests."""

    def testDeleteNoChroot(self) -> None:
        """Test no chroot provided."""
        sdk.Delete()
        # cros_sdk --delete.
        self.assertCommandContains(["--delete"])
        # No chroot specified for cros_sdk --delete.
        self.assertCommandContains(["--chroot"], expected=False)

    def testDeleteWithChroot(self) -> None:
        """Test with chroot provided."""
        path = "/some/path"
        out_path = "/some/out"
        sdk.Delete(chroot=chroot_lib.Chroot(path, out_path=out_path))
        self.assertCommandContains(["--delete", "--chroot", path])

    def testDeleteWithChrootAndForce(self) -> None:
        """Test with chroot and force provided."""
        path = "/some/path"
        out_path = "/some/out"
        sdk.Delete(
            chroot=chroot_lib.Chroot(path, out_path=out_path), force=True
        )
        self.assertCommandContains(["--delete", "--force", "--chroot", path])


class UpdateTest(
    cros_test_lib.RunCommandTempDirTestCase, cros_test_lib.LoggingTestCase
):
    """Update function tests."""

    def setUp(self) -> None:
        # Needs to be run inside the chroot right now.
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=True)
        # Don't bother trying to remount root read-write.
        self.PatchObject(osutils, "IsMountedReadOnly", return_value=False)
        # Avoid any logging functions that inpsect or change filesystem state.
        self.PatchObject(osutils, "rotate_log_file")

    def testSuccess(self) -> None:
        """Test the simple success case."""
        arguments = sdk.UpdateArguments(root=self.tempdir)
        expected_args = ["--arg", "--other", "--with-value", "value"]
        expected_version = 1
        self.PatchObject(arguments, "GetArgList", return_value=expected_args)
        self.PatchObject(sdk, "GetChrootVersion", return_value=expected_version)

        response = sdk.Update(arguments)
        version = response.version

        self.assertCommandContains(expected_args)
        self.assertEqual(expected_version, version)

    def testPackageFailure(self) -> None:
        """Test non-zero return code and failed package handling."""
        pkgs = [package_info.parse(p) for p in ["foo/bar", "cat/pkg"]]
        self.PatchObject(
            portage_util, "ParseDieHookStatusFile", return_value=pkgs
        )
        expected_rc = 1
        self.rc.AddCmdResult(
            partial_mock.In(
                str(constants.CHROMITE_SHELL_DIR / "update_chroot.sh")
            ),
            returncode=expected_rc,
        )

        result = sdk.Update(sdk.UpdateArguments())
        self.assertFalse(result.success)
        self.assertEqual(expected_rc, result.return_code)
        self.assertCountEqual(pkgs, result.failed_pkgs)

    def testLoggingPortageBinhosts(self) -> None:
        """Test logging portage binhosts."""
        self.PatchObject(
            binhost,
            "GetHostBinhosts",
            return_value=["gs://binhost1", "gs://binhost2"],
        )
        with cros_test_lib.LoggingCapturer() as logs:
            sdk.Update(sdk.UpdateArguments(use_snapshot_binhosts=True))

            self.AssertLogsContain(
                logs,
                "PORTAGE_BINHOST: gs://binhost1 gs://binhost2",
            )

        self.PatchObject(binhost, "GetHostBinhosts", return_value=[])
        with cros_test_lib.LoggingCapturer() as logs:
            sdk.Update(sdk.UpdateArguments())

            self.AssertLogsContain(
                logs,
                "PORTAGE_BINHOST: ",
            )

    def _find_toolchain_call(self) -> Optional[Tuple]:
        """Find the cros_setup_toolchains call."""
        for call_args, call_kwargs in self.rc.call_args_list:
            if (
                constants.CHROMITE_BIN_DIR / "cros_setup_toolchains"
                in call_args[0]
            ):
                return call_args, call_kwargs
        return None

    def testToolchainUpdate(self) -> None:
        """Test toolchain updates are handled correctly."""
        sdk.Update(sdk.UpdateArguments(update_toolchain=True))
        call = self._find_toolchain_call()
        assert call is not None

    def testNoToolchainUpdate(self) -> None:
        """Test skipping toolchain updates are handled correctly."""
        self.rc.AddCmdResult(
            partial_mock.In(
                str(constants.CHROMITE_BIN_DIR / "cros_setup_toolchains")
            ),
            returncode=1,
        )
        sdk.Update(sdk.UpdateArguments(update_toolchain=False))
        call = self._find_toolchain_call()
        assert call is None


class BuildSdkToolchainTest(cros_test_lib.RunCommandTestCase):
    """Test the implementation of BuildSdkToolchain()."""

    _filenames_to_find = ["foo.tar.gz", "bar.txt"]
    _toolchain_dir = os.path.join("/", constants.SDK_TOOLCHAINS_OUTPUT)

    @property
    def _expected_generated_files(self) -> List[common_pb2.Path]:
        return [
            common_pb2.Path(
                path=os.path.join(self._toolchain_dir, filename),
                location=common_pb2.Path.INSIDE,
            )
            for filename in BuildSdkToolchainTest._filenames_to_find
        ]

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=True)

    def test_success(self) -> None:
        """Check that a standard call performs expected logic.

        Look for the following behavior:
        1. Call `cros_setup_toolchain --nousepkg`
        2. Clear any existing files in the output dir
        3. Call `cros_setup_toolchain --debug --create-packages --output-dir`
        4. Return any generated filepaths
        """
        # Arrange
        rmdir_patch = self.PatchObject(osutils, "RmDir")
        listdir_patch = self.PatchObject(os, "listdir")
        listdir_patch.return_value = self._filenames_to_find

        # Act
        generated_files = sdk.BuildSdkToolchain()

        # Assert
        self.assertCommandCalled(
            ["sudo", "--", "cros_setup_toolchains", "--nousepkg", "--debug"],
        )
        rmdir_patch.assert_any_call(
            self._toolchain_dir,
            ignore_missing=True,
            sudo=True,
        )
        self.assertCommandCalled(
            [
                "sudo",
                "--",
                "cros_setup_toolchains",
                "--debug",
                "--create-packages",
                "--output-dir",
                self._toolchain_dir,
            ],
        )
        self.assertEqual(generated_files, self._expected_generated_files)

    def test_success_with_use_flags(self) -> None:
        """Check that a standard call with USE flags performs expected logic.

        The call to `cros_setup_toolchain --nousepkg` should use the USE flag.
        However, the call to `cros_setup_toolchain ... --create-packages ...`
        should NOT use the USE flag.
        """
        # Arrange
        rmdir_patch = self.PatchObject(osutils, "RmDir")
        listdir_patch = self.PatchObject(os, "listdir")
        listdir_patch.return_value = self._filenames_to_find

        # Act
        found_files = sdk.BuildSdkToolchain(extra_env={"USE": "llvm-next"})

        # Assert
        self.assertCommandCalled(
            [
                "sudo",
                "USE=llvm-next",
                "--",
                "cros_setup_toolchains",
                "--nousepkg",
                "--debug",
            ],
        )
        rmdir_patch.assert_any_call(
            self._toolchain_dir, ignore_missing=True, sudo=True
        )
        self.assertCommandCalled(
            [
                "sudo",
                "--",
                "cros_setup_toolchains",
                "--debug",
                "--create-packages",
                "--output-dir",
                self._toolchain_dir,
            ],
        )
        self.assertEqual(found_files, self._expected_generated_files)


class UploadPrebuiltPackagesTest(cros_test_lib.RunCommandTestCase):
    """Test case for sdk.UploadPrebuiltPackages()."""

    def test_runs_script_with_expected_args(self) -> None:
        """Check that the expected arguments and values are passed."""

        # Arrange
        chroot = chroot_lib.Chroot("/test/chroot", out_path="/test/out")
        expected_binhost_conf_dir = os.path.join(
            constants.SOURCE_ROOT,
            constants.PUBLIC_BINHOST_CONF_DIR,
        )
        expected_prepackaged_tarball = os.path.join(
            constants.SOURCE_ROOT,
            constants.SDK_TARBALL_NAME,
        )
        expected_parts = [
            ["--sync-host"],
            ["--build-path", constants.SOURCE_ROOT],
            ["--chroot", "/test/chroot"],
            ["--out-dir", "/test/out"],
            ["--board", "amd64-host"],
            ["--set-version", "19691231"],
            ["--prepend-version", "upptest"],
            ["--upload", "gs://upptest"],
            ["--binhost-conf-dir", expected_binhost_conf_dir],
            ["--upload-board-tarball"],
            ["--prepackaged-tarball", expected_prepackaged_tarball],
            ["--no-sync-remote-latest-sdk-file"],
        ]

        # Act
        sdk.UploadPrebuiltPackages(
            chroot=chroot,
            prepend_version="upptest",
            version="19691231",
            upload_location="gs://upptest",
        )

        # Assert
        for part in expected_parts:
            self.assertCommandContains(part)


class UprevSdkAndPrebuiltsTest(cros_test_lib.MockTestCase):
    """Test case for sdk.UprevSdkAndPrebuilts()."""

    # The old version, which applies to both the SDK and prebuilt.
    _old_version = "2021.01.01.111111"

    # Values interpolated into the old SDK version file.
    # Note: The "%(target)s" here is expected in the actual SDK version file.
    _old_tc_path = "2021/01/%(target)s-2021.01.01.111111"
    _old_bootstrap_version = "2020.00.00.000000"
    _old_sdk_bucket = "old-chromiumos-sdk"

    # Contents of the SDK version file. Intended to be %-interpolated.
    _sdk_version_file_template = """# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# The latest version of the SDK that we built & tested.
SDK_LATEST_VERSION="%(sdk_version)s"

# How to find the standalone toolchains from the above sdk.
TC_PATH="%(tc_path)s"

# Frozen version of SDK used for bootstrapping.
# If unset, SDK_LATEST_VERSION will be used for bootstrapping.
BOOTSTRAP_FROZEN_VERSION="%(bootstrap_version)s"

# The Google Storage bucket containing the SDK tarball and toolchains.
# If empty, Chromite will assume a default value, likely "chromiumos-sdk".
SDK_BUCKET="%(sdk_bucket)s"
"""

    # Contents of the host prebuilt file. Intended to be %-interpolated.
    _prebuilt_file_template = (
        'FULL_BINHOST="gs://chromeos-prebuilt/board/amd64-host/'
        'chroot-%(version)s/packages/"\n'
    )

    # Contents of make.conf.amd64-host. Intended to be %-interpolated.
    # pylint: disable=line-too-long
    _make_conf_amd64_template = """# See "man make.conf" for the available options.

# Common settings across all sdks.
source /mnt/host/source/src/third_party/chromiumos-overlay/chromeos/config/make.conf.common

# Pull in definition of at least { CHOST, [BOARD_OVERLAY] }
source make.conf.board_setup

# We initialize PORTDIR_OVERLAY here to clobber any redefinitions elsewhere.
# This has to be the first overlay so crossdev finds the correct gcc and
# glibc ebuilds.
PORTDIR_OVERLAY="
  /usr/local/portage/crossdev
  /mnt/host/source/src/third_party/toolchains-overlay
  /mnt/host/source/src/third_party/chromiumos-overlay
  /mnt/host/source/src/third_party/eclass-overlay
  /mnt/host/source/src/overlays/overlay-amd64-host
"

# Where to store built packages.
PKGDIR="/var/lib/portage/pkgs"

PORT_LOGDIR="/var/log/portage"

FULL_BINHOST="gs://chromeos-prebuilt/host/amd64/amd64-host/chroot-%(version)s/packages/"
PORTAGE_BINHOST="$FULL_BINHOST"

GENTOO_MIRRORS="https://commondatastorage.googleapis.com/chromeos-localmirror"
GENTOO_MIRRORS="$GENTOO_MIRRORS https://commondatastorage.googleapis.com/chromeos-mirror/gentoo"

# Remove all .la files for non-plugin libraries.
# Remove Gentoo init files since we use upstart.
# Remove logrotate.d files since we don't use logrotate.
INSTALL_MASK="
  /usr/lib*/*.la
  /etc/init.d /etc/conf.d
  /etc/logrotate.d
"
PKG_INSTALL_MASK="${INSTALL_MASK}"

source make.conf.host_setup
"""

    def setUp(self) -> None:
        self._write_file_patch = self.PatchObject(osutils, "WriteFile")

        def _read_text_response(filepath: str) -> str:
            """Mock responses for osutils.ReadText based on input filepath."""
            self.assertIn(
                filepath.name,
                ("sdk_version.conf", "prebuilt.conf", "make.conf.amd64-host"),
            )
            if filepath.name == "sdk_version.conf":
                return self._sdk_version_file_template % {
                    "sdk_version": self._old_version,
                    "tc_path": self._old_tc_path,
                    "bootstrap_version": self._old_bootstrap_version,
                    "sdk_bucket": self._old_sdk_bucket,
                }
            if filepath.name == "prebuilt.conf":
                return self._prebuilt_file_template % {
                    "version": self._old_version
                }
            if filepath.name == "make.conf.amd64-host":
                return self._make_conf_amd64_template % {
                    "version": self._old_version
                }
            raise ValueError(f"Unexpected path in mock ReadText: {filepath}")

        self.PatchObject(osutils, "ReadText", side_effect=_read_text_response)

    def test_noop(self) -> None:
        """Test trying to update to the existing version."""
        modified_paths = sdk.uprev_sdk_and_prebuilts(
            self._old_version,
            self._old_tc_path,
            "gs://chromeos-prebuilt",
        )
        self.assertEqual(modified_paths, [])

    def _test_update(
        self,
        input_prebuilts_bucket: str,
        input_sdk_bucket: Optional[str],
        expected_new_sdk_bucket: str,
    ) -> None:
        """Test making a genuine update.

        Args:
            input_prebuilts_bucket: The value to pass into
                uprev_sdk_and_prebuilts for the "prebuilts_gs_bucket" arg
            input_sdk_bucket: The value to pass into uprev_sdk_and_prebuilts for
                the "sdk_gs_bucket" kwarg.
            expected_new_sdk_bucket: The value that we expect to see written
                to the new file.
        """
        new_version = "2022.02.02.222222"
        new_tc_path = "path/to/%(target)s/toolchain.tar.xz"
        modified_paths = sdk.uprev_sdk_and_prebuilts(
            new_version,
            new_tc_path,
            input_prebuilts_bucket,
            sdk_gs_bucket=input_sdk_bucket,
        )
        self.assertCountEqual(
            modified_paths,
            [
                constants.SDK_VERSION_FILE_FULL_PATH,
                constants.HOST_PREBUILT_CONF_FILE_FULL_PATH,
                constants.MAKE_CONF_AMD64_HOST_FILE_FULL_PATH,
            ],
        )
        self._write_file_patch.assert_any_call(
            constants.SDK_VERSION_FILE_FULL_PATH,
            self._sdk_version_file_template
            % {
                "sdk_version": new_version,
                "tc_path": new_tc_path,
                "bootstrap_version": self._old_bootstrap_version,
                "sdk_bucket": expected_new_sdk_bucket,
            },
        )
        self._write_file_patch.assert_any_call(
            constants.HOST_PREBUILT_CONF_FILE_FULL_PATH,
            self._prebuilt_file_template % {"version": new_version},
        )
        self._write_file_patch.assert_any_call(
            constants.MAKE_CONF_AMD64_HOST_FILE_FULL_PATH,
            self._make_conf_amd64_template % {"version": new_version},
        )

    def test_update_where_sdk_bucket_is_none(self) -> None:
        """Test making an update without changing the SDK bucket."""
        self._test_update("gs://chromeos-prebuilt", None, self._old_sdk_bucket)

    def test_update_where_sdk_bucket_is_empty_string(self) -> None:
        """Test making an update, setting the SDK bucket to "".

        This test case is intended to catch any code that checks whether
        SDK_BUCKET is falsey. The empty string is a meaningful value, distinct
        from None.
        """
        self._test_update("gs://chromeos-prebuilt", "", "")

    def test_update_where_buckets_have_prefix(self) -> None:
        """Test an update where the SDK and prebuilt buckets start with gs://.

        We expect the gs:// prefix to be stripped.
        """
        self._test_update(
            "gs://chromeos-prebuilt",
            "gs://new-chromiumos-sdk",
            "new-chromiumos-sdk",
        )

    def test_update_where_sdk_bucket_has_no_prefix(self) -> None:
        """Test an update where the buckets have no gs:// prefix."""
        self._test_update(
            "chromeos-prebuilt", "new-chromiumos-sdk", "new-chromiumos-sdk"
        )

    def test_update_sdk_bucket_to_default_value(self) -> None:
        self._test_update("chromeos-prebuilt", "chromiumos-sdk", "")


class UprevToolchainVirtualsSdkTest(cros_test_lib.MockTempDirTestCase):
    """Tests for `uprev_toolchain_virtuals`."""

    def write_versions(
        self,
        dev_lang_rust_versions: List[str],
        virtual_rust_versions: List[str],
        saved_virtual_rust_versions: Optional[List[str]] = None,
    ) -> Path:
        """Writes the given virtual versions for testing.

        Args:
            dev_lang_rust_versions: versions of dev-lang/rust files to create.
            virtual_rust_versions: versions of virtual/rust files to create.
            saved_virtual_rust_versions: versions of dev-lang/rust to write
                into `virtual_rust_versions`. If `None` is given, this is
                inferred to be "whatever the virtual_rust_versions are." If a
                list is given, it must be the same length as
                `virtual_rust_versions`. Those versions are written into their
                corresponding virtual/rust ebuilds.
        """
        if saved_virtual_rust_versions:
            assert len(saved_virtual_rust_versions) == len(
                virtual_rust_versions
            )
            write_virtual_rust_versions = saved_virtual_rust_versions
        else:
            write_virtual_rust_versions = virtual_rust_versions

        chromiumos_overlay = self.tempdir
        dev_lang_rust = chromiumos_overlay / "dev-lang" / "rust"
        dev_lang_rust.mkdir(parents=True)
        for ver in dev_lang_rust_versions:
            (dev_lang_rust / f"rust-{ver}.ebuild").touch()

        virtual_rust = chromiumos_overlay / "virtual" / "rust"
        virtual_rust.mkdir(parents=True)
        for ver, write_ver in zip(
            virtual_rust_versions, write_virtual_rust_versions
        ):
            (virtual_rust / f"rust-{ver}.ebuild").write_text(
                textwrap.dedent(
                    f"""\
                    # Foo
                    # Corresponding package version: dev-lang/rust-{write_ver}
                    # Bar
                    baz
                    """
                ),
                encoding="utf-8",
            )
        return chromiumos_overlay

    def test_nop_update(self):
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.77.0"],
            virtual_rust_versions=["1.77.0"],
        )
        updated_files = sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        self.assertEqual(updated_files, [])

    def test_revision_upgrade(self):
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.77.0-r1"],
            virtual_rust_versions=["1.77.0"],
        )
        updated_files = sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        new_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r1.ebuild"
        )
        old_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0.ebuild"
        )
        self.assertEqual(updated_files, [new_virtual])
        self.assertFalse(old_virtual.exists())
        self.assertTrue(new_virtual.exists())

    def test_highest_is_picked_of_multiple_versions(self):
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.77.0", "1.77.0-r3"],
            virtual_rust_versions=["1.77.0", "1.77.0-r2"],
        )
        updated_files = sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        new_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r3.ebuild"
        )
        old_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r2.ebuild"
        )
        self.assertEqual(updated_files, [new_virtual])
        self.assertFalse(old_virtual.exists())
        self.assertTrue(new_virtual.exists())

    def test_9999_ebuild_is_ignored(self):
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.77.0", "1.77.0-r3", "9999"],
            virtual_rust_versions=["1.77.0", "1.77.0-r2"],
        )
        updated_files = sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        new_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r3.ebuild"
        )
        old_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r2.ebuild"
        )
        self.assertEqual(updated_files, [new_virtual])
        self.assertFalse(old_virtual.exists())
        self.assertTrue(new_virtual.exists())

    def test_virtual_rev_is_bumped_if_version_equality_is_downgrade(self):
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.77.0-r5", "9999"],
            virtual_rust_versions=["1.77.0-r6"],
            saved_virtual_rust_versions=["1.77.0-r4"],
        )
        updated_files = sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        new_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r7.ebuild"
        )
        old_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r6.ebuild"
        )
        self.assertEqual(updated_files, [new_virtual])
        self.assertFalse(old_virtual.exists())
        self.assertTrue(new_virtual.exists())
        self.assertIn(
            "dev-lang/rust-1.77.0-r5", new_virtual.read_text(encoding="utf-8")
        )

    def test_virtual_revision_is_lowered_if_version_equality_is_upgrade(self):
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.80.0-r1", "9999"],
            virtual_rust_versions=["1.77.0-r6"],
            saved_virtual_rust_versions=["1.77.0-r4"],
        )
        updated_files = sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        new_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.80.0-r1.ebuild"
        )
        old_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.77.0-r6.ebuild"
        )
        self.assertEqual(updated_files, [new_virtual])
        self.assertFalse(old_virtual.exists())
        self.assertTrue(new_virtual.exists())
        self.assertIn(
            "dev-lang/rust-1.80.0-r1", new_virtual.read_text(encoding="utf-8")
        )

    def test_virtual_ebuild_writing_only_replaces_version(self):
        # There's some manual string slicing, so ensure that the virtual rust
        # ebuild remains intact across version string updates.
        chromiumos_overlay = self.write_versions(
            dev_lang_rust_versions=["1.80.0-r1", "9999"],
            virtual_rust_versions=["1.77.0-r4"],
        )
        sdk.uprev_toolchain_virtuals(chromiumos_overlay)
        new_virtual = (
            chromiumos_overlay / "virtual" / "rust" / "rust-1.80.0-r1.ebuild"
        )
        self.assertEqual(
            new_virtual.read_text(encoding="utf-8"),
            textwrap.dedent(
                """\
                # Foo
                # Corresponding package version: dev-lang/rust-1.80.0-r1
                # Bar
                baz
                """
            ),
        )
