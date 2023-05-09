# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the cros_sdk_lib module."""

import errno
import os
from pathlib import Path
import stat

import pytest

from chromite.lib import chroot_lib
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import cros_test_lib
from chromite.lib import locking
from chromite.lib import osutils


# pylint: disable=protected-access


class VersionHookTestCase(cros_test_lib.TempDirTestCase):
    """Class to set up tests that use the version hooks."""

    def setUp(self):
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


class TestGetFileSystemDebug(cros_test_lib.RunCommandTestCase):
    """Tests GetFileSystemDebug functionality."""

    def testNoPs(self):
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

    def testWithPs(self):
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


class TestMigrateStatePaths(cros_test_lib.MockTempDirTestCase):
    """Tests MigrateStatePaths functionality."""

    def setUp(self):
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        chroot_path = self.tempdir / "chroot"
        out_path = self.tempdir / "out"
        self.chroot = chroot_lib.Chroot(path=chroot_path, out_path=out_path)
        osutils.SafeMakedirsNonRoot(self.chroot.path)
        osutils.SafeMakedirsNonRoot(self.chroot.out_path)
        self.lock = locking.FileLock(
            chroot_path / ".chroot_lock", "chroot lock"
        )

        # TODO(b/265885353): fill map as we migrate state paths.
        self.state_path_map = (
            (Path(self.chroot.path) / "tmp", self.chroot.out_path / "tmp"),
            (Path(self.chroot.path) / "home", self.chroot.out_path / "home"),
            (Path(self.chroot.path) / "build", self.chroot.out_path / "build"),
        )

    def _crossdevice_rename(self, src, dst):
        raise OSError(errno.EXDEV, "fake cross-device rename failure")

    def testOldPathsExist(self):
        for src, dst in self.state_path_map:
            osutils.SafeMakedirsNonRoot(src / "foo")

            cros_sdk_lib.MigrateStatePaths(self.chroot, self.lock)

            self.assertNotExists(src / "foo")
            self.assertExists(src / "README")
            self.assertExists(dst / "foo")

    def testOnlyReadmeExists(self):
        for src, dst in self.state_path_map:
            osutils.SafeMakedirsNonRoot(src)
            osutils.Touch(src / "README")

            cros_sdk_lib.MigrateStatePaths(self.chroot, self.lock)

            self.assertExists(src / "README")
            self.assertNotExists(dst / "README")

    def testBothPathsExist(self):
        for src, dst in self.state_path_map:
            osutils.SafeMakedirsNonRoot(src / "foo")
            osutils.Touch(src / "foo" / "bar")
            osutils.SafeMakedirsNonRoot(dst / "foo")
            osutils.Touch(dst / "foo" / "baz")

            cros_sdk_lib.MigrateStatePaths(self.chroot, self.lock)

            self.assertNotExists(src / "foo")
            self.assertExists(dst / "foo")
            self.assertExists(dst / "foo" / "bar")
            self.assertExists(dst / "foo" / "baz")

    def testCrossDevice(self):
        """Verify we can migrate state across filesystem boundaries.

        Check for retention of ownership, mode too, since we
        need to exercise different logic when os.rename()
        doesn't work.
        """
        # Mock os.rename() to fail, so we fall back to copying/rsyncing.
        self.PatchObject(os, "rename", side_effect=self._crossdevice_rename)

        for src, dst in self.state_path_map:
            osutils.SafeMakedirsNonRoot(src / "foo")
            (src / "foo" / "bar").touch()
            (src / "foo" / "baz").touch(mode=0o400)
            osutils.Chown(src / "foo" / "baz", user="root", group="root")
            self.assertEqual(
                stat.S_IMODE((src / "foo" / "baz").stat().st_mode), 0o400
            )

            cros_sdk_lib.MigrateStatePaths(self.chroot, self.lock)

            self.assertNotExists(src / "foo")
            self.assertExists(dst / "foo")
            self.assertExists(dst / "foo" / "bar")
            self.assertExists(dst / "foo" / "baz")
            st = (dst / "foo" / "baz").stat()
            self.assertEqual(stat.S_IMODE(st.st_mode), 0o400)
            self.assertEqual(st.st_uid, 0)
            self.assertEqual(st.st_gid, 0)


class TestGetChrootVersion(cros_test_lib.MockTestCase):
    """Tests GetChrootVersion functionality."""

    def testNoChroot(self):
        """Verify we don't blow up when there is no chroot yet."""
        self.PatchObject(
            cros_sdk_lib.ChrootUpdater, "GetVersion", side_effect=IOError()
        )
        self.assertIsNone(cros_sdk_lib.GetChrootVersion("/.$om3/place/nowhere"))


