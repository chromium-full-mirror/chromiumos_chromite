# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the binhost.py service."""

import base64
import os
from pathlib import Path
import time
from unittest import mock

from chromite.third_party import requests
from chromite.third_party.google.protobuf import timestamp_pb2
import pytest

from chromite.api.gen.chromiumos import prebuilts_cloud_pb2
from chromite.lib import binpkg
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import config_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib import repo_util
from chromite.lib import sysroot_lib
from chromite.service import binhost
from chromite.utils import gs_urls_util


# pylint: disable=protected-access

# Define constants for test cases.
MOCK_BINHOST_ID = 1
MOCK_BUILD_TARGET = build_target_lib.BuildTarget("test_build_target", "base")
MOCK_BUILD_TARGET_NAME = "test_build_target"
MOCK_DATE_STRING = "2023-07-25T08:09:14.842Z"
MOCK_GENERIC_BUILD_TARGET_NAME = "generic_build_target"
MOCK_GENERIC_PROFILE = "generic_profile"
MOCK_GS_URI = "gs://test"
MOCK_ID_TOKEN = "test_token"
MOCK_PROFILE = "test_profile"
MOCK_SNAPSHOT_SHA = "test_sha"


class GetPrebuiltAclArgsTest(cros_test_lib.MockTempDirTestCase):
    """GetPrebuiltAclArgs tests."""

    _ACL_FILE = """
# Comment
-g group1:READ

# Another Comment
-u user:FULL_CONTROL # EOL Comment



# Comment # Comment
-g group2:READ
"""

    def setUp(self) -> None:
        self.build_target = build_target_lib.BuildTarget("board")
        self.acl_file = os.path.join(self.tempdir, "googlestorage_acl.txt")
        osutils.WriteFile(self.acl_file, self._ACL_FILE)

    def testParse(self) -> None:
        """Test parsing a valid file."""
        self.PatchObject(
            portage_util, "FindOverlayFile", return_value=self.acl_file
        )

        expected_acls = [
            ["-g", "group1:READ"],
            ["-u", "user:FULL_CONTROL"],
            ["-g", "group2:READ"],
        ]

        acls = binhost.GetPrebuiltAclArgs(self.build_target)

        self.assertCountEqual(expected_acls, acls)

    def testNoFile(self) -> None:
        """Test no file handling."""
        self.PatchObject(portage_util, "FindOverlayFile", return_value=None)

        with self.assertRaises(binhost.NoAclFileFound):
            binhost.GetPrebuiltAclArgs(self.build_target)


class SetBinhostTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for SetBinhost."""

    def setUp(self) -> None:
        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)

        self.public_conf_dir = os.path.join(
            self.tempdir, constants.PUBLIC_BINHOST_CONF_DIR, "target"
        )
        osutils.SafeMakedirs(self.public_conf_dir)

        self.private_conf_dir = os.path.join(
            self.tempdir, constants.PRIVATE_BINHOST_CONF_DIR, "target"
        )
        osutils.SafeMakedirs(self.private_conf_dir)

    def tearDown(self) -> None:
        osutils.EmptyDir(self.tempdir)

    def testSetBinhostPublic(self) -> None:
        """SetBinhost returns correct public path and updates conf file."""
        actual = binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts", private=False
        )
        expected = os.path.join(self.public_conf_dir, "coral-BINHOST_KEY.conf")
        self.assertEqual(actual, expected)
        self.assertEqual(
            osutils.ReadFile(actual), 'BINHOST_KEY="gs://prebuilts"'
        )

    def testSetBinhostPrivate(self) -> None:
        """SetBinhost returns correct private path and updates conf file."""
        actual = binhost.SetBinhost("coral", "BINHOST_KEY", "gs://prebuilts")
        expected = os.path.join(self.private_conf_dir, "coral-BINHOST_KEY.conf")
        self.assertEqual(actual, expected)
        self.assertEqual(
            osutils.ReadFile(actual), 'BINHOST_KEY="gs://prebuilts"'
        )

    def testSetBinhostEmptyConf(self) -> None:
        """SetBinhost rejects existing but empty conf files."""
        conf_path = os.path.join(
            self.private_conf_dir, "multi-BINHOST_KEY.conf"
        )
        osutils.WriteFile(conf_path, " ")
        with self.assertRaises(ValueError):
            binhost.SetBinhost("multi", "BINHOST_KEY", "gs://blah")

    def testSetBinhostMultilineConf(self) -> None:
        """SetBinhost rejects existing multiline conf files."""
        conf_path = os.path.join(
            self.private_conf_dir, "multi-BINHOST_KEY.conf"
        )
        osutils.WriteFile(conf_path, "\n".join(['A="foo"', 'B="bar"']))
        with self.assertRaises(ValueError):
            binhost.SetBinhost("multi", "BINHOST_KEY", "gs://blah")

    def testSetBinhhostBadConfLine(self) -> None:
        """SetBinhost rejects existing conf files with malformed lines."""
        conf_path = os.path.join(self.private_conf_dir, "bad-BINHOST_KEY.conf")
        osutils.WriteFile(conf_path, "bad line")
        with self.assertRaises(ValueError):
            binhost.SetBinhost("bad", "BINHOST_KEY", "gs://blah")

    def testSetBinhostMismatchedKey(self) -> None:
        """SetBinhost rejects existing conf files with a mismatched key."""
        conf_path = os.path.join(self.private_conf_dir, "bad-key-GOOD_KEY.conf")
        osutils.WriteFile(conf_path, 'BAD_KEY="https://foo.bar"')
        with self.assertRaises(KeyError):
            binhost.SetBinhost("bad-key", "GOOD_KEY", "gs://blah")

    def testSetBinhostMaxURIsIncrease(self) -> None:
        """SetBinhost appends uri in BINHOST conf file."""
        binhost.SetBinhost("coral", "BINHOST_KEY", "gs://prebuilts", max_uris=1)
        actual = binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts2", max_uris=2
        )
        self.assertEqual(
            osutils.ReadFile(actual),
            'BINHOST_KEY="gs://prebuilts gs://prebuilts2"',
        )

    def testSetBinhostMaxURIsRemoveOldest(self) -> None:
        """Setbinhost appends only maximum # uris and removes in FIFO order."""
        binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts1", max_uris=1
        )
        binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts2", max_uris=3
        )
        binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts3", max_uris=3
        )
        actual = binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts4", max_uris=3
        )
        self.assertEqual(
            osutils.ReadFile(actual),
            'BINHOST_KEY="gs://prebuilts2 gs://prebuilts3 gs://prebuilts4"',
        )

        actual = binhost.SetBinhost(
            "coral", "BINHOST_KEY", "gs://prebuilts5", max_uris=1
        )
        self.assertEqual(
            osutils.ReadFile(actual), 'BINHOST_KEY="gs://prebuilts5"'
        )

    def testSetBinhostInvalidMaxUris(self) -> None:
        """SetBinhost rejects invalid max_uris"""
        with self.assertRaises(binhost.InvalidMaxUris):
            binhost.SetBinhost(
                "coral", "BINHOST_KEY", "gs://prebuilts", max_uris=0
            )
        with self.assertRaises(binhost.InvalidMaxUris):
            binhost.SetBinhost(
                "coral", "BINHOST_KEY", "gs://prebuilts", max_uris=-1
            )
        with self.assertRaises(binhost.InvalidMaxUris):
            binhost.SetBinhost(
                "coral", "BINHOST_KEY", "gs://prebuilts", max_uris=None
            )

    def testSetBinhostForHost(self) -> None:
        """SetBinhost returns host path and sets the binhost."""
        binhost.SetBinhost(
            "amd64-generic",
            "POSTSUBMIT_BINHOST",
            "gs://prebuilts1/host",
            max_uris=1,
        )
        actual = binhost.SetBinhost(
            "amd64-generic",
            "POSTSUBMIT_BINHOST",
            "gs://prebuilts2/host",
            max_uris=1,
        )
        self.assertEqual(
            osutils.ReadFile(actual),
            'POSTSUBMIT_BINHOST="gs://prebuilts2/host"',
        )


class GetBinhostConfPathTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for GetBinhostConfPath."""

    def setUp(self) -> None:
        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)

        self.public_conf_dir = (
            Path(self.tempdir) / constants.PUBLIC_BINHOST_CONF_DIR / "target"
        )
        self.private_conf_dir = (
            Path(self.tempdir) / constants.PRIVATE_BINHOST_CONF_DIR / "target"
        )

    def testGetBinhostConfPathPublic(self) -> None:
        """GetBinhostConfPath returns correct public conf path."""
        expected = self.public_conf_dir / "coral-BINHOST_KEY.conf"
        actual = binhost.GetBinhostConfPath("coral", "BINHOST_KEY", False)
        self.assertEqual(actual, expected)

    def testGetBinhostConfPathPrivate(self) -> None:
        """GetBinhostConfPath returns correct private conf path."""
        expected = self.private_conf_dir / "coral-BINHOST_KEY.conf"
        actual = binhost.GetBinhostConfPath("coral", "BINHOST_KEY", True)
        self.assertEqual(actual, expected)


class GetPrebuiltsRootTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for GetPrebuiltsRoot."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)
        self.sysroot_path = "/build/foo"

        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)
        self.build_target = build_target_lib.BuildTarget("foo")

        self.root = self.chroot.full_path(self.sysroot.JoinPath("packages"))
        osutils.SafeMakedirs(self.root)

    def testGetPrebuiltsRoot(self) -> None:
        """GetPrebuiltsRoot returns correct root for given build target."""
        actual = binhost.GetPrebuiltsRoot(
            self.chroot, self.sysroot, self.build_target
        )
        self.assertEqual(actual, self.root)

    def testGetPrebuiltsBadTarget(self) -> None:
        """GetPrebuiltsRoot dies on missing root (target probably not built.)"""
        with self.assertRaises(binhost.EmptyPrebuiltsRoot):
            binhost.GetPrebuiltsRoot(
                self.chroot,
                sysroot_lib.Sysroot("/build/bar"),
                build_target_lib.BuildTarget("bar"),
            )


class GetPrebuiltsFilesTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for GetPrebuiltsFiles."""

    def setUp(self) -> None:
        self.PatchObject(constants, "SOURCE_ROOT", new=str(self.tempdir))
        self.root = self.tempdir / "chroot/build/target/packages"
        osutils.SafeMakedirs(self.root)

    def testGetPrebuiltsFiles(self) -> None:
        """GetPrebuiltsFiles returns all archives for all packages."""
        packages_content = """\
ARCH: amd64
URI: gs://foo_prebuilts

CPV: package/prebuilt_a

CPV: package/prebuilt_b
    """
        osutils.WriteFile(os.path.join(self.root, "Packages"), packages_content)
        osutils.WriteFile(
            os.path.join(self.root, "package/prebuilt_a.tbz2"),
            "a",
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(self.root, "package/prebuilt_b.tbz2"), "b"
        )

        actual = binhost.GetPrebuiltsFiles(self.root)
        expected = ["package/prebuilt_a.tbz2", "package/prebuilt_b.tbz2"]
        self.assertEqual(actual, expected)

    def testGetPrebuiltsFilesWithDebugSymbols(self) -> None:
        """GetPrebuiltsFiles returns debug symbols archive if set in index."""
        packages_content = """\
ARCH: amd64
URI: gs://foo_prebuilts

CPV: package/prebuilt
DEBUG_SYMBOLS: yes
    """
        osutils.WriteFile(os.path.join(self.root, "Packages"), packages_content)
        osutils.WriteFile(
            os.path.join(self.root, "package/prebuilt.tbz2"),
            "foo",
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(self.root, "package/prebuilt.debug.tbz2"),
            "debug",
            makedirs=True,
        )

        actual = binhost.GetPrebuiltsFiles(self.root)
        expected = ["package/prebuilt.tbz2", "package/prebuilt.debug.tbz2"]
        self.assertEqual(actual, expected)

    def testGetPrebuiltsFilesBadFile(self) -> None:
        """GetPrebuiltsFiles dies if archive file does not exist."""
        packages_content = """\
ARCH: amd64
URI: gs://foo_prebuilts

CPV: package/prebuilt
    """
        osutils.WriteFile(os.path.join(self.root, "Packages"), packages_content)

        with self.assertRaises(LookupError):
            binhost.GetPrebuiltsFiles(self.root)

    def testPrebuiltsDeduplication(self) -> None:
        """GetPrebuiltsFiles returns all archives for all packages."""
        now = int(time.time())
        # As of time of writing it checks for no older than 2 weeks. We just
        # need to be newer than that, but older than the new time, so just knock
        # off a few seconds.
        old_time = now - 5

        packages_content = f"""\
ARCH: amd64
URI: gs://foo_prebuilts

CPV: category/package_a
SHA1: 02b0a68a347e39c6d7be3c987022c134e4ba75e5
MTIME: {now}
PATH: category/package_a.tbz2

CPV: category/package_b
"""

        old_packages_content = f"""\
ARCH: amd64
URI: gs://foo_prebuilts

CPV: category/package_a
SHA1: 02b0a68a347e39c6d7be3c987022c134e4ba75e5
MTIME: {old_time}
PATH: old_binhost/category/package_a.tbz2
"""

        old_binhost = self.tempdir / "old_packages"
        old_package_index = old_binhost / "Packages"
        osutils.WriteFile(
            old_package_index, old_packages_content, makedirs=True
        )
        osutils.WriteFile(self.root / "Packages", packages_content)
        osutils.WriteFile(
            self.root / "category/package_a.tbz2",
            "a",
            makedirs=True,
        )
        osutils.WriteFile(
            self.root / "category/package_b.tbz2",
            "b",
            makedirs=True,
        )

        actual = binhost.GetPrebuiltsFiles(self.root, [old_package_index])
        # package_a should be deduped, so only package_b is left.
        expected = ["category/package_b.tbz2"]
        self.assertEqual(expected, actual)

        # Verify the deduplication was persisted to the index.
        pkg_index = binpkg.PackageIndex()
        pkg_index.ReadFilePath(self.root / "Packages")
        self.assertEqual(
            pkg_index.packages[0]["PATH"], "old_binhost/category/package_a.tbz2"
        )


class UpdatePackageIndexTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for UpdatePackageIndex."""

    def setUp(self) -> None:
        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)
        self.root = os.path.join(self.tempdir, "chroot/build/target/packages")
        osutils.SafeMakedirs(self.root)

    def testAbsoluteUploadPath(self) -> None:
        """Test UpdatePackageIndex raises an error for absolute paths."""
        with self.assertRaises(AssertionError):
            binhost.UpdatePackageIndex(
                self.root, "gs://chromeos-prebuilt", "/target"
            )

    def testUpdatePackageIndex(self) -> None:
        """UpdatePackageIndex writes updated file to disk."""
        packages_content = """\
ARCH: amd64
TTL: 0

CPV: package/prebuilt
    """
        osutils.WriteFile(os.path.join(self.root, "Packages"), packages_content)

        binhost.UpdatePackageIndex(
            self.root, "gs://chromeos-prebuilt", "target/"
        )

        actual = binpkg.GrabLocalPackageIndex(self.root)
        self.assertEqual(actual.header["URI"], "gs://chromeos-prebuilt")
        self.assertEqual(int(actual.header["TTL"]), 60 * 60 * 24 * 365)
        self.assertEqual(
            actual.packages,
            [
                {
                    "CPV": "package/prebuilt",
                    "PATH": "target/package/prebuilt.tbz2",
                }
            ],
        )


class GetHostBinhostsTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for GetHostBinhosts."""

    def setUp(self) -> None:
        self.portageq_envvar_mock = self.PatchObject(
            portage_util, "PortageqEnvvar"
        )
        self.PatchObject(constants, "PUBLIC_BINHOST_CONF_DIR", new=self.tempdir)
        self.test_host_binhost_conf = (
            self.tempdir / "host" / "amd64-generic-POSTSUBMIT_BINHOST.conf"
        )

    def testReadAndParseBinhosts(self) -> None:
        """Tests that binhosts are parsed from the BINHOST.conf file."""
        self.portageq_envvar_mock.return_value = None
        binhost_conf_file_content = """\
POSTSUBMIT_BINHOST="gs://binhost1 gs://binhost2"
"""
        osutils.WriteFile(
            self.test_host_binhost_conf,
            binhost_conf_file_content,
            makedirs=True,
        )

        binhosts = binhost.GetHostBinhosts()

        self.assertEqual(binhosts, ["gs://binhost1", "gs://binhost2"])

    def testIncorrectKey(self) -> None:
        """Tests when the BINHOST.conf does not contain the correct key."""
        self.portageq_envvar_mock.return_value = "gs://binhost1"
        binhost_conf_file_content = """\
WRONG_KEY="gs://binhost1 gs://binhost2"
"""
        osutils.WriteFile(
            self.test_host_binhost_conf,
            binhost_conf_file_content,
            makedirs=True,
        )

        binhosts = binhost.GetHostBinhosts()

        self.assertEqual(binhosts, ["gs://binhost1"])

    def testMissingFile(self) -> None:
        """Tests when the BINHOST.conf does not exist."""
        self.portageq_envvar_mock.return_value = "gs://binhost1"

        binhosts = binhost.GetHostBinhosts()

        self.assertEqual(binhosts, ["gs://binhost1"])


