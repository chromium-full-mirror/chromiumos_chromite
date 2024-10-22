# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the logic to find ChromeOS image version for a board."""

from chromite.lib import chrome_lkgm
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib import gs_unittest
from chromite.lib import osutils
from chromite.lib import partial_mock


class GetChromeLkgmTest(
    cros_test_lib.MockTempDirTestCase,
    cros_test_lib.LoggingTestCase,
):
    """Tests GetChromeLkgm method."""

    def setUp(self) -> None:
        (self.tempdir / constants.PATH_TO_CHROME_LKGM).parent.mkdir(
            parents=True, exist_ok=True
        )

    def testLkgm(self) -> None:
        """Test normal case."""
        osutils.WriteFile(
            self.tempdir / constants.PATH_TO_CHROME_LKGM, "12345.6.7"
        )
        self.assertEqual(
            chrome_lkgm.GetChromeLkgm(self.tempdir), ("12345.6.7", None)
        )

    def testLkgmWithSnapshot(self) -> None:
        """Test normal case (with snapshot suffix)."""
        osutils.WriteFile(
            self.tempdir / constants.PATH_TO_CHROME_LKGM, "12345.6.7-123456"
        )
        self.assertEqual(
            chrome_lkgm.GetChromeLkgm(self.tempdir), ("12345.6.7", 123456)
        )

    def testLkgmWithExtraLF(self) -> None:
        """Test normal case with an extra new line at the end."""
        osutils.WriteFile(
            self.tempdir / constants.PATH_TO_CHROME_LKGM, "12345.6.7\n"
        )
        self.assertEqual(
            chrome_lkgm.GetChromeLkgm(self.tempdir), ("12345.6.7", None)
        )

    def testLkgmWithSnnapshotAndExtraLF(self) -> None:
        """Test normal case with an extra new line at the end."""
        osutils.WriteFile(
            self.tempdir / constants.PATH_TO_CHROME_LKGM, "12345.6.7-123456\n"
        )
        self.assertEqual(
            chrome_lkgm.GetChromeLkgm(self.tempdir), ("12345.6.7", 123456)
        )

    def testEmptyLKGM(self) -> None:
        """Test case of an empty LKGM file."""
        osutils.WriteFile(self.tempdir / constants.PATH_TO_CHROME_LKGM, "")
        self.assertRaises(RuntimeError, chrome_lkgm.GetChromeLkgm, self.tempdir)

    def testNonexistentLKGM(self) -> None:
        """Test case of non-existent LKGM file."""
        self.assertRaises(
            chrome_lkgm.MissingLkgmFile, chrome_lkgm.GetChromeLkgm, self.tempdir
        )