class TestChrootVersionValid(VersionHookTestCase):
    """Test valid chroot version method."""

    def testLowerVersionValid(self):
        """Lower versions are considered valid."""
        osutils.WriteFile(
            self.version_file, str(self.latest_version - 1), sudo=True
        )
        self.assertTrue(
            cros_sdk_lib.IsChrootVersionValid(self.chroot_path, self.hooks_dir)
        )

    def testLatestVersionValid(self):
        """Test latest version."""
        osutils.WriteFile(
            self.version_file, str(self.latest_version), sudo=True
        )
        self.assertTrue(
            cros_sdk_lib.IsChrootVersionValid(self.chroot_path, self.hooks_dir)
        )

    def testInvalidVersion(self):
        """Test version higher than latest."""
        osutils.WriteFile(
            self.version_file, str(self.latest_version + 1), sudo=True
        )
        self.assertFalse(
            cros_sdk_lib.IsChrootVersionValid(self.chroot_path, self.hooks_dir)
        )


class TestLatestChrootVersion(VersionHookTestCase):
    """LatestChrootVersion tests."""

    def testLatest(self):
        """Test latest version."""
        self.assertEqual(
            self.latest_version,
            cros_sdk_lib.LatestChrootVersion(self.hooks_dir),
        )


class TestEarliestChrootVersion(VersionHookTestCase):
    """EarliestChrootVersion tests."""

    def testEarliest(self):
        """Test earliest version."""
        self.assertEqual(
            self.earliest_version,
            cros_sdk_lib.EarliestChrootVersion(self.hooks_dir),
        )


class TestIsChrootReady(cros_test_lib.MockTestCase):
    """Tests IsChrootReady functionality."""

    def setUp(self):
        self.version_mock = self.PatchObject(cros_sdk_lib, "GetChrootVersion")

    def testMissing(self):
        """Check behavior w/out a chroot."""
        self.version_mock.return_value = None
        self.assertFalse(cros_sdk_lib.IsChrootReady("/"))

    def testNotSetup(self):
        """Check behavior w/an existing uninitialized chroot."""
        self.version_mock.return_value = 0
        self.assertFalse(cros_sdk_lib.IsChrootReady("/"))

    def testUpToDate(self):
        """Check behavior w/a valid chroot."""
        self.version_mock.return_value = 123
        self.assertTrue(cros_sdk_lib.IsChrootReady("/"))


class TestCleanupChrootMount(cros_test_lib.MockTempDirTestCase):
    """Tests the CleanupChrootMount function."""

    def setUp(self):
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        osutils.SafeMakedirsNonRoot(self.chroot.path)
        osutils.SafeMakedirsNonRoot(self.chroot.out_path)

    def testCleanup(self):
        m = self.PatchObject(osutils, "UmountTree")

        cros_sdk_lib.CleanupChrootMount(self.chroot, None)

        m.assert_called_with(self.chroot.path)

    def testCleanupByBuildroot(self):
        m = self.PatchObject(osutils, "UmountTree")

        cros_sdk_lib.CleanupChrootMount(None, self.tempdir)

        m.assert_called_with(self.chroot.path)

    def testCleanupWithDelete(self):
        m = self.PatchObject(osutils, "UmountTree")
        m2 = self.PatchObject(osutils, "RmDir")

        cros_sdk_lib.CleanupChrootMount(self.chroot, None, delete=True)

        m.assert_called_with(self.chroot.path)
        m2.assert_any_call(self.chroot.path, ignore_missing=True, sudo=True)
        m2.assert_any_call(self.chroot.out_path, ignore_missing=True, sudo=True)

    def testCleanupNoDeleteOut(self):
        m = self.PatchObject(osutils, "UmountTree")
        m2 = self.PatchObject(osutils, "RmDir")

        cros_sdk_lib.CleanupChrootMount(
            self.chroot, None, delete=True, delete_out=False
        )

        m.assert_called_with(self.chroot.path)
        m2.assert_called_with(self.chroot.path, ignore_missing=True, sudo=True)