def test_regen_build_cache(tmp_path, run_mock, outside_sdk):
    """Test RegenBuildCache."""
    del outside_sdk

    chroot = chroot_lib.Chroot(
        path=tmp_path / "chroot",
        out_path=tmp_path / "out",
    )
    osutils.SafeMakedirs(chroot.tmp)
    run_mock.SetDefaultCmdResult(
        stdout="src/third_party/chromiumos-overlay\n",
    )
    assert binhost.RegenBuildCache(chroot, constants.PUBLIC_OVERLAYS) == [
        str(
            constants.SOURCE_ROOT / "src" / "third_party" / "chromiumos-overlay"
        ),
    ]
    run_mock.assertCommandContains(
        [
            "/mnt/host/source/chromite/scripts/cros_update_metadata_cache",
            "--overlay-type",
            "public",
            "--debug",
        ]
    )


class ReadDevInstallPackageFileTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for ReadDevInstallPackageFile."""

    def setUp(self) -> None:
        self.root = os.path.join(
            self.tempdir, "chroot/build/target/build/dev-install/"
        )
        self.packages_file = os.path.join(self.root, "package.installable")
        osutils.SafeMakedirs(self.root)
        package_file_content = """\
x11-apps/intel-gpu-tools-1.22
x11-libs/gdk-pixbuf-2.36.12-r1
x11-misc/read-edid-1.4.2
virtual/acl-0-r1
"""
        osutils.WriteFile(self.packages_file, package_file_content)

    def testReadDevInstallPackageFile(self) -> None:
        """Test that parsing valid file works."""
        packages = binhost.ReadDevInstallPackageFile(self.packages_file)
        expected_packages = [
            "x11-apps/intel-gpu-tools-1.22",
            "x11-libs/gdk-pixbuf-2.36.12-r1",
            "x11-misc/read-edid-1.4.2",
            "virtual/acl-0-r1",
        ]
        self.assertEqual(packages, expected_packages)


class CreateDevInstallPackageFileTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for CreateDevInstallPackageFile."""

    def setUp(self) -> None:
        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)
        self.root = os.path.join(self.tempdir, "chroot/build/target/packages")
        osutils.SafeMakedirs(self.root)
        self.devinstall_package_list = ["virtual/python-enum34-1"]
        self.devinstall_packages_filename = os.path.join(
            self.root, "package.installable"
        )
        packages_content = """\
ARCH: amd64
TTL: 0

CPV: package/prebuilt

CPV: virtual/python-enum34-1

    """
        osutils.WriteFile(os.path.join(self.root, "Packages"), packages_content)

        devinstall_packages_content = """\
virtual/python-enum34-1
    """
        osutils.WriteFile(
            self.devinstall_packages_filename, devinstall_packages_content
        )
        self.upload_dir = os.path.join(self.root, "upload_dir")
        osutils.SafeMakedirs(self.upload_dir)
        self.upload_packages_file = os.path.join(self.upload_dir, "Packages")

    def testCreateFilteredPackageIndex(self) -> None:
        """CreateDevInstallPackageFile writes updated file to disk."""
        binhost.CreateFilteredPackageIndex(
            self.root,
            self.devinstall_package_list,
            self.upload_packages_file,
            "gs://chromeos-prebuilt",
            "target/",
        )

        # We need to verify that a file was created at
        # self.devinstall_package_list
        actual = binpkg.GrabLocalPackageIndex(self.upload_dir)
        self.assertEqual(actual.header["URI"], "gs://chromeos-prebuilt")
        self.assertEqual(int(actual.header["TTL"]), 60 * 60 * 24 * 365)
        self.assertEqual(
            actual.packages,
            [
                {
                    "CPV": "virtual/python-enum34-1",
                    "PATH": "target/virtual/python-enum34-1.tbz2",
                }
            ],
        )


class CreateChromePackageIndexTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for CreateChromePackageIndex."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        self.sysroot_path = Path("/build/foo")
        self.pkgs_dir = self.sysroot_path / "packages"
        self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)

        packages_content = """\
ARCH: amd64
TTL: 0

CPV: package/exclude-1

CPV: chromeos-base/chromeos-chrome-100.0.0-r1

CPV: chromeos-base/chrome-icu-100.0.0-r1

CPV: package/exclude-2
    """
        package_index_file_path = self.chroot.full_path(
            self.pkgs_dir / "Packages"
        )
        osutils.Touch(package_index_file_path, makedirs=True)
        osutils.WriteFile(package_index_file_path, packages_content)

        self.upload_dir = Path(self.chroot.tmp) / "upload_dir"
        osutils.SafeMakedirs(self.upload_dir)
        self.upload_packages_file = self.upload_dir / "Packages"

        self.PatchObject(os.path, "exists", return_value=True)
        self.fake_packages = [
            portage_util.InstalledPackage(
                None, "", category="package", pf="exclude-1"
            ),
            portage_util.InstalledPackage(
                None,
                "",
                category=constants.CHROME_CN,
                pf="chromeos-chrome-100.0.0-r1",
            ),
            portage_util.InstalledPackage(
                None,
                "",
                category=constants.CHROME_CN,
                pf="chrome-icu-100.0.0-r1",
            ),
            portage_util.InstalledPackage(
                None, "", category="package", pf="exclude-2"
            ),
        ]
        self.PatchObject(
            portage_util.PortageDB,
            "InstalledPackages",
            return_value=self.fake_packages,
        )

    def testCreateChromePackageIndex(self) -> None:
        """CreateChromePackageIndex writes updated file to disk."""
        actual_packages = binhost.CreateChromePackageIndex(
            self.chroot,
            self.sysroot,
            self.upload_packages_file,
            "gs://chromeos-prebuilt",
            "target/",
        )
        actual_packages_content = osutils.ReadFile(
            self.upload_packages_file
        ).splitlines()

        self.assertEqual(
            [
                "chromeos-base/chromeos-chrome-100.0.0-r1.tbz2",
                "chromeos-base/chrome-icu-100.0.0-r1.tbz2",
            ],
            actual_packages,
        )
        self.assertIn(
            "CPV: chromeos-base/chromeos-chrome-100.0.0-r1",
            actual_packages_content,
        )
        self.assertIn(
            "PATH: target/chromeos-base/chromeos-chrome-100.0.0-r1.tbz2",
            actual_packages_content,
        )
        self.assertIn(
            "CPV: chromeos-base/chrome-icu-100.0.0-r1", actual_packages_content
        )
        self.assertIn(
            "PATH: target/chromeos-base/chrome-icu-100.0.0-r1.tbz2",
            actual_packages_content,
        )
        self.assertNotIn("CPV: package/exclude-1", actual_packages_content)
        self.assertNotIn("CPV: package/exclude-2", actual_packages_content)


class GetSnapshotShasTest(
    cros_test_lib.MockTempDirTestCase, cros_test_lib.LoggingTestCase
):
    """Unittests for the _get_snapshot_shas function.

    The _get_snapshot_shas_from_git_log function is also tested here when it is
    called internally and the relevant functions are mocked.
    """

    def setUp(self) -> None:
        self.find_repo_mock = self.PatchObject(repo_util.Repository, "MustFind")
        self.has_remote_mock = (
            self.find_repo_mock.return_value.Manifest.return_value.HasRemote
        )
        self.git_log_mock = self.PatchObject(git, "Log")
        self.source_root_mock = self.PatchObject(
            constants, "SOURCE_ROOT", new=self.tempdir
        )
        self.manifest_checkout_mock = self.PatchObject(git, "ManifestCheckout")

    def testInternalSuccess(self) -> None:
        """Test basic internal success case."""
        self.has_remote_mock.side_effect = (False, True)
        self.git_log_mock.side_effect = (
            "internal-snapshot-sha1\ninternal-snapshot-sha2",
        )

        result = binhost._get_snapshot_shas()

        self.git_log_mock.assert_called_with(
            os.path.join(self.tempdir, "manifest-internal"),
            format="format:%H",
            max_count=5,
            rev="cros-internal/snapshot",
        )
        self.assertEqual(
            ["internal-snapshot-sha1", "internal-snapshot-sha2"],
            result.internal,
        )
        self.assertEqual([], result.external)

    def testExternalSuccess(self) -> None:
        """Test basic external success case."""
        self.has_remote_mock.side_effect = (True, False)
        self.git_log_mock.side_effect = (
            "external-snapshot-sha1\nexternal-snapshot-sha2",
        )

        result = binhost._get_snapshot_shas()

        self.git_log_mock.assert_called_with(
            os.path.join(self.tempdir, "manifest"),
            format="format:%H",
            max_count=5,
            rev="cros/snapshot",
        )
        self.assertEqual(
            ["external-snapshot-sha1", "external-snapshot-sha2"],
            result.external,
        )
        self.assertEqual([], result.internal)

    def testRepoBranch(self) -> None:
        """Test when a non-default branch is used."""
        self.has_remote_mock.side_effect = (True, False)
        self.git_log_mock.side_effect = (
            "external-snapshot-sha1\nexternal-snapshot-sha2",
        )
        self.manifest_checkout_mock.return_value.manifest_branch = "stable"

        result = binhost._get_snapshot_shas()

        self.git_log_mock.assert_called_with(
            os.path.join(self.tempdir, "manifest"),
            format="format:%H",
            max_count=5,
            rev="cros/stable",
        )
        self.assertEqual(
            ["external-snapshot-sha1", "external-snapshot-sha2"],
            result.external,
        )
        self.assertEqual([], result.internal)

    def testGetSnapshotShasRepoError(self) -> None:
        """Test repo error when getting snapshot SHAs."""
        with cros_test_lib.LoggingCapturer() as logs:
            self.find_repo_mock.side_effect = repo_util.NotInRepoError()

            result = binhost._get_snapshot_shas()

            self.AssertLogsContain(logs, "Unable to determine a repo directory")
            self.assertEqual([], result.external)
            self.assertEqual([], result.internal)

    def testGetSnapshotShasGitError(self) -> None:
        """Test git error when getting snapshot SHAs."""
        with cros_test_lib.LoggingCapturer() as logs:
            self.git_log_mock.side_effect = cros_build_lib.RunCommandError(
                "Run Command Error."
            )
            result = binhost._get_snapshot_shas()

            self.AssertLogsContain(logs, "Run Command Error.")
            self.assertEqual([], result.external)
            self.assertEqual([], result.internal)


