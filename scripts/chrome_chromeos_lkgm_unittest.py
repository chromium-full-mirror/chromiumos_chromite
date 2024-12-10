# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the chrome_chromeos_lkgm program."""

import re
from unittest import mock

from chromite.lib import chromeos_version
from chromite.lib import cros_test_lib
from chromite.scripts import chrome_chromeos_lkgm


class StubGerritChange:
    """Stab class corresponding to cros_patch.GerritChange."""

    def __init__(
        self,
        gerrit_number,
        file_content,
        subject,
        mergeable=True,
        original_file_content=None,
        footers=None,
    ) -> None:
        self._gerrit_number = gerrit_number
        self._subject = subject
        self._file_content = file_content
        self._mergeable = mergeable
        self._original_file_content = original_file_content or file_content
        self._footers = footers

    @property
    def subject(self):
        return self._subject

    @property
    def gerrit_number(self):
        return self._gerrit_number

    @property
    def footers(self):
        return self._footers or []

    def GetFileContents(self, _path: str):
        return self._file_content

    def GetOriginalFileContents(self, _path: str):
        return self._original_file_content

    def IsMergeable(self):
        return self._mergeable

    def Rebase(self, allow_conflicts: bool = False) -> None:
        pass


# pylint: disable=protected-access
class ChromeLKGMCommitterTester(
    cros_test_lib.RunCommandTestCase, cros_test_lib.MockTempDirTestCase
):
    """Test cros_chromeos_lkgm.Committer."""

    def testCommitNewLKGM(self) -> None:
        """Tests that we can commit a new LKGM file."""
        committer = chrome_chromeos_lkgm.ChromeLKGMCommitter(
            "1001.0.0",
            "main",
            chromeos_version.VersionInfo("999.0.0"),
            dryrun=False,
        )

        with mock.patch.object(committer._gerrit_helper, "CreateChange") as cg:
            cg.return_value = mock.MagicMock(gerrit_number=123456)
            with mock.patch.object(
                committer._gerrit_helper, "ChangeEdit"
            ) as ce:
                with mock.patch.object(
                    committer._gerrit_helper, "SetReview"
                ) as bc:
                    with mock.patch.object(
                        committer._gerrit_helper, "SetHashtags"
                    ):
                        committer.UpdateLKGM()
                        ce.assert_called_once_with(
                            123456, "chromeos/CHROMEOS_LKGM", "1001.0.0"
                        )
                        bc.assert_called_once_with(
                            123456,
                            labels={"Bot-Commit": 1, "Commit-Queue": 2},
                            notify="NONE",
                            ready=True,
                            reviewers=[
                                "chrome-os-gardeners-reviews@google.com"
                            ],
                        )

    def testDryRun(self) -> None:
        committer = chrome_chromeos_lkgm.ChromeLKGMCommitter(
            "1001.0.0",
            "main",
            chromeos_version.VersionInfo("999.0.0"),
            dryrun=True,
        )

        with mock.patch.object(committer._gerrit_helper, "CreateChange") as cg:
            change = StubGerritChange(123456, "10001.0.0", "10001.0.0")
            cg.return_value = change
            with mock.patch.object(
                committer._gerrit_helper, "ChangeEdit"
            ) as ce:
                with mock.patch.object(
                    committer._gerrit_helper, "SetReview"
                ) as bc:
                    with mock.patch.object(
                        committer._gerrit_helper, "SetHashtags"
                    ) as sht:
                        with mock.patch.object(
                            committer._gerrit_helper, "AbandonChange"
                        ) as ac:
                            committer.UpdateLKGM()
                            ce.assert_called_once_with(
                                123456, "chromeos/CHROMEOS_LKGM", "1001.0.0"
                            )
                            ac.assert_called_once_with((change), msg=mock.ANY)
                            bc.assert_not_called()
                            sht.assert_not_called()

    def testOlderLKGMFails(self) -> None:
        """Tests that trying to update to an older lkgm version fails."""
        committer = chrome_chromeos_lkgm.ChromeLKGMCommitter(
            "1001.0.0",
            "main",
            chromeos_version.VersionInfo("1002.0.0"),
            dryrun=False,
        )
        with mock.patch.object(committer._gerrit_helper, "CreateChange") as cg:
            cg.return_value = mock.MagicMock(gerrit_number=123456)
            with mock.patch.object(
                committer._gerrit_helper, "ChangeEdit"
            ) as ce:
                self.assertRaises(
                    chrome_chromeos_lkgm.LKGMNotValid, committer.UpdateLKGM
                )
                ce.assert_not_called()

    def testAbandonObsoleteLKGMs(self) -> None:
        """Tests that trying to abandon the obsolete lkgm CLs."""
        cleaner = chrome_chromeos_lkgm.ChromeLKGMCleaner(
            "main", chromeos_version.VersionInfo("10002.0.0"), "USER_EMAIL"
        )

        older_change = StubGerritChange(
            3876550, "10001.0.0", "10001.0.0", mergeable=False
        )
        newer_change = StubGerritChange(3876551, "10003.0.0", "10003.0.0")
        open_issues = [older_change, newer_change]

        with mock.patch.object(
            cleaner._gerrit_helper, "Query", return_value=open_issues
        ) as mock_query:
            with mock.patch.object(
                cleaner._gerrit_helper, "AbandonChange"
            ) as ac:
                cleaner.ProcessObsoleteLKGMRolls()
                mock_query.assert_called_once()
                ac.assert_called_once_with((older_change), msg=mock.ANY)

    def testRebaseObsoleteLKGMs(self) -> None:
        """Tests that trying to abandon the obsolete lkgm CLs."""
        cleaner = chrome_chromeos_lkgm.ChromeLKGMCleaner(
            "main", chromeos_version.VersionInfo("10002.0.0"), "USER_EMAIL"
        )

        # LKGM Roll CL from "10001.0.0" to "10003.0.0" should be in the
        # merge-conflict state, since the current LKGM version is "10002.0.0".
        ROLL_FROM = "10001.0.0"
        ROLL_TO = "10003.0.0"
        GERRIT_NUM = 3876551
        roll = StubGerritChange(
            GERRIT_NUM,
            ROLL_TO,
            ROLL_TO,
            mergeable=False,
            original_file_content=ROLL_FROM,
        )

        with mock.patch.object(
            cleaner._gerrit_helper, "Query", return_value=[roll]
        ) as mock_query:
            with mock.patch.object(roll, "Rebase") as rebase:
                with mock.patch.object(
                    cleaner._gerrit_helper, "ChangeEdit"
                ) as ce:
                    cleaner.ProcessObsoleteLKGMRolls()
                    mock_query.assert_called_once()

                    # Confirm that it does rebasing.
                    rebase.assert_called_once_with(allow_conflicts=True)
                    ce.assert_called_once_with(GERRIT_NUM, mock.ANY, ROLL_TO)

    def testDoNothingObsoleteLKGMs(self) -> None:
        """Tests that trying to abandon the obsolete lkgm CLs."""
        cleaner = chrome_chromeos_lkgm.ChromeLKGMCleaner(
            "main", chromeos_version.VersionInfo("10002.0.0"), "USER_EMAIL"
        )

        # LKGM Roll CL from "10002.0.0" to "10003.0.0" should NOT be in the
        # merge-conflict state, since the current LKGM version is "10002.0.0".
        ROLL_FROM = "10002.0.0"
        ROLL_TO = "10003.0.0"
        GERRIT_NUM = 3876551
        # Even if mergeable=False, the logic should not do nothing.
        roll = StubGerritChange(
            GERRIT_NUM,
            ROLL_TO,
            ROLL_TO,
            mergeable=False,
            original_file_content=ROLL_FROM,
        )

        with mock.patch.object(
            cleaner._gerrit_helper, "Query", return_value=[roll]
        ) as mock_query:
            with mock.patch.object(roll, "Rebase") as rebase:
                with mock.patch.object(
                    cleaner._gerrit_helper, "ChangeEdit"
                ) as ce:
                    cleaner.ProcessObsoleteLKGMRolls()
                    mock_query.assert_called_once()

                    # Confirm that it does nothing.
                    rebase.assert_not_called()
                    ce.assert_not_called()

    def testVersionWithChromeBranch(self) -> None:
        """Tests passing a version with a chrome branch strips the branch."""
        branch = "refs/branch-heads/5000"
        committer = chrome_chromeos_lkgm.ChromeLKGMCommitter(
            "1003.0.0-rc2",
            branch,
            chromeos_version.VersionInfo("1002.0.0"),
            dryrun=False,
        )

        with mock.patch.object(committer._gerrit_helper, "CreateChange") as cg:
            cg.return_value = mock.MagicMock(gerrit_number=123456)
            with mock.patch.object(
                committer._gerrit_helper, "ChangeEdit"
            ) as ce:
                with mock.patch.object(
                    committer._gerrit_helper, "SetReview"
                ) as bc:
                    with mock.patch.object(
                        committer._gerrit_helper, "SetHashtags"
                    ):
                        # Check the file was actually written out correctly.
                        committer.UpdateLKGM()
                        cg.assert_called_once_with(
                            "chromium/src", branch, mock.ANY, False
                        )
                        ce.assert_called_once_with(
                            123456, "chromeos/CHROMEOS_LKGM", "1003.0.0"
                        )
                        bc.assert_called_once_with(
                            123456,
                            labels={"Bot-Commit": 1, "Commit-Queue": 2},
                            notify="NONE",
                            ready=True,
                            reviewers=[
                                "chrome-os-gardeners-reviews@google.com"
                            ],
                        )

    def testVersionWithSnapshotNumber(self) -> None:
        """Tests passing a version with a CrOS snapshot number."""
        branch = "refs/branch-heads/5000"
        committer = chrome_chromeos_lkgm.ChromeLKGMCommitter(
            "1003.0.0-2222222",
            branch,
            chromeos_version.VersionInfo("1002.0.0-1111111"),
            False,
        )

        with mock.patch.object(committer._gerrit_helper, "CreateChange") as cg:
            cg.return_value = mock.MagicMock(gerrit_number=123456)
            with mock.patch.object(
                committer._gerrit_helper, "ChangeEdit"
            ) as ce:
                with mock.patch.object(
                    committer._gerrit_helper, "SetReview"
                ) as bc:
                    with mock.patch.object(
                        committer._gerrit_helper, "SetHashtags"
                    ):
                        # Check the file was actually written out correctly.
                        committer.UpdateLKGM()
                        cg.assert_called_once_with(
                            "chromium/src", branch, mock.ANY, False
                        )
                        ce.assert_called_once_with(
                            123456, "chromeos/CHROMEOS_LKGM", "1003.0.0-2222222"
                        )
                        bc.assert_called_once_with(
                            123456,
                            labels={"Bot-Commit": 1, "Commit-Queue": 2},
                            notify="NONE",
                            ready=True,
                            reviewers=[
                                "chrome-os-gardeners-reviews@google.com"
                            ],
                        )

    def testCommitMsg(self) -> None:
        """Tests format of the commit message."""
        committer = chrome_chromeos_lkgm.ChromeLKGMCommitter(
            "1001.0.0",
            "main",
            chromeos_version.VersionInfo("999.0.0"),
            dryrun=False,
            buildbucket_id="some-build-id",
            message="this is a message.",
            internal_manifest_position=111111,
            external_manifest_position=22222,
        )

        committer._PRESUBMIT_BOTS = {
            "internal": (
                "bot1",
                "bot2",
            )
        }

        # The current CL is with the external position but without the internal
        # one, so that a next CL would have only the external manifest diff.
        previous_lkgm_uprev_cls = [
            StubGerritChange(
                3333,
                "subj",
                "content",
                footers=[
                    (
                        chrome_chromeos_lkgm.GIT_FOOTER_EXTERNAL_MANIFEST_POS,
                        "22221",
                    ),
                ],
            )
        ]
        with mock.patch.object(
            committer._gerrit_helper,
            "Query",
            return_value=previous_lkgm_uprev_cls,
        ) as mock_query:
            commit_msg_lines = committer.ComposeCommitMsg().splitlines()
            mock_query.assert_called_once()

        self.assertIn(
            "Automated Commit: LKGM 1001.0.0 for chromeos.", commit_msg_lines
        )

        self.assertIn("CrOS Changes (999.0.0 -> 1001.0.0):", commit_msg_lines)

        # Ensure the link to external manifest diff exists.
        self.assertIn(
            "- External: http://go/cros-changes/22221..22222?ext=true",
            commit_msg_lines,
        )

        # Ensure the link to internal manifest diff doesn't exist.
        internal_regexp = re.compile("^- Internal: .*$")
        for line in commit_msg_lines:
            self.assertNotRegex(line, internal_regexp)

        self.assertIn(
            "Uploaded by https://ci.chromium.org/b/some-build-id",
            commit_msg_lines,
        )
        self.assertIn("CQ_INCLUDE_TRYBOTS=internal:bot1", commit_msg_lines)
        self.assertIn("CQ_INCLUDE_TRYBOTS=internal:bot2", commit_msg_lines)
        self.assertIn("this is a message.", commit_msg_lines)
        self.assertIn(
            "CrOS-External-Manifest-Position: 22222", commit_msg_lines
        )
        self.assertIn(
            "CrOS-Internal-Manifest-Position: 111111", commit_msg_lines
        )