class ChrootUpdaterTest(cros_test_lib.MockTestCase, VersionHookTestCase):
    """ChrootUpdater tests."""

    def setUp(self):
        self.chroot = cros_sdk_lib.ChrootUpdater(
            version_file=self.version_file, hooks_dir=self.hooks_dir
        )

    def testVersion(self):
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

    def testInvalidVersion(self):
        """Test invalid version file contents."""
        osutils.WriteFile(self.version_file, "invalid", sudo=True)
        with self.assertRaises(cros_sdk_lib.InvalidChrootVersionError):
            self.chroot.GetVersion()

    def testMissingFileVersion(self):
        """Test missing version file."""
        osutils.SafeUnlink(self.version_file, sudo=True)
        with self.assertRaises(cros_sdk_lib.UninitializedChrootError):
            self.chroot.GetVersion()

    def testLatestVersion(self):
        """Test the latest_version property/_LatestScriptsVersion method."""
        self.assertEqual(self.latest_version, self.chroot.latest_version)

    def testGetChrootUpdates(self):
        """Test GetChrootUpdates."""
        # Test the deprecated error conditions.
        for version in self.deprecated_versions:
            self.chroot.SetVersion(version)
            with self.assertRaises(cros_sdk_lib.ChrootDeprecatedError):
                self.chroot.GetChrootUpdates()

    def testMultipleUpdateFiles(self):
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

    def testApplyUpdates(self):
        """Test ApplyUpdates."""
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc_mock.SetDefaultCmdResult()
        for version in self.success_versions:
            self.chroot.SetVersion(version)
            self.chroot.ApplyUpdates()
            self.assertEqual(self.latest_version, self.chroot.GetVersion())

    def testApplyInvalidUpdates(self):
        """Test the invalid version conditions for ApplyUpdates."""
        for version in self.invalid_versions:
            self.chroot.SetVersion(version)
            with self.assertRaises(cros_sdk_lib.InvalidChrootVersionError):
                self.chroot.ApplyUpdates()

    def testIsInitialized(self):
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

    def setUp(self):
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
                        D("skel", (D(".ssh", ("foo",)),)),
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
        osutils.Touch(tar_dir / self.creater.DEFAULT_TZ, makedirs=True)
        cros_build_lib.CreateTarball(self.sdk_tarball, tar_dir)

    def testMakeChroot(self):
        """Verify make_chroot invocation."""
        with cros_test_lib.RunCommandMock() as rc_mock:
            rc_mock.SetDefaultCmdResult()
            # pylint: disable=protected-access
            self.creater._make_chroot()
            rc_mock.assertCommandContains(
                [
                    "--chroot",
                    str(self.chroot.path),
                    "--cache_dir",
                    str(self.chroot.cache_dir),
                ]
            )

    def testRun(self):
        """Verify run works."""
        TEST_USER = "a-test-user"
        TEST_UID = 20100908
        TEST_GROUP = "a-test-group"
        TEST_GID = 9082010
        self.PatchObject(cros_sdk_lib.ChrootCreator, "_make_chroot")
        # The files won't be root owned, but they won't be user owned.
        self.ExpectRootOwnedFiles()

        self.creater.run(
            user=TEST_USER, uid=TEST_UID, group=TEST_GROUP, gid=TEST_GID
        )

        # Check various root files.
        self.assertExists(Path(self.chroot.path) / "etc" / "localtime")

        # Check user home files.
        user_file = Path(
            self.chroot.full_path(
                Path("/") / "home" / "a-test-user" / ".ssh" / "foo"
            )
        )
        self.assertExists(user_file)
        st = user_file.stat()
        self.assertEqual(st.st_uid, TEST_UID)
        self.assertEqual(st.st_gid, TEST_GID)

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
        self.assertIn(
            "en_US.UTF-8 UTF-8",
            (etc / "locale.gen").read_text(encoding="utf-8"),
        )

        # Check /mnt/host directories.
        self.assertTrue(
            (Path(self.chroot.path) / "mnt" / "host" / "source").is_dir()
        )
        self.assertTrue(
            (Path(self.chroot.path) / "mnt" / "host" / "out").is_dir()
        )
        self.assertTrue(self.chroot.out_path.is_dir())

    def testExistingCompatGroup(self):
        """Verify running with an existing, but matching, group works."""
        TEST_USER = "a-test-user"
        TEST_UID = 20100908
        TEST_GROUP = "users"
        TEST_GID = 100
        self.PatchObject(cros_sdk_lib.ChrootCreator, "_make_chroot")
        # The files won't be root owned, but they won't be user owned.
        self.ExpectRootOwnedFiles()

        self.creater.run(
            user=TEST_USER, uid=TEST_UID, group=TEST_GROUP, gid=TEST_GID
        )

    # TODO(b/297068910): Remove this when we remove the clear_state() hack.
    def testCleanHome(self):
        """Verify we can clean a bad /home/* path."""
        TEST_USER = "a-test-user"
        TEST_UID = 20100908
        TEST_GROUP = "a-test-group"
        TEST_GID = 9082010
        self.PatchObject(cros_sdk_lib.ChrootCreator, "_make_chroot")
        # The files won't be root owned, but they won't be user owned.
        self.ExpectRootOwnedFiles()

        osutils.SafeMakedirsNonRoot(
            Path(self.chroot.path) / "home" / "chronos" / "user"
        )

        self.creater.run(
            user=TEST_USER, uid=TEST_UID, group=TEST_GROUP, gid=TEST_GID
        )
        self.assertNotExists(Path(self.chroot.path) / "home" / "chronos")
        self.assertExists(Path(self.chroot.path) / "home")