class ChromeOSVersionFinderTest(
    gs_unittest.AbstractGSContextTest,
    cros_test_lib.MockTempDirTestCase,
    cros_test_lib.LoggingTestCase,
):
    """Tests the determination of which SDK version to use."""

    VERSION = "3543.0.0"
    SNAPSHOT = 123456
    FULL_VERSION = "R55-%s" % VERSION
    FULL_VERSION_WITH_SNAPSHOT = "R55-%s-%s-888888" % (VERSION, SNAPSHOT)
    RECENT_VERSION_MISSING = "3542.0.0"
    RECENT_VERSION_FOUND = "3541.0.0"
    EVEN_OLDER_VERSION = "3540.0.0"
    FULL_VERSION_RECENT = "R55-%s" % RECENT_VERSION_FOUND
    FULL_VERSION_WITH_SNAPSHOT_OLDER_PLATFORM_VERSION = "R55-%s-%s-888888" % (
        RECENT_VERSION_FOUND,
        SNAPSHOT - 60,
    )
    FULL_VERSION_WITH_SNAPSHOT_EVEN_OLDER_PLATFORM_VERSION = (
        "R55-%s-%s-888888" % (EVEN_OLDER_VERSION, SNAPSHOT - 60)
    )
    BRANCH_VERSION = "3541.68.0"
    FILL_VERSION_BRANCH = "R55-%s" % BRANCH_VERSION
    MINI_BRANCH_VERSION = "3543.2.1"
    FULL_VERSION_MINI_BRANCH = "R55-%s" % MINI_BRANCH_VERSION
    BOARD = "eve"

    VERSION_BASE = "gs://chromeos-image-archive/%s-release/LATEST-%s" % (
        BOARD,
        VERSION,
    )

    CAT_ERROR = "CommandException: No URLs matched %s" % VERSION_BASE

    def setUp(self) -> None:
        self.finder = chrome_lkgm.ChromeOSVersionFinder(
            self.tempdir, self.BOARD, 10
        )

    def testGsName(self) -> None:
        """Test GS bases contain the given board name."""
        self.assertTrue(self.BOARD in self.finder.gs_base)
        self.assertTrue(self.BOARD in self.finder.snapshot_gs_base)

    def testFullVersionFromPlatformVersion(self) -> None:
        """Test full version calculation from the platform version."""
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % self.VERSION),
            stdout=self.FULL_VERSION,
        )
        self.assertEqual(
            self.FULL_VERSION,
            self.finder.GetFullVersionFromLatestFile(self.VERSION),
        )

    def _SetupMissingVersions(self) -> None:
        """Version & Version-1 are missing, but Version-2 exists."""

        def _RaiseGSNoSuchKey(*_args, **_kwargs) -> None:
            raise gs.GSNoSuchKey("file does not exist")

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % self.VERSION),
            side_effect=_RaiseGSNoSuchKey,
        )
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-%s" % self.RECENT_VERSION_MISSING
            ),
            side_effect=_RaiseGSNoSuchKey,
        )
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-%s" % self.RECENT_VERSION_FOUND
            ),
            stdout=self.FULL_VERSION_RECENT,
        )

    def _SetupMissingSnapshots(
        self, exists: int, latest: int, version: str
    ) -> None:
        """Setup missing snapshots based on Args.

        [exists + 1, latest] missing, [exists] exists with version.
        """

        def _RaiseGSNoSuchKey(*_args, **_kwargs) -> None:
            raise gs.GSNoSuchKey("file does not exist")

        for i in range(exists + 1, latest + 1):
            self.gs_mock.AddCmdResult(
                partial_mock.ListRegex("cat .*/LATEST-SNAPSHOT-%s" % i),
                side_effect=_RaiseGSNoSuchKey,
            )

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-SNAPSHOT-%s" % exists),
            stdout=version,
        )

    def testFullVersionFromSnapshotId(self) -> None:
        """Test full version calculation from the snapshot id."""
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-SNAPSHOT-%s" % self.SNAPSHOT),
            stdout=self.FULL_VERSION_WITH_SNAPSHOT,
        )
        self.assertEqual(
            self.FULL_VERSION_WITH_SNAPSHOT,
            self.finder.GetFullVersionFromLatestSnapshotFile(self.SNAPSHOT),
        )

    def testNoFallbackVersion(self) -> None:
        """Test that all versions are checked before returning None."""

        def _RaiseGSNoSuchKey(*_args, **_kwargs) -> None:
            raise gs.GSNoSuchKey("file does not exist")

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-*"),
            side_effect=gs.GSNoSuchKey,
        )
        self.finder.fallback_versions = 2000000
        with cros_test_lib.LoggingCapturer() as logs:
            self.assertEqual(
                None, self.finder.GetFullVersionFromLatestFile(self.VERSION)
            )
        self.AssertLogsContain(logs, "LATEST-1.0.0")
        self.AssertLogsContain(logs, "LATEST--1.0.0", inverted=True)

    def testFallbackVersions(self) -> None:
        """Test full version calculation with various fallback versions."""
        self._SetupMissingVersions()
        for version in range(6):
            self.finder.fallback_versions = version
            # _SetupMissingVersions mocks the result of 3 files.
            # The file ending with LATEST-3.0.0 is the only one that would pass.
            self.assertEqual(
                self.FULL_VERSION_RECENT if version >= 3 else None,
                self.finder.GetFullVersionFromLatestFile(self.VERSION),
            )

    def testFallbackSnapshots(self) -> None:
        """Test full version calculation with various fallback snapshots."""
        # _SetupMissingSnapshots mocks the result of 3 * SNAPSHOTS_PER_VERSION
        # files, thus cur-3n+1 exists, [cur-3n+2, cur] missing.
        self._SetupMissingSnapshots(
            self.SNAPSHOT - 3 * chrome_lkgm.SNAPSHOTS_PER_VERSION + 1,
            self.SNAPSHOT,
            self.FULL_VERSION_WITH_SNAPSHOT,
        )
        for version in range(6):
            self.finder.fallback_versions = version
            self.assertEqual(
                self.FULL_VERSION_WITH_SNAPSHOT if version >= 3 else None,
                self.finder.GetFullVersionFromLatestSnapshotFile(self.SNAPSHOT),
            )

    def testFallbackSnapshotsPreviousPlatformVersion(self) -> None:
        # Found latest snapshots at platform 3541.0.0
        self._SetupMissingSnapshots(
            self.SNAPSHOT - 3 * chrome_lkgm.SNAPSHOTS_PER_VERSION + 1,
            self.SNAPSHOT,
            self.FULL_VERSION_WITH_SNAPSHOT_OLDER_PLATFORM_VERSION,
        )
        # Latest release image also at platform 3541.0.0
        self._SetupMissingVersions()
        self.finder.fallback_versions = 5
        self.assertEqual(
            # Use snapshot since snapshot is newer.
            self.FULL_VERSION_WITH_SNAPSHOT_OLDER_PLATFORM_VERSION,
            self.finder.GetLatestVersionInfo(self.VERSION, self.SNAPSHOT),
        )

    def testFallbackSnapshotsPreviousPlatformVersionUseRelease(self) -> None:
        # Found latest snapshot at platform 3540.0.0
        self._SetupMissingSnapshots(
            self.SNAPSHOT - 3 * chrome_lkgm.SNAPSHOTS_PER_VERSION + 1,
            self.SNAPSHOT,
            self.FULL_VERSION_WITH_SNAPSHOT_EVEN_OLDER_PLATFORM_VERSION,
        )
        # Setup latest release at platform 3541.0.0
        self._SetupMissingVersions()
        self.finder.fallback_versions = 5
        self.assertEqual(
            # Use release image.
            self.FULL_VERSION_RECENT,
            self.finder.GetLatestVersionInfo(self.VERSION, self.SNAPSHOT),
        )

    def testBranchFallbackVersions(self) -> None:
        """Test full version calculation for a branch version with fallbacks."""
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % "12345.89.0"),
            side_effect=gs.GSNoSuchKey,
        )
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % "12345.88.0"),
            side_effect=gs.GSNoSuchKey,
        )
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % "12345.87.0"),
            stdout="R123-12345.87.0",
        )
        self.assertEqual(
            self.finder.GetFullVersionFromLatestFile("12345.89.0"),
            "R123-12345.87.0",
        )

    def testBranchNoFallbackVersions(self) -> None:
        """Test version calculation for a branch version with no fallbacks."""
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*-release/LATEST-*"),
            side_effect=gs.GSNoSuchKey,
        )
        self.assertEqual(
            self.finder.GetFullVersionFromLatestFile("12345.89.0"), None
        )

    def testMiniBranchFullVersion(self) -> None:
        """Test full version calculation for a mini branch version."""
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-%s" % self.MINI_BRANCH_VERSION
            ),
            stdout=self.FULL_VERSION_MINI_BRANCH,
        )
        self.assertEqual(
            self.FULL_VERSION_MINI_BRANCH,
            self.finder.GetFullVersionFromLatestFile(self.MINI_BRANCH_VERSION),
        )

    def testMiniBranchNoLatestVersion(self) -> None:
        """There is no matching latest mini branch."""
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-%s" % self.MINI_BRANCH_VERSION
            ),
            stdout="",
            stderr=self.CAT_ERROR,
            returncode=1,
        )
        # Set any other query to return a valid version, but we don't expect
        # that to occur for non canary versions.
        self.gs_mock.SetDefaultCmdResult(stdout=self.FULL_VERSION_MINI_BRANCH)
        self.assertEqual(
            None,
            self.finder.GetFullVersionFromLatestFile(self.MINI_BRANCH_VERSION),
        )
