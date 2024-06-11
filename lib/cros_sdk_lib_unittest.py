# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the cros_sdk_lib module."""

import contextlib
import io
import os
from pathlib import Path
import stat
from typing import Optional
from unittest import mock
import urllib.request

import pytest

from chromite.lib import chroot_lib
from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import retry_util


# pylint: disable=protected-access


class VersionHookTestCase(cros_test_lib.TempDirTestCase):
    """Class to set up tests that use the version hooks."""

    def setUp(self) -> None:
        # Build set of expected scripts.
        self.ExpectRootOwnedFiles()
        D = cros_test_lib.Directory
        filesystem = (
            D(
                "hooks",
                (
                    "8_invalid_gap",
                    "10_run_success",
                    "11_run_success",
                    "12_run_success",
                ),
            ),
            "version_file",
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, filesystem)

        self.chroot_path = os.path.join(self.tempdir, "chroot")
        self.version_file = os.path.join(
            self.chroot_path, cros_sdk_lib.CHROOT_VERSION_FILE.lstrip(os.sep)
        )
        osutils.WriteFile(self.version_file, "0", makedirs=True, sudo=True)
        self.hooks_dir = os.path.join(self.tempdir, "hooks")

        self.earliest_version = 8
        self.latest_version = 12
        self.deprecated_versions = (6, 7, 8)
        self.invalid_versions = (13,)
        self.success_versions = (9, 10, 11, 12)


class TestVersionConfig:
    """Test SdkVersionConfig container."""

    @pytest.mark.parametrize(
        ["latest_version", "bootstrap_version", "bootstrap", "expected_value"],
        [
            ("123", None, False, "123"),
            ("123", None, True, "123"),
            ("123", "122", False, "123"),
            ("123", "122", True, "122"),
        ],
    )
    def test_default_version(
        self,
        latest_version: str,
        bootstrap_version: Optional[str],
        bootstrap: bool,
        expected_value: str,
    ) -> None:
        """Test get_default_version method."""
        assert (
            cros_sdk_lib.SdkVersionConfig(
                latest_version=latest_version,
                bootstrap_version=bootstrap_version,
            ).get_default_version(bootstrap=bootstrap)
            == expected_value
        )

    @pytest.mark.parametrize(
        ["contents", "expected_value"],
        [
            (
                'SDK_LATEST_VERSION="123"\n',
                cros_sdk_lib.SdkVersionConfig(latest_version="123"),
            ),
            (
                'SDK_LATEST_VERSION="123"\nFROZEN_BOOTSTRAP_VERSION="122"\n',
                cros_sdk_lib.SdkVersionConfig(
                    latest_version="123", bootstrap_version="122"
                ),
            ),
            (
                """\
SDK_LATEST_VERSION="123"
FROZEN_BOOTSTRAP_VERSION="122"
SDK_BUCKET="foo"
""",
                cros_sdk_lib.SdkVersionConfig(
                    latest_version="123", bootstrap_version="122", bucket="foo"
                ),
            ),
        ],
    )
    def test_parse_file(
        self, contents: str, expected_value: cros_sdk_lib.SdkVersionConfig
    ):
        assert (
            cros_sdk_lib.SdkVersionConfig.from_file(io.StringIO(contents))
            == expected_value
        )


class TestGetFileSystemDebug(cros_test_lib.RunCommandTestCase):
    """Tests GetFileSystemDebug functionality."""

    def testNoPs(self) -> None:
        """Verify with run_ps=False."""
        self.rc.AddCmdResult(
            ["sudo", "--", "fuser", "/some/path"], stdout="fuser_output"
        )
        self.rc.AddCmdResult(
            ["sudo", "--", "lsof", "/some/path"], stdout="lsof_output"
        )
        file_system_debug_tuple = cros_sdk_lib.GetFileSystemDebug(
            "/some/path", run_ps=False
        )
        self.assertEqual(file_system_debug_tuple.fuser, "fuser_output")
        self.assertEqual(file_system_debug_tuple.lsof, "lsof_output")
        self.assertIsNone(file_system_debug_tuple.ps)

    def testWithPs(self) -> None:
        """Verify with run_ps=False."""
        self.rc.AddCmdResult(
            ["sudo", "--", "fuser", "/some/path"], stdout="fuser_output"
        )
        self.rc.AddCmdResult(
            ["sudo", "--", "lsof", "/some/path"], stdout="lsof_output"
        )
        self.rc.AddCmdResult(["ps", "auxf"], stdout="ps_output")
        file_system_debug_tuple = cros_sdk_lib.GetFileSystemDebug(
            "/some/path", run_ps=True
        )
        self.assertEqual(file_system_debug_tuple.fuser, "fuser_output")
        self.assertEqual(file_system_debug_tuple.lsof, "lsof_output")
        self.assertEqual(file_system_debug_tuple.ps, "ps_output")