class ChrootEnterorTests(cros_test_lib.MockTempDirTestCase):
    """ChrootEnteror tests."""

    def setUp(self):
        chroot_path = self.tempdir / "chroot"
        self.chroot = chroot_lib.Chroot(
            path=chroot_path, cache_dir=self.tempdir / "cache_dir"
        )

        sudo = chroot_path / "usr" / "bin" / "sudo"
        osutils.Touch(sudo, makedirs=True, mode=0o7755)

        # We can't really verify these in any useful way atm.
        self.mount_mock = self.PatchObject(osutils, "Mount")

        self.enteror = cros_sdk_lib.ChrootEnteror(self.chroot)

        self.sysctl_vm_max_map_count = self.tempdir / "vm_max_map_count"
        self.PatchObject(
            cros_sdk_lib.ChrootEnteror,
            "_SYSCTL_VM_MAX_MAP_COUNT",
            self.sysctl_vm_max_map_count,
        )

    def testRun(self):
        """Verify run works."""
        with self.PatchObject(cros_build_lib, "dbg_run"):
            self.enteror.run()

    def testHelperRun(self):
        """Verify helper run API works."""
        with self.PatchObject(cros_build_lib, "dbg_run"):
            cros_sdk_lib.EnterChroot(self.chroot)

    def test_setup_vm_max_map_count(self):
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


def test_inside_chroot_checks_inside_chroot(chroot_version_file: Path):
    """Test {is|assert}_inside_chroot inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    assert cros_sdk_lib.is_inside_chroot()
    cros_sdk_lib.assert_inside_chroot()


def test_outside_chroot_checks_inside_chroot(chroot_version_file: Path):
    """Test {is|assert}_outside_chroot inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    assert not cros_sdk_lib.is_outside_chroot()
    with pytest.raises(AssertionError):
        cros_sdk_lib.assert_outside_chroot()


def test_inside_chroot_checks_outside_chroot(chroot_version_file: Path):
    """Test {is|assert}_inside_chroot outside the chroot."""
    assert not chroot_version_file.exists()

    assert not cros_sdk_lib.is_inside_chroot()
    with pytest.raises(AssertionError):
        cros_sdk_lib.assert_inside_chroot()


def test_outside_chroot_checks_outside_chroot(chroot_version_file: Path):
    """Test {is|assert}_outside_chroot outside the chroot."""
    assert not chroot_version_file.exists()

    assert cros_sdk_lib.is_outside_chroot()
    cros_sdk_lib.assert_outside_chroot()


def test_require_inside_decorator_inside_chroot(chroot_version_file: Path):
    """Test require_inside_chroot decorator inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    @cros_sdk_lib.require_inside_chroot("Runs")
    def inside():
        pass

    inside()


def test_require_outside_decorator_inside_chroot(chroot_version_file: Path):
    """Test require_outside_chroot decorator inside the chroot."""
    chroot_version_file.write_text("123", encoding="utf-8")

    @cros_sdk_lib.require_outside_chroot("Raises assertion")
    def outside():
        pass

    with pytest.raises(AssertionError):
        outside()


def test_require_inside_decorator_outside_chroot(chroot_version_file: Path):
    """Test require_inside_chroot decorator outside the chroot."""
    assert not chroot_version_file.exists()

    @cros_sdk_lib.require_inside_chroot("Raises assertion")
    def inside():
        pass

    with pytest.raises(AssertionError):
        inside()


def test_require_outside_decorator_outside_chroot(chroot_version_file: Path):
    """Test require_outside_chroot decorator inside the chroot."""
    assert not chroot_version_file.exists()

    @cros_sdk_lib.require_outside_chroot("Runs")
    def outside():
        pass

    outside()
