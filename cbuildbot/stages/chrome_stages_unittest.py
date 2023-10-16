# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for chrome stages."""

from chromite.cbuildbot import cbuildbot_run
from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import chrome_stages
from chromite.cbuildbot.stages import generic_stages_unittest
from chromite.lib import cros_test_lib
from chromite.lib.buildstore import FakeBuildStore


# pylint: disable=too-many-ancestors


class SyncChromeStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cros_test_lib.RunCommandTestCase,
):
    """Tests for SyncChromeStage."""

    # pylint: disable=protected-access
    def setUp(self):
        self._Prepare()
        self.PatchObject(
            cbuildbot_run._BuilderRunBase,
            "DetermineChromeVersion",
            return_value="35.0.1863.0",
        )
        self.PatchObject(commands, "SyncChrome")

    def ConstructStage(self):
        bs = FakeBuildStore()
        return chrome_stages.SyncChromeStage(self._run, bs)

    def testBasic(self):
        """Basic syntax sanity test."""
        stage = self.ConstructStage()
        stage.PerformStage()