class TestMountChrootPaths(cros_test_lib.MockTempDirTestCase):
    """Tests MountChrootPaths functionality."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        chroot_path = self.tempdir / "chroot"
        out_path = self.tempdir / "out"
        self.chroot = chroot_lib.Chroot(path=chroot_path, out_path=out_path)
        osutils.SafeMakedirsNonRoot(self.chroot.path)
        osutils.SafeMakedirsNonRoot(self.chroot.out_path)

        osutils.WriteFile(
            chroot_path / "etc" / "passwd", "passwd contents", makedirs=True
        )
        osutils.WriteFile(
            chroot_path / "etc" / "group", "group contents", makedirs=True
        )
        osutils.WriteFile(
            chroot_path / "etc" / "shadow", "shadow contents", makedirs=True
        )

        self.mount_mock = self.PatchObject(osutils, "Mount")

    def testMounts(self) -> None:
        cros_sdk_lib.MountChrootPaths(self.chroot)

        self.mount_mock.assert_has_calls(
            [
                mock.call(
                    Path(self.chroot.path),
                    Path(self.chroot.path),
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "tmp",
                    Path(self.chroot.path) / "tmp",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "home",
                    Path(self.chroot.path) / "home",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "build",
                    Path(self.chroot.path) / "build",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "bin",
                    Path(self.chroot.path) / "usr" / "local" / "bin",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "cache",
                    Path(self.chroot.path) / "var" / "cache",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "run",
                    Path(self.chroot.path) / "run",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "logs",
                    Path(self.chroot.path) / "var" / "log",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "tmp",
                    Path(self.chroot.path) / "var" / "tmp",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    "proc", Path(self.chroot.path) / "proc", "proc", mock.ANY
                ),
                mock.call(
                    "sysfs", Path(self.chroot.path) / "sys", "sysfs", mock.ANY
                ),
                mock.call(
                    "/dev",
                    Path(self.chroot.path) / "dev",
                    None,
                    osutils.MS_BIND | osutils.MS_REC,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "passwd",
                    Path(self.chroot.path) / "etc" / "passwd",
                    None,
                    osutils.MS_BIND,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "group",
                    Path(self.chroot.path) / "etc" / "group",
                    None,
                    osutils.MS_BIND,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "shadow",
                    Path(self.chroot.path) / "etc" / "shadow",
                    None,
                    osutils.MS_BIND,
                ),
            ],
            any_order=True,
        )

    def testPasswdExists(self) -> None:
        """If out/ already has passwd contents, we should still mount OK."""
        osutils.WriteFile(
            self.chroot.out_path / "sdk" / "passwd",
            "preexisting passwd",
            makedirs=True,
        )

        cros_sdk_lib.MountChrootPaths(self.chroot)

        self.assertEqual(
            "preexisting passwd",
            osutils.ReadFile(self.chroot.out_path / "sdk" / "passwd"),
        )

        self.mount_mock.assert_has_calls(
            [
                mock.call(
                    self.chroot.out_path / "sdk" / "passwd",
                    Path(self.chroot.path) / "etc" / "passwd",
                    None,
                    osutils.MS_BIND,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "group",
                    Path(self.chroot.path) / "etc" / "group",
                    None,
                    osutils.MS_BIND,
                ),
                mock.call(
                    self.chroot.out_path / "sdk" / "shadow",
                    Path(self.chroot.path) / "etc" / "shadow",
                    None,
                    osutils.MS_BIND,
                ),
            ],
            any_order=True,
        )

    def testTmpPermissions(self) -> None:
        cros_sdk_lib.MountChrootPaths(self.chroot)

        self.assertEqual(
            0o1777, stat.S_IMODE(os.stat(self.chroot.out_path / "tmp").st_mode)
        )


class TestGetChrootVersion(cros_test_lib.MockTestCase):
    """Tests GetChrootVersion functionality."""

    def testNoChroot(self) -> None:
        """Verify we don't blow up when there is no chroot yet."""
        self.PatchObject(
            cros_sdk_lib.ChrootUpdater, "GetVersion", side_effect=IOError()
        )
        self.assertIsNone(cros_sdk_lib.GetChrootVersion("/.$om3/place/nowhere"))


class TestChrootVersionValid(VersionHookTestCase):
    """Test valid chroot version method."""

    def testLowerVersionValid(self) -> None:
        """Lower versions are considered valid."""
        osutils.WriteFile(
            self.version_file, str(self.latest_version - 1), sudo=True
        )
        self.assertTrue(
            cros_sdk_lib.IsChrootVersionValid(self.chroot_path, self.hooks_dir)
        )

    def testLatestVersionValid(self) -> None:
        """Test latest version."""
        osutils.WriteFile(
            self.version_file, str(self.latest_version), sudo=True
        )
        self.assertTrue(
            cros_sdk_lib.IsChrootVersionValid(self.chroot_path, self.hooks_dir)
        )

    def testInvalidVersion(self) -> None:
        """Test version higher than latest."""
        osutils.WriteFile(
            self.version_file, str(self.latest_version + 1), sudo=True
        )
        self.assertFalse(
            cros_sdk_lib.IsChrootVersionValid(self.chroot_path, self.hooks_dir)
        )


