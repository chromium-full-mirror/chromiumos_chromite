# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the chromeos_version module."""

import os
import tempfile

from chromite.lib import chromeos_version
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import git
from chromite.lib import osutils


FAKE_VERSION = """
CHROMEOS_BUILD=%(build_number)s
CHROMEOS_BRANCH=%(branch_build_number)s
CHROMEOS_PATCH=%(patch_number)s
CHROME_BRANCH=%(chrome_branch)s
"""

FAKE_VERSION_STRING = "1.2.3"
CHROME_BRANCH = "13"
FAKE_DATE_STRING = "2022_07_20_203326"
FAKE_DEV_VERSION_STRING = f"{FAKE_VERSION_STRING}-d{FAKE_DATE_STRING}"


class VersionInfoTest(cros_test_lib.MockTempDirTestCase):
    """Test methods testing methods in VersionInfo class."""

    @classmethod
    def WriteFakeVersionFile(
        cls, version_file, version=None, chrome_branch=None
    ) -> None:
        """Helper method to write a version file for |version|."""
        if version is None:
            version = FAKE_VERSION_STRING
        if chrome_branch is None:
            chrome_branch = CHROME_BRANCH

        osutils.SafeMakedirs(os.path.split(version_file)[0])
        info = chromeos_version.VersionInfo(version, chrome_branch)
        osutils.WriteFile(version_file, FAKE_VERSION % info.__dict__)

    @classmethod
    def CreateFakeVersionFile(cls, tmpdir, version=None, chrome_branch=None):
        """Helper method to create a version file for |version|."""
        version_file = tempfile.mktemp(dir=tmpdir)
        cls.WriteFakeVersionFile(
            version_file, version=version, chrome_branch=chrome_branch
        )
        return version_file

    def setUp(self) -> None:
        self.PatchObject(
            chromeos_version.VersionInfo,
            "_GetDateTime",
            return_value=FAKE_DATE_STRING,
        )

    def testLoadFromFile(self) -> None:
        """Tests whether we can load from a version file."""
        version_file = self.CreateFakeVersionFile(self.tempdir)
        # Test for Dev/Local Builds.
        info = chromeos_version.VersionInfo(version_file=version_file)
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)
        self.assertEqual(
            info.VersionStringWithDateTime(), FAKE_DEV_VERSION_STRING
        )
        # Test for Official.
        os.environ["CHROMEOS_OFFICIAL"] = "1"
        info = chromeos_version.VersionInfo(version_file=version_file)
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)
        self.assertEqual(info.VersionStringWithDateTime(), FAKE_VERSION_STRING)

    def testSuffixes(self) -> None:
        VERSION = "12345.0.0"
        VERSION_WITH_BRANCH = "12345.0.0-R1234"
        VERSION_WITH_SNAPSHOT = "12345.0.0-12345"
        VERSION_WITH_SNAPSHOT_AND_BRANCH = "12345.0.0-12345-R1234"

        # Tests the version with snapshot suffix.
        info = chromeos_version.VersionInfo(
            version_string=VERSION_WITH_SNAPSHOT
        )
        self.assertEqual(info.VersionString(), VERSION_WITH_SNAPSHOT)

        # Tests the version with snapshot and branch suffixes.
        info = chromeos_version.VersionInfo(
            version_string=VERSION_WITH_SNAPSHOT_AND_BRANCH
        )
        self.assertEqual(info.VersionString(), VERSION_WITH_SNAPSHOT)

        # Tests the version with branch suffix.
        info = chromeos_version.VersionInfo(version_string=VERSION_WITH_BRANCH)
        self.assertEqual(info.VersionString(), VERSION)

    def testLoadFromRepo(self) -> None:
        """Tests whether we can load from a source repo."""
        version_file = os.path.join(self.tempdir, constants.VERSION_FILE)
        self.WriteFakeVersionFile(version_file)
        # Test for Dev/Local Builds.
        info = chromeos_version.VersionInfo.from_repo(self.tempdir)
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)
        self.assertEqual(
            info.VersionStringWithDateTime(), FAKE_DEV_VERSION_STRING
        )
        # Test for Official.
        os.environ["CHROMEOS_OFFICIAL"] = "1"
        info = chromeos_version.VersionInfo.from_repo(self.tempdir)
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)
        self.assertEqual(info.VersionStringWithDateTime(), FAKE_VERSION_STRING)

    def testLoadFromString(self) -> None:
        """Tests whether we can load from a string."""
        info = chromeos_version.VersionInfo(FAKE_VERSION_STRING, CHROME_BRANCH)
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)
        self.assertEqual(info.VersionStringWithDateTime(), FAKE_VERSION_STRING)

    def CommonTestIncrementVersion(
        self, incr_type, version, chrome_branch=None
    ):
        """Common test increment.  Returns path to new incremented file."""
        message = "Incrementing cuz I sed so"
        create_mock = self.PatchObject(git, "CreateBranch")
        push_mock = self.PatchObject(
            chromeos_version.VersionInfo, "_PushGitChanges"
        )
        clean_mock = self.PatchObject(git, "CleanAndCheckoutUpstream")

        version_file = self.CreateFakeVersionFile(
            self.tempdir, version=version, chrome_branch=chrome_branch
        )
        info = chromeos_version.VersionInfo(
            version_file=version_file, incr_type=incr_type
        )
        info.IncrementVersion()
        info.UpdateVersionFile(message, dry_run=False)

        # pylint: disable=protected-access
        create_mock.assert_called_once_with(
            self.tempdir, chromeos_version._PUSH_BRANCH
        )
        # pylint: enable=protected-access

        push_mock.assert_called_once_with(self.tempdir, message, False, None)
        clean_mock.assert_called_once_with(self.tempdir)

        return version_file

    def testIncrementVersionPatch(self) -> None:
        """Tests whether we can increment a version file by patch number."""
        version_file = self.CommonTestIncrementVersion("branch", "1.2.3")
        new_info = chromeos_version.VersionInfo(
            version_file=version_file, incr_type="branch"
        )
        self.assertEqual(new_info.VersionString(), "1.2.4")

    def testIncrementVersionBranch(self) -> None:
        """Tests whether we can increment a version file by branch number."""
        version_file = self.CommonTestIncrementVersion("branch", "1.2.0")
        new_info = chromeos_version.VersionInfo(
            version_file=version_file, incr_type="branch"
        )
        self.assertEqual(new_info.VersionString(), "1.3.0")

    def testIncrementVersionBuild(self) -> None:
        """Tests whether we can increment a version file by build number."""
        version_file = self.CommonTestIncrementVersion("build", "1.0.0")
        new_info = chromeos_version.VersionInfo(
            version_file=version_file, incr_type="build"
        )
        self.assertEqual(new_info.VersionString(), "2.0.0")

    def testIncrementVersionChrome(self) -> None:
        """Tests whether we can increment the chrome version."""
        version_file = self.CommonTestIncrementVersion(
            "chrome_branch", version="1.0.0", chrome_branch="29"
        )
        new_info = chromeos_version.VersionInfo(version_file=version_file)
        self.assertEqual(new_info.VersionString(), "2.0.0")
        self.assertEqual(new_info.chrome_branch, "30")

    def testCompareEqual(self) -> None:
        """Verify comparisons of equal versions."""
        lhs = chromeos_version.VersionInfo(version_string="1.2.3")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3")
        self.assertFalse(lhs < rhs)
        self.assertTrue(lhs <= rhs)
        self.assertTrue(lhs == rhs)
        self.assertFalse(lhs != rhs)
        self.assertFalse(lhs > rhs)
        self.assertTrue(lhs >= rhs)

        lhs = chromeos_version.VersionInfo(version_string="1.2.3-12345")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3-12345")
        self.assertFalse(lhs < rhs)
        self.assertTrue(lhs <= rhs)
        self.assertTrue(lhs == rhs)
        self.assertFalse(lhs != rhs)
        self.assertFalse(lhs > rhs)
        self.assertTrue(lhs >= rhs)

    def testCompareLess(self) -> None:
        """Verify comparisons of less versions."""
        lhs = chromeos_version.VersionInfo(version_string="1.0.3")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3")
        self.assertTrue(lhs < rhs)
        self.assertTrue(lhs <= rhs)
        self.assertFalse(lhs == rhs)
        self.assertTrue(lhs != rhs)
        self.assertFalse(lhs > rhs)
        self.assertFalse(lhs >= rhs)

        lhs = chromeos_version.VersionInfo(version_string="1.2.3-12345")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3")
        self.assertFalse(lhs < rhs)
        self.assertFalse(lhs <= rhs)
        self.assertFalse(lhs == rhs)
        self.assertTrue(lhs != rhs)
        self.assertTrue(lhs > rhs)
        self.assertTrue(lhs >= rhs)

        lhs = chromeos_version.VersionInfo(version_string="1.2.3-12344")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3-12345")
        self.assertTrue(lhs < rhs)
        self.assertTrue(lhs <= rhs)
        self.assertFalse(lhs == rhs)
        self.assertTrue(lhs != rhs)
        self.assertFalse(lhs > rhs)
        self.assertFalse(lhs >= rhs)

    def testCompareGreater(self) -> None:
        """Verify comparisons of greater versions."""
        lhs = chromeos_version.VersionInfo(version_string="1.2.4")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3")
        self.assertFalse(lhs < rhs)
        self.assertFalse(lhs <= rhs)
        self.assertFalse(lhs == rhs)
        self.assertTrue(lhs != rhs)
        self.assertTrue(lhs > rhs)
        self.assertTrue(lhs >= rhs)

        lhs = chromeos_version.VersionInfo(version_string="1.2.3")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3-12345")
        self.assertTrue(lhs < rhs)
        self.assertTrue(lhs <= rhs)
        self.assertFalse(lhs == rhs)
        self.assertTrue(lhs != rhs)
        self.assertFalse(lhs > rhs)
        self.assertFalse(lhs >= rhs)

        lhs = chromeos_version.VersionInfo(version_string="1.2.3-12346")
        rhs = chromeos_version.VersionInfo(version_string="1.2.3-12345")
        self.assertFalse(lhs < rhs)
        self.assertFalse(lhs <= rhs)
        self.assertFalse(lhs == rhs)
        self.assertTrue(lhs != rhs)
        self.assertTrue(lhs > rhs)
        self.assertTrue(lhs >= rhs)