@pytest.fixture(scope="class")
def mock_lookup_binhosts_response_object(request):
    """Fixture to mock a LookupBinhostsResponse object."""
    created_at = timestamp_pb2.Timestamp()
    created_at.FromJsonString(MOCK_DATE_STRING)

    # Construct a LookupBinhostsResponse object.
    response = prebuilts_cloud_pb2.LookupBinhostsResponse()
    response.binhosts.append(
        prebuilts_cloud_pb2.LookupBinhostsResponse.Binhost(
            binhost_id=MOCK_BINHOST_ID,
            gs_uri=MOCK_GS_URI,
            created_at=created_at,
        )
    )

    # Encode the protobuf message with base64.
    request.cls.mock_lookup_binhosts_response_object = base64.urlsafe_b64encode(
        response.SerializeToString()
    )


@pytest.mark.usefixtures("mock_lookup_binhosts_response_object")
class FetchBinhostsTest(
    cros_test_lib.MockTestCase,
    cros_test_lib.LoggingTestCase,
):
    """Tests for _fetch_binhosts."""

    FETCH_BINHOSTS_MOCK_ARGS = (
        [MOCK_SNAPSHOT_SHA],
        MOCK_BUILD_TARGET_NAME,
        MOCK_PROFILE,
        False,
        True,
        MOCK_GENERIC_BUILD_TARGET_NAME,
        MOCK_GENERIC_PROFILE,
        True,
    )

    def setUp(self):
        self.requests_mock = self.PatchObject(requests, "request")

    def _set_requests_mock_response(self, status_code, content):
        """Helper function to set the mock API response."""
        api_response = requests.models.Response()
        api_response.status_code = status_code
        api_response._content = content
        self.requests_mock.return_value = api_response

    def test_success(self):
        """Test successful fetching of binhosts."""
        self._set_requests_mock_response(
            200, self.mock_lookup_binhosts_response_object
        )

        assert binhost._fetch_binhosts(*self.FETCH_BINHOSTS_MOCK_ARGS) == (
            [MOCK_GS_URI]
        )

    def test_binhosts_not_found(self):
        """Test failure case when no binhosts are found."""
        self._set_requests_mock_response(
            404, "No binhosts found with the given parameters"
        )

        with cros_test_lib.LoggingCapturer() as logs:
            binhost._fetch_binhosts(*self.FETCH_BINHOSTS_MOCK_ARGS)
            self.AssertLogsContain(
                logs, "No suitable binhosts found in the binhost lookup service"
            )

    def test_fetching_error(self):
        """Test failure case when there is an error while fetching binhosts."""
        self._set_requests_mock_response(
            400, "Unable to parse filter parameters from the request."
        )

        with self.assertRaises(binhost.BinhostsLookupServiceError):
            binhost._fetch_binhosts(*self.FETCH_BINHOSTS_MOCK_ARGS)