class TestLatestChrootVersion(VersionHookTestCase):
    """LatestChrootVersion tests."""

    def testLatest(self) -> None:
        """Test latest version."""
        self.assertEqual(
            self.latest_version,
            cros_sdk_lib.LatestChrootVersion(self.hooks_dir),
        )


class TestEarliestChrootVersion(VersionHookTestCase):
    """EarliestChrootVersion tests."""

    def testEarliest(self) -> None:
        """Test earliest version."""
        self.assertEqual(
            self.earliest_version,
            cros_sdk_lib.EarliestChrootVersion(self.hooks_dir),
        )


class TestIsChrootReady(cros_test_lib.MockTestCase):
    """Tests IsChrootReady functionality."""

    def setUp(self) -> None:
        self.version_mock = self.PatchObject(cros_sdk_lib, "GetChrootVersion")

    def testMissing(self) -> None:
        """Check behavior w/out a chroot."""
        self.version_mock.return_value = None
        self.assertFalse(cros_sdk_lib.IsChrootReady("/"))

    def testNotSetup(self) -> None:
        """Check behavior w/an existing uninitialized chroot."""
        self.version_mock.return_value = 0
        self.assertFalse(cros_sdk_lib.IsChrootReady("/"))

    def testUpToDate(self) -> None:
        """Check behavior w/a valid chroot."""
        self.version_mock.return_value = 123
        self.assertTrue(cros_sdk_lib.IsChrootReady("/"))