class VersionCheckMethodsTest(cros_test_lib.TestCase):
    """Test methods testing methods verifying a version string."""

    VERSION = "4567.8.9"
    FULL_VERSION = "R26-4567.8.9"
    VERSION_WITH_SNAPSHOT = "4567.8.9-12345"
    FULL_VERSION_WITH_SNAPSHOT = "R26-4567.8.9-12345-88888"

    WRONG_FORMAT_VERSION1 = "1331488"
    WRONG_FORMAT_VERSION2 = "129.0.6614.2"
    WRONG_FORMAT_VERSION3 = "89.0.4357.3_rc-r1"
    WRONG_FORMAT_VERSION4 = "R99-1234.B"

    def testIsPlatformVersionn(self) -> None:
        """Tests IsVersion method."""
        self.assertTrue(chromeos_version.IsPlatformVersion(self.VERSION))
        self.assertTrue(
            chromeos_version.IsPlatformVersion(self.VERSION_WITH_SNAPSHOT)
        )
        self.assertFalse(chromeos_version.IsPlatformVersion(self.FULL_VERSION))
        self.assertFalse(
            chromeos_version.IsPlatformVersion(self.FULL_VERSION_WITH_SNAPSHOT)
        )
        self.assertFalse(
            chromeos_version.IsPlatformVersion(self.WRONG_FORMAT_VERSION1)
        )
        self.assertFalse(
            chromeos_version.IsPlatformVersion(self.WRONG_FORMAT_VERSION2)
        )
        self.assertFalse(
            chromeos_version.IsPlatformVersion(self.WRONG_FORMAT_VERSION3)
        )
        self.assertFalse(
            chromeos_version.IsPlatformVersion(self.WRONG_FORMAT_VERSION4)
        )

    def testIsFullVersion(self) -> None:
        """Tests IsFullVersion method."""
        self.assertFalse(chromeos_version.IsFullVersion(self.VERSION))
        self.assertFalse(
            chromeos_version.IsFullVersion(self.VERSION_WITH_SNAPSHOT)
        )
        self.assertTrue(chromeos_version.IsFullVersion(self.FULL_VERSION))
        self.assertTrue(
            chromeos_version.IsFullVersion(self.FULL_VERSION_WITH_SNAPSHOT)
        )
        self.assertFalse(
            chromeos_version.IsFullVersion(self.WRONG_FORMAT_VERSION1)
        )
        self.assertFalse(
            chromeos_version.IsFullVersion(self.WRONG_FORMAT_VERSION2)
        )
        self.assertFalse(
            chromeos_version.IsFullVersion(self.WRONG_FORMAT_VERSION3)
        )
        self.assertFalse(
            chromeos_version.IsFullVersion(self.WRONG_FORMAT_VERSION4)
        )

    def testIsFullVersionWithSnapshotSuffix(self) -> None:
        """Tests IsSnapshotFullVersion method."""
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(self.VERSION)
        )
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(
                self.VERSION_WITH_SNAPSHOT
            )
        )
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(self.FULL_VERSION)
        )
        self.assertTrue(
            chromeos_version.IsFullVersionWithSnapshotSuffix(
                self.FULL_VERSION_WITH_SNAPSHOT
            )
        )
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(
                self.WRONG_FORMAT_VERSION1
            )
        )
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(
                self.WRONG_FORMAT_VERSION2
            )
        )
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(
                self.WRONG_FORMAT_VERSION3
            )
        )
        self.assertFalse(
            chromeos_version.IsFullVersionWithSnapshotSuffix(
                self.WRONG_FORMAT_VERSION4
            )
        )
