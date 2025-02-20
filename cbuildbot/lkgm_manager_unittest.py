# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for lkgm_manager"""

from chromite.cbuildbot import lkgm_manager
from chromite.lib import cros_test_lib


FAKE_VERSION_STRING = "1.2.4-rc3"
FAKE_VERSION_STRING_NEXT = "1.2.4-rc4"
CHROME_BRANCH = "13"


# pylint: disable=protected-access


class LKGMCandidateInfoTest(cros_test_lib.TestCase):
    """Test methods testing methods in _LKGMCandidateInfo class."""

    def testLoadFromString(self) -> None:
        """Tests whether we can load from a string."""
        info = lkgm_manager._LKGMCandidateInfo(
            version_string=FAKE_VERSION_STRING, chrome_branch=CHROME_BRANCH
        )
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING)

    def testIncrementVersionPatch(self) -> None:
        """Tests whether we can increment a lkgm info."""
        info = lkgm_manager._LKGMCandidateInfo(
            version_string=FAKE_VERSION_STRING, chrome_branch=CHROME_BRANCH
        )
        info.IncrementVersion()
        self.assertEqual(info.VersionString(), FAKE_VERSION_STRING_NEXT)

    def testVersionCompare(self) -> None:
        """Tests whether our comparision method works."""
        info0 = lkgm_manager._LKGMCandidateInfo("5.2.3-rc100")
        info1 = lkgm_manager._LKGMCandidateInfo("1.2.3-rc1")
        info2 = lkgm_manager._LKGMCandidateInfo("1.2.3-rc2")
        info3 = lkgm_manager._LKGMCandidateInfo("1.2.200-rc1")
        info4 = lkgm_manager._LKGMCandidateInfo("1.4.3-rc1")

        self.assertGreater(info0, info1)
        self.assertGreater(info0, info2)
        self.assertGreater(info0, info3)
        self.assertGreater(info0, info4)
        self.assertGreater(info2, info1)
        self.assertGreater(info3, info1)
        self.assertGreater(info3, info2)
        self.assertGreater(info4, info1)
        self.assertGreater(info4, info2)
        self.assertGreater(info4, info3)
        self.assertEqual(info0, info0)
        self.assertEqual(info1, info1)
        self.assertEqual(info2, info2)
        self.assertEqual(info3, info3)
        self.assertEqual(info4, info4)
        self.assertNotEqual(info0, info1)
        self.assertNotEqual(info0, info2)
        self.assertNotEqual(info0, info3)
        self.assertNotEqual(info0, info4)
        self.assertNotEqual(info1, info0)
        self.assertNotEqual(info1, info2)
        self.assertNotEqual(info1, info3)
        self.assertNotEqual(info1, info4)
        self.assertNotEqual(info2, info0)
        self.assertNotEqual(info2, info1)
        self.assertNotEqual(info2, info3)
        self.assertNotEqual(info2, info4)
        self.assertNotEqual(info3, info0)
        self.assertNotEqual(info3, info1)
        self.assertNotEqual(info3, info2)
        self.assertNotEqual(info3, info4)
        self.assertNotEqual(info4, info0)
        self.assertNotEqual(info4, info1)
        self.assertNotEqual(info4, info1)
        self.assertNotEqual(info4, info3)