class TestCleanupChroot(cros_test_lib.MockTempDirTestCase):
    """Tests the CleanupChroot function."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        osutils.SafeMakedirsNonRoot(self.chroot.path)
        osutils.SafeMakedirsNonRoot(self.chroot.out_path)

    def testCleanup(self) -> None:
        m = self.PatchObject(osutils, "RmDir")

        cros_sdk_lib.CleanupChroot(self.chroot)

        m.assert_any_call(self.chroot.path, ignore_missing=True, sudo=True)
        m.assert_any_call(self.chroot.out_path, ignore_missing=True, sudo=True)

    def testCleanupNoDeleteOut(self) -> None:
        m = self.PatchObject(osutils, "RmDir")

        cros_sdk_lib.CleanupChroot(self.chroot, delete_out=False)

        m.assert_called_with(self.chroot.path, ignore_missing=True, sudo=True)


class ChrootUpdaterTest(cros_test_lib.MockTestCase, VersionHookTestCase):
    """ChrootUpdater tests."""

    def setUp(self) -> None:
        self.chroot = cros_sdk_lib.ChrootUpdater(
            version_file=self.version_file, hooks_dir=self.hooks_dir
        )

    def testVersion(self) -> None:
        """Test the version property logic."""
        # Testing default value.
        self.assertEqual(0, self.chroot.GetVersion())

        # Test setting the version.
        self.chroot.SetVersion(5)
        self.assertEqual(5, self.chroot.GetVersion())
        self.assertEqual("5", osutils.ReadFile(self.version_file))

        # The current behavior is that outside processes writing to the file
        # does not affect our view after we've already read it. This shouldn't
        # generally be a problem since run_chroot_version_hooks should be the
        # only process writing to it.
        osutils.WriteFile(self.version_file, "10", sudo=True)
        self.assertEqual(5, self.chroot.GetVersion())

    def testInvalidVersion(self) -> None:
        """Test invalid version file contents."""
        osutils.WriteFile(self.version_file, "invalid", sudo=True)
        with self.assertRaises(cros_sdk_lib.InvalidChrootVersionError):
            self.chroot.GetVersion()

    def testMissingFileVersion(self) -> None:
        """Test missing version file."""
        osutils.SafeUnlink(self.version_file, sudo=True)
        with self.assertRaises(cros_sdk_lib.UninitializedChrootError):
            self.chroot.GetVersion()

    def testLatestVersion(self) -> None:
        """Test the latest_version property/_LatestScriptsVersion method."""
        self.assertEqual(self.latest_version, self.chroot.latest_version)

    def testGetChrootUpdates(self) -> None:
        """Test GetChrootUpdates."""
        # Test the deprecated error conditions.
        for version in self.deprecated_versions:
            self.chroot.SetVersion(version)
            with self.assertRaises(cros_sdk_lib.ChrootDeprecatedError):
                self.chroot.GetChrootUpdates()

    def testMultipleUpdateFiles(self) -> None:
        """Test handling of multiple files existing for a single version."""
        # When the version would be run.
        osutils.WriteFile(os.path.join(self.hooks_dir, "10_duplicate"), "")

        self.chroot.SetVersion(9)
        with self.assertRaises(cros_sdk_lib.VersionHasMultipleHooksError):
            self.chroot.GetChrootUpdates()

        # When the version would not be run.
        self.chroot.SetVersion(11)
        with self.assertRaises(cros_sdk_lib.VersionHasMultipleHooksError):
            self.chroot.GetChrootUpdates()

    def testApplyUpdates(self) -> None:
        """Test ApplyUpdates."""
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc_mock.SetDefaultCmdResult()
        for version in self.success_versions:
            self.chroot.SetVersion(version)
            self.chroot.ApplyUpdates()
            self.assertEqual(self.latest_version, self.chroot.GetVersion())

    def testApplyInvalidUpdates(self) -> None:
        """Test the invalid version conditions for ApplyUpdates."""
        for version in self.invalid_versions:
            self.chroot.SetVersion(version)
            with self.assertRaises(cros_sdk_lib.InvalidChrootVersionError):
                self.chroot.ApplyUpdates()

    def testIsInitialized(self) -> None:
        """Test IsInitialized conditions."""
        self.chroot.SetVersion(0)
        self.assertFalse(self.chroot.IsInitialized())

        self.chroot.SetVersion(1)
        self.assertTrue(self.chroot.IsInitialized())

        # Test handling each of the errors thrown by GetVersion.
        self.PatchObject(
            self.chroot,
            "GetVersion",
            side_effect=cros_sdk_lib.InvalidChrootVersionError(),
        )
        self.assertFalse(self.chroot.IsInitialized())

        self.PatchObject(self.chroot, "GetVersion", side_effect=IOError())
        self.assertFalse(self.chroot.IsInitialized())

        self.PatchObject(
            self.chroot,
            "GetVersion",
            side_effect=cros_sdk_lib.UninitializedChrootError(),
        )
        self.assertFalse(self.chroot.IsInitialized())


class ChrootCreatorTests(cros_test_lib.MockTempDirTestCase):
    """ChrootCreator tests."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
            cache_dir=str(self.tempdir / "cache_dir"),
        )
        self.sdk_tarball = self.tempdir / "chroot.tar"

        # We can't really verify these in any useful way atm.
        self.mount_mock = self.PatchObject(osutils, "Mount")

        self.creater = cros_sdk_lib.ChrootCreator(self.chroot, self.sdk_tarball)

        # Create a minimal tarball to extract during testing.
        tar_dir = self.tempdir / "tar_dir"
        D = cros_test_lib.Directory
        cros_test_lib.CreateOnDiskHierarchy(
            tar_dir,
            (
                D(
                    "etc",
                    (
                        D("env.d", ()),
                        "passwd",
                        "group",
                        "shadow",
                        D("skel", (D(".ssh", ("foo",)),)),
                    ),
                ),
                D(
                    "var",
                    (
                        D(
                            "cache",
                            (D("edb", ("counter",)),),
                        ),
                        D("log", (D("portage", ()),)),
                    ),
                ),
            ),
        )
        (tar_dir / "etc/passwd").write_text(
            "root:x:0:0:Root:/root:/bin/bash\n", encoding="utf-8"
        )
        (tar_dir / "etc/group").write_text(
            "root::0\nusers::100\n", encoding="utf-8"
        )
        (tar_dir / "etc/shadow").write_text(
            "root:*:10770:0:::::\n", encoding="utf-8"
        )

        osutils.Touch(tar_dir / self.creater.DEFAULT_TZ, makedirs=True)
        compression_lib.create_tarball(self.sdk_tarball, tar_dir)

    def testMakeChroot(self) -> None:
        """Verify make_chroot invocation."""
        with cros_test_lib.RunCommandMock() as rc_mock:
            rc_mock.SetDefaultCmdResult()
            # pylint: disable=protected-access
            self.creater._make_chroot()

    def testRun(self) -> None:
        """Verify run works."""
        TEST_USER = "a-test-user"
        TEST_UID = 20100908
        TEST_GROUP = "a-test-group"
        TEST_GID = 9082010
        self.PatchObject(cros_sdk_lib.ChrootCreator, "_make_chroot")
        chown_mock = self.PatchObject(osutils, "Chown")
        # We have to mock the cachedir lookup because, when run inside the SDK,
        # it always returns /mnt/host/source/ paths.  This is normally correct,
        # but we want to assert all paths to chown are safe by virtue of being
        # relative to the chroot dir.
        test_cache_dir = str(self.chroot.out_path / "test-cachedir")
        self.PatchObject(
            path_util.ChrootPathResolver,
            "_GetCachePath",
            return_value=test_cache_dir,
        )

        self.creater.run(
            user=TEST_USER, uid=TEST_UID, group=TEST_GROUP, gid=TEST_GID
        )
        assert chown_mock.call_args_list == [
            mock.call(
                Path(self.chroot.full_path("/home/a-test-user")),
                TEST_UID,
                group=TEST_GID,
                recursive=True,
            ),
            mock.call(
                self.chroot.full_path("/etc/make.conf.host_setup"),
                user="root",
                group="root",
            ),
            mock.call(
                test_cache_dir,
                TEST_UID,
                group=constants.PORTAGE_GID,
            ),
            mock.call(
                Path(
                    self.chroot.full_path(
                        constants.CHROOT_EDB_CACHE_ROOT / "dep"
                    )
                ),
                constants.PORTAGE_UID,
                group=constants.PORTAGE_GID,
                recursive=True,
            ),
        ]
        # Make sure all the paths are under the tempdir so we aren't accessing
        # random paths on the host.  The relative_to call will assert the path
        # is actually below the path.
        assert list(
            Path(x.args[0]).relative_to(self.tempdir)
            for x in chown_mock.call_args_list
        )

        # Check various root files.
        self.assertExists(Path(self.chroot.path) / "etc" / "localtime")

        # Check user home files.
        user_file = (
            self.chroot.out_path / "home" / "a-test-user" / ".ssh" / "foo"
        )

        self.assertExists(user_file)

        # Check the user/group accounts.
        db = (Path(self.chroot.path) / "etc" / "passwd").read_text(
            encoding="utf-8"
        )
        self.assertStartsWith(db, f"{TEST_USER}:x:{TEST_UID}:{TEST_GID}:")
        # Make sure Python None didn't leak in.
        self.assertNotIn("None", db)
        db = (Path(self.chroot.path) / "etc" / "group").read_text(
            encoding="utf-8"
        )
        self.assertStartsWith(db, f"{TEST_GROUP}:x:{TEST_GID}:{TEST_USER}")
        # Make sure Python None didn't leak in.
        self.assertNotIn("None", db)

        # Check various /etc paths.
        etc = Path(self.chroot.path) / "etc"
        self.assertExists(etc / "mtab")
        self.assertExists(etc / "hosts")
        self.assertExists(etc / "resolv.conf")
        self.assertIn(
            f'PORTAGE_USERNAME="{TEST_USER}"',
            (etc / "env.d" / "99chromiumos").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            "/mnt/host/source/chromite/sdk/etc/bash_completion.d/cros",
            os.readlink(etc / "bash_completion.d" / "cros"),
        )
        self.assertExists(etc / "shadow")

        # Check /mnt/host directories.
        self.assertTrue(
            (Path(self.chroot.path) / "mnt" / "host" / "out").is_dir()
        )
        self.assertTrue(self.chroot.out_path.is_dir())
        edb_dep_path = Path(
            self.chroot.full_path(Path("/") / "var" / "cache" / "edb" / "dep")
        )
        self.assertTrue(edb_dep_path.is_dir())

        # Check chroot/var/ directories.
        var = Path(self.chroot.path) / "var"
        # Mount points exist in chroot.
        self.assertTrue((var / "cache").is_dir())
        self.assertTrue((var / "log").is_dir())
        # Sub-directory contents get copied over to out/.
        self.assertTrue(
            (self.chroot.out_path / "sdk" / "logs" / "portage").is_dir()
        )
        self.assertExists(
            self.chroot.out_path / "sdk" / "cache" / "edb" / "counter"
        )

    def testExistingCompatGroup(self) -> None:
        """Verify running with an existing, but matching, group works."""
        TEST_USER = "a-test-user"
        TEST_UID = 20100908
        TEST_GROUP = "users"
        TEST_GID = 100
        self.PatchObject(cros_sdk_lib.ChrootCreator, "_make_chroot")
        chown_mock = self.PatchObject(osutils, "Chown")
        # We have to mock the cachedir lookup because, when run inside the SDK,
        # it always returns /mnt/host/source/ paths.  This is normally correct,
        # but we want to assert all paths to chown are safe by virtue of being
        # relative to the chroot dir.
        test_cache_dir = str(self.chroot.out_path / "test-cachedir")
        self.PatchObject(
            path_util.ChrootPathResolver,
            "_GetCachePath",
            return_value=test_cache_dir,
        )

        self.creater.run(
            user=TEST_USER, uid=TEST_UID, group=TEST_GROUP, gid=TEST_GID
        )
        assert chown_mock.call_args_list == [
            mock.call(
                Path(self.chroot.full_path("/home/a-test-user")),
                TEST_UID,
                group=TEST_GID,
                recursive=True,
            ),
            mock.call(
                self.chroot.full_path("/etc/make.conf.host_setup"),
                user="root",
                group="root",
            ),
            mock.call(
                test_cache_dir,
                TEST_UID,
                group=constants.PORTAGE_GID,
            ),
            mock.call(
                Path(
                    self.chroot.full_path(
                        constants.CHROOT_EDB_CACHE_ROOT / "dep"
                    )
                ),
                constants.PORTAGE_UID,
                group=constants.PORTAGE_GID,
                recursive=True,
            ),
        ]