class LookupBinhostsTest(cros_test_lib.MockTestCase):
    """Test the lookup_binhosts function."""

    INTERNAL_GS_URIS = ["gs://internal/binhost1", "gs://internal/binhost2"]
    INTERNAL_SNAPSHOT_SHAS = [
        "internal_snapshot_sha1",
        "internal_snapshot_sha2",
    ]
    EXTERNAL_GS_URIS = ["gs://external/binhost1", "gs://external/binhost2"]
    EXTERNAL_SNAPSHOT_SHAS = [
        "external_snapshot_sha1",
        "external_snapshot_sha2",
    ]
    BINHOST_LOOKUP_SERVICE_DATA = prebuilts_cloud_pb2.BinhostLookupServiceData(
        snapshot_shas=INTERNAL_SNAPSHOT_SHAS, private=True, is_staging=True
    )

    def setUp(self):
        self.PatchObject(config_lib, "GetSiteParams")
        self.repo_mock = self.PatchObject(repo_util, "Repository")
        self.get_snapshot_shas = self.PatchObject(binhost, "_get_snapshot_shas")
        self.fetch_binhosts = self.PatchObject(binhost, "_fetch_binhosts")
        self.sysroot = self.PatchObject(sysroot_lib, "Sysroot")

    def testInputSnapshotShas(self):
        """Test when snapshot SHAs are passed as input."""

        self.fetch_binhosts.return_value = (
            self.INTERNAL_GS_URIS + self.EXTERNAL_GS_URIS
        )

        result = binhost.lookup_binhosts(
            MOCK_BUILD_TARGET,
            self.BINHOST_LOOKUP_SERVICE_DATA,
        )

        self.assertEqual(
            result,
            [
                "gs://external/binhost2",
                "gs://external/binhost1",
                "gs://internal/binhost2",
                "gs://internal/binhost1",
            ],
        )

    def testCheckoutSnapshotShas(self):
        """Test when manifest SHAs from the checkout are used as input."""
        self.get_snapshot_shas.return_value = binhost.SnapshotShas(
            self.EXTERNAL_SNAPSHOT_SHAS, self.INTERNAL_SNAPSHOT_SHAS
        )
        self.fetch_binhosts.return_value = (
            self.INTERNAL_GS_URIS + self.EXTERNAL_GS_URIS
        )

        result = binhost.lookup_binhosts(
            MOCK_BUILD_TARGET,
            self.BINHOST_LOOKUP_SERVICE_DATA,
        )

        self.fetch_binhosts.assert_called_with(
            self.INTERNAL_SNAPSHOT_SHAS,
            MOCK_BUILD_TARGET.name,
            MOCK_BUILD_TARGET.profile,
            mock.ANY,
            mock.ANY,
            mock.ANY,
            mock.ANY,
            True,
        )
        self.assertEqual(
            result,
            [
                "gs://external/binhost2",
                "gs://external/binhost1",
                "gs://internal/binhost2",
                "gs://internal/binhost1",
            ],
        )

    def testMainBranch(self):
        """Test that nothing is returned with a main branch."""

        self.repo_mock.MustFind.return_value.GetBranch.return_value = "main"

        self.fetch_binhosts.return_value = (
            self.INTERNAL_GS_URIS + self.EXTERNAL_GS_URIS
        )

        result = binhost.lookup_binhosts(
            MOCK_BUILD_TARGET,
            None,
        )

        self.assertEqual(
            list(result),
            [
                "gs://external/binhost2",
                "gs://external/binhost1",
                "gs://internal/binhost2",
                "gs://internal/binhost1",
            ],
        )

    def testNonMainBranch(self):
        """Test that nothing is returned with a non-main branch."""

        self.repo_mock.GetBranch.return_value = "factory-branch"

        self.fetch_binhosts.return_value = (
            self.INTERNAL_GS_URIS + self.EXTERNAL_GS_URIS
        )

        result = binhost.lookup_binhosts(
            MOCK_BUILD_TARGET,
            None,
        )

        self.assertEqual(
            list(result),
            [],
        )


@pytest.mark.parametrize(
    "uri,expected",
    [
        ("gs://garbage", f"{gs_urls_util.PUBLIC_BASE_HTTPS_URL}garbage"),
        (
            "gs://chromeos-dev-installer",
            f"{gs_urls_util.PUBLIC_BASE_HTTPS_URL}chromeos-dev-installer",
        ),
        ("https://google.com", "https://google.com"),
        (
            f"{gs_urls_util.PUBLIC_BASE_HTTPS_URL}chromeos-dev-installer",
            f"{gs_urls_util.PUBLIC_BASE_HTTPS_URL}chromeos-dev-installer",
        ),
    ],
)
def test_convert_gs_upload_uri(uri, expected) -> None:
    """Ensure we're converting gs:// URIs to https:// in an expected way."""
    assert binhost.ConvertGsUploadUri(uri) == expected