class ChrootEnterorTests(cros_test_lib.MockTempDirTestCase):
    """ChrootEnteror tests."""

    def setUp(self) -> None:
        chroot_path = self.tempdir / "chroot"
        self.chroot = chroot_lib.Chroot(
            path=chroot_path, cache_dir=self.tempdir / "cache_dir"
        )

        sudo = chroot_path / "usr" / "bin" / "sudo"
        osutils.Touch(sudo, makedirs=True, mode=0o7755)

        # We can't really verify these in any useful way atm.
        self.mount_mock = self.PatchObject(osutils, "Mount")

        self.enteror = cros_sdk_lib.ChrootEnteror(self.chroot, read_only=False)

        self.sysctl_vm_max_map_count = self.tempdir / "vm_max_map_count"
        self.PatchObject(
            cros_sdk_lib.ChrootEnteror,
            "_SYSCTL_VM_MAX_MAP_COUNT",
            self.sysctl_vm_max_map_count,
        )

    def testRun(self) -> None:
        """Verify run works."""
        with self.PatchObject(cros_build_lib, "dbg_run"):
            self.enteror.run()

    def testHelperRun(self) -> None:
        """Verify helper run API works."""
        with self.PatchObject(cros_build_lib, "dbg_run"):
            cros_sdk_lib.EnterChroot(self.chroot)

    def test_setup_vm_max_map_count(self) -> None:
        """Verify _setup_vm_max_map_count works."""
        self.sysctl_vm_max_map_count.write_text("1024", encoding="utf-8")
        self.enteror._setup_vm_max_map_count()
        self.assertEqual(
            int(self.sysctl_vm_max_map_count.read_text(encoding="utf-8")),
            self.enteror._RLIMIT_NOFILE_MIN,
        )


@pytest.fixture(name="chroot_version_file")
def _with_chroot_version_file(monkeypatch, tmp_path: Path):
    """Set CHROOT_VERSION_FILE to the returned temp path.

    The chroot version file is not created, callers expected to write the
    file if that's the desired behavior.
    """
    chroot_version_file = tmp_path / "chroot_version_file"
    monkeypatch.setattr(
        cros_sdk_lib, "CHROOT_VERSION_FILE", str(chroot_version_file)
    )

    yield chroot_version_file


def test_inside_chroot_checks_inside_chroot(chroot_version_file: Path) -> None:
    """Test {is|assert}_inside_chroot inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    assert cros_sdk_lib.is_inside_chroot()
    cros_sdk_lib.assert_inside_chroot()


def test_outside_chroot_checks_inside_chroot(chroot_version_file: Path) -> None:
    """Test {is|assert}_outside_chroot inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    assert not cros_sdk_lib.is_outside_chroot()
    with pytest.raises(AssertionError):
        cros_sdk_lib.assert_outside_chroot()


def test_inside_chroot_checks_outside_chroot(chroot_version_file: Path) -> None:
    """Test {is|assert}_inside_chroot outside the chroot."""
    assert not chroot_version_file.exists()

    assert not cros_sdk_lib.is_inside_chroot()
    with pytest.raises(AssertionError):
        cros_sdk_lib.assert_inside_chroot()


def test_outside_chroot_checks_outside_chroot(
    chroot_version_file: Path,
) -> None:
    """Test {is|assert}_outside_chroot outside the chroot."""
    assert not chroot_version_file.exists()

    assert cros_sdk_lib.is_outside_chroot()
    cros_sdk_lib.assert_outside_chroot()


def test_require_inside_decorator_inside_chroot(
    chroot_version_file: Path,
) -> None:
    """Test require_inside_chroot decorator inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    @cros_sdk_lib.require_inside_chroot("Runs")
    def inside() -> None:
        pass

    inside()


def test_require_outside_decorator_inside_chroot(
    chroot_version_file: Path,
) -> None:
    """Test require_outside_chroot decorator inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    @cros_sdk_lib.require_outside_chroot("Raises assertion")
    def outside() -> None:
        pass

    with pytest.raises(AssertionError):
        outside()


def test_require_inside_decorator_outside_chroot(
    chroot_version_file: Path,
) -> None:
    """Test require_inside_chroot decorator outside the chroot."""
    assert not chroot_version_file.exists()

    @cros_sdk_lib.require_inside_chroot("Raises assertion")
    def inside() -> None:
        pass

    with pytest.raises(AssertionError):
        inside()


def test_require_outside_decorator_outside_chroot(
    chroot_version_file: Path,
) -> None:
    """Test require_outside_chroot decorator inside the chroot."""
    assert not chroot_version_file.exists()

    @cros_sdk_lib.require_outside_chroot("Runs")
    def outside() -> None:
        pass

    outside()


@contextlib.contextmanager
def fake_urlopen(url):
    """Fake urlopen function which pretends to fetch cros-sdk-latest.conf."""
    del url
    yield io.BytesIO(b'LATEST_SDK="2.3.4"\n')


def test_get_prefetch_versions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Test the get_prefetch_versions function."""
    fake_version_conf = tmp_path / "sdk_version.conf"
    fake_version_conf.write_text(
        "SDK_LATEST_VERSION='1.2.3'\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        constants, "SDK_VERSION_FILE_FULL_PATH", fake_version_conf
    )
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    fake_checkout_info = path_util.CheckoutInfo(
        path_util.CheckoutType.CITC, "", ""
    )
    with mock.patch.object(
        path_util, "DetermineCheckout", return_value=fake_checkout_info
    ):
        assert cros_sdk_lib.get_prefetch_sdk_versions() == {"1.2.3", "2.3.4"}


class FetchRemoteTarballsTest(cros_test_lib.MockTempDirTestCase):
    """Tests fetch_remote_tarballs function."""

    def test_fetch_remote_tarballs_empty(self) -> None:
        """Test fetch_remote_tarballs with no results."""
        m = self.PatchObject(retry_util, "RunCurl")
        with self.assertRaises(ValueError):
            cros_sdk_lib.fetch_remote_tarballs(self.tempdir, [])
        m.return_value = cros_build_lib.CompletedProcess(stdout=b"Foo: bar\n")
        with self.assertRaises(ValueError):
            cros_sdk_lib.fetch_remote_tarballs(self.tempdir, ["gs://x.tar"])

    def test_fetch_remote_tarballs_success(self) -> None:
        """Test fetch_remote_tarballs with a successful download."""
        curl = cros_build_lib.CompletedProcess(
            stdout=(b"HTTP/1.0 200\n" b"Foo: bar\n" b"Content-Length: 100\n")
        )
        self.PatchObject(retry_util, "RunCurl", return_value=curl)
        self.assertEqual(
            self.tempdir / "tar",
            cros_sdk_lib.fetch_remote_tarballs(self.tempdir, ["gs://x/tar"]),
        )


class ChrootWritableTests(cros_test_lib.MockTempDirTestCase):
    """Tests for ChrootReadWrite and ChrootReadOnly context managers."""

    def fake_mount(self, _source, target, _fstype, flags, _data="") -> None:
        if target in self.ro_map:
            ro = flags & osutils.MS_RDONLY != 0
            self.ro_map[target] = ro

    def fake_is_mounted(self, target):
        return target in self.ro_map

    def fake_is_mounted_readonly(self, target):
        return self.ro_map.get(target, False)

    def fake_run_mount(self, *args, **_kwargs) -> None:
        mount_options = args[0][4]
        mount_point = args[0][5]
        ro = "rw" not in mount_options.split(",")
        self.ro_map[mount_point] = ro

    def setUp(self) -> None:
        self.ro_map = {}

        self.mount_mock = self.PatchObject(
            osutils, "Mount", side_effect=self.fake_mount
        )
        self.is_mounted_mock = self.PatchObject(
            osutils, "IsMounted", side_effect=self.fake_is_mounted
        )
        self.read_only_mock = self.PatchObject(
            osutils,
            "IsMountedReadOnly",
            side_effect=self.fake_is_mounted_readonly,
        )
        self.rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        self.rc_mock.AddCmdResult(
            ["sudo", "--", "mount", "-o", mock.ANY, mock.ANY],
            side_effect=self.fake_run_mount,
        )

    def testReadWrite_BadMount(self) -> None:
        """Test with a path that's not mounted."""
        assert not osutils.IsMounted("/some/path")

        with pytest.raises(AssertionError):
            with cros_sdk_lib.ChrootReadWrite("/some/path"):
                pass

        self.mount_mock.assert_not_called()

    def testReadWrite_RenamedMount(self) -> None:
        """Test with a path that's modified within the context manager."""
        self.ro_map["/path/to/chroot"] = True
        self.PatchObject(cros_sdk_lib, "IsChrootReady", return_value=True)
        assert osutils.IsMounted("/path/to/chroot")
        assert osutils.IsMountedReadOnly("/path/to/chroot")
        assert not osutils.IsMounted("/")

        with cros_sdk_lib.ChrootReadWrite("/path/to/chroot"):
            assert not osutils.IsMountedReadOnly("/path/to/chroot")

            # Imitate a pivot_root.
            self.ro_map.pop("/path/to/chroot")
            self.ro_map["/"] = False

            assert not osutils.IsMounted("/path/to/chroot")
            assert osutils.IsMounted("/")
            assert not osutils.IsMountedReadOnly("/")

        assert self.mount_mock.call_count == 1
        # We lost track of the changed root mount, but that's the best we can
        # do. We only expect this to happen for the outermost chroot entry, so
        # this leakage should be short-lived (until we tear down the mount
        # namespace).
        assert osutils.IsMounted("/")
        assert not osutils.IsMountedReadOnly("/")

    def testReadWrite_WritableRoot(self) -> None:
        """Read-write context when root is already writable."""
        self.ro_map["/"] = False
        assert osutils.IsMounted("/")
        assert not osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadWrite():
            assert not osutils.IsMountedReadOnly("/")

        assert not osutils.IsMountedReadOnly("/")
        self.mount_mock.assert_not_called()

    def testReadWrite_ReadonlyRoot(self) -> None:
        """Read-write context when root is read-only."""
        self.ro_map["/"] = True
        assert osutils.IsMounted("/")
        assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadWrite():
            assert not osutils.IsMountedReadOnly("/")

        assert osutils.IsMountedReadOnly("/")
        assert self.mount_mock.call_args_list == [
            mock.call(None, "/", None, osutils.MS_REMOUNT | osutils.MS_BIND),
            mock.call(
                None,
                "/",
                None,
                osutils.MS_REMOUNT | osutils.MS_BIND | osutils.MS_RDONLY,
            ),
        ]

    def testReadWrite_Stacked(self) -> None:
        """Stacked read/write on a writable root."""
        self.ro_map["/"] = False
        assert osutils.IsMounted("/")
        assert not osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadWrite():
            with cros_sdk_lib.ChrootReadWrite():
                assert not osutils.IsMountedReadOnly("/")
            assert not osutils.IsMountedReadOnly("/")

        assert not osutils.IsMountedReadOnly("/")
        self.mount_mock.assert_not_called()

    def testReadWrite_StackedReadOnly(self) -> None:
        """Stacked read/write on a read-only root."""
        self.ro_map["/"] = True
        assert osutils.IsMounted("/")
        assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadWrite():
            with cros_sdk_lib.ChrootReadWrite():
                assert not osutils.IsMountedReadOnly("/")
            assert not osutils.IsMountedReadOnly("/")

        assert osutils.IsMountedReadOnly("/")
        assert self.mount_mock.call_count == 2

    def testReadOnly_BadMount(self) -> None:
        """Test with a path that's not mounted."""
        assert not osutils.IsMounted("/some/path")

        with pytest.raises(AssertionError):
            with cros_sdk_lib.ChrootReadOnly("/some/path"):
                pass

        self.mount_mock.assert_not_called()

    def testReadOnly_ReadOnlyRoot(self) -> None:
        """Read-only context when root is already read-only."""
        self.ro_map["/"] = True
        assert osutils.IsMounted("/")
        assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadOnly():
            assert osutils.IsMountedReadOnly("/")

        assert osutils.IsMountedReadOnly("/")
        self.mount_mock.assert_not_called()

    def testReadOnly_WritableRoot(self) -> None:
        """Read-only context when root is read/write."""
        self.ro_map["/"] = False
        assert osutils.IsMounted("/")
        assert not osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadOnly():
            assert osutils.IsMountedReadOnly("/")

        assert not osutils.IsMountedReadOnly("/")
        assert self.mount_mock.call_args_list == [
            mock.call(
                None,
                "/",
                None,
                osutils.MS_REMOUNT | osutils.MS_BIND | osutils.MS_RDONLY,
            ),
            mock.call(
                None,
                "/",
                None,
                osutils.MS_REMOUNT | osutils.MS_BIND,
            ),
        ]

    def testReadOnly_Stacked(self) -> None:
        """Stacked read-only on a read-only root."""
        self.ro_map["/"] = True
        assert osutils.IsMounted("/")
        assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadOnly():
            with cros_sdk_lib.ChrootReadOnly():
                assert osutils.IsMountedReadOnly("/")
            assert osutils.IsMountedReadOnly("/")

        assert osutils.IsMountedReadOnly("/")
        self.mount_mock.assert_not_called()

    def testReadOnly_StackedWritable(self) -> None:
        """Stacked read-only on a writable root."""
        self.ro_map["/"] = False
        assert osutils.IsMounted("/")
        assert not osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadOnly():
            with cros_sdk_lib.ChrootReadOnly():
                assert osutils.IsMountedReadOnly("/")
            assert osutils.IsMountedReadOnly("/")

        assert not osutils.IsMountedReadOnly("/")
        assert self.mount_mock.call_count == 2

    def testStacked_WriteRead(self) -> None:
        """Stacked writable and read-only."""
        self.ro_map["/"] = True
        assert osutils.IsMounted("/")
        assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadWrite():
            assert not osutils.IsMountedReadOnly("/")
            with cros_sdk_lib.ChrootReadOnly():
                assert osutils.IsMountedReadOnly("/")
            assert not osutils.IsMountedReadOnly("/")

        assert osutils.IsMountedReadOnly("/")
        assert self.mount_mock.call_count == 4

    def testStacked_ReadWrite(self) -> None:
        """Stacked read-only and writable."""
        self.ro_map["/"] = False
        assert osutils.IsMounted("/")
        assert not osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadOnly():
            assert osutils.IsMountedReadOnly("/")
            with cros_sdk_lib.ChrootReadWrite():
                assert not osutils.IsMountedReadOnly("/")
            assert osutils.IsMountedReadOnly("/")

        assert not osutils.IsMountedReadOnly("/")
        assert self.mount_mock.call_count == 4

    def testNonRoot(self) -> None:
        """Test the non-root flow."""

        def non_root_mount(self, *args) -> None:
            raise PermissionError("Fake Mount permission failure")

        self.PatchObject(osutils, "Mount", side_effect=non_root_mount)
        # Clear environment to ensure nothing is propagated in sudo_run call.
        self.PatchObject(os, "environ", new_value={})

        self.ro_map["/"] = True
        assert osutils.IsMounted("/")
        assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadOnly():
            assert osutils.IsMountedReadOnly("/")

        with cros_sdk_lib.ChrootReadWrite():
            assert not osutils.IsMountedReadOnly("/")

        self.rc_mock.assertCommandContains(
            ["sudo", "--", "mount", "-o", "remount,bind,rw", "/"],
        )
        self.rc_mock.assertCommandContains(
            ["sudo", "--", "mount", "-o", "remount,bind,ro", "/"],
        )
        assert self.rc_mock.call_count == 2
        assert osutils.IsMountedReadOnly("/")
