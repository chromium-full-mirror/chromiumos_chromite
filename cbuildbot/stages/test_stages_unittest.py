# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for test stages."""

import os
from unittest import mock

from chromite.cbuildbot import cbuildbot_unittest
from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import generic_stages
from chromite.cbuildbot.stages import generic_stages_unittest
from chromite.cbuildbot.stages import test_stages
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib.buildstore import FakeBuildStore


pytestmark = cros_test_lib.pytestmark_inside_only


# pylint: disable=too-many-ancestors,protected-access


class UnitTestStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cbuildbot_unittest.SimpleBuilderTestCase,
):
    """Tests for the UnitTest stage."""

    BOT_ID = "amd64-generic-full"
    RELEASE_TAG = "ToT.0.0"

    def setUp(self):
        self.rununittests_mock = self.PatchObject(commands, "RunUnitTests")
        self.uploadartifact_mock = self.PatchObject(
            generic_stages.ArchivingStageMixin, "UploadArtifact"
        )
        self.image_dir = os.path.join(
            self.build_root, "src/build/images/amd64-generic/latest-cbuildbot"
        )

        self._Prepare()
        self.buildstore = FakeBuildStore()

    def ConstructStage(self):
        self._run.GetArchive().SetupArchivePath()
        return test_stages.UnitTestStage(
            self._run, self.buildstore, self._current_board
        )

    def testFullTests(self):
        """Tests full unit and cros_au_test_harness tests are run correctly."""
        makedirs_mock = self.PatchObject(osutils, "SafeMakedirs")

        board_runattrs = self._run.GetBoardRunAttrs(self._current_board)
        board_runattrs.SetParallel("test_artifacts_uploaded", True)
        board_runattrs.SetParallel("debug_symbols_completed", True)
        self.RunStage()
        makedirs_mock.assert_called_once_with(
            self._run.GetArchive().archive_path
        )
        self.rununittests_mock.assert_called_once_with(
            self.build_root,
            self._current_board,
            extra_env=mock.ANY,
            build_stage=True,
        )


class ImageTestStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cros_test_lib.RunCommandTestCase,
    cbuildbot_unittest.SimpleBuilderTestCase,
):
    """Test image test stage."""

    BOT_ID = "eve-release"
    RELEASE_TAG = "ToT.0.0"

    def setUp(self):
        self._test_root = os.path.join(self.build_root, "tmp/results_dir")
        self.PatchObject(
            commands,
            "CreateTestRoot",
            autospec=True,
            return_value="/tmp/results_dir",
        )
        self.PatchObject(
            path_util, "ToChrootPath", side_effect=lambda x, **kwargs: x
        )
        self._Prepare()
        self.buildstore = FakeBuildStore()

    # Our API here is not great when it comes to kwargs passing.
    def _Prepare(
        self, bot_id=None, **kwargs
    ):  # pylint: disable=arguments-differ
        super()._Prepare(bot_id, **kwargs)
        self._run.GetArchive().SetupArchivePath()

    def ConstructStage(self):
        return test_stages.ImageTestStage(
            self._run, self.buildstore, self._current_board
        )

    def testPerformStage(self):
        """Tests that we correctly run test-image script."""
        stage = self.ConstructStage()
        stage.PerformStage()
        cmd = [
            "sudo",
            "--",
            os.path.join(self.build_root, "chromite", "bin", "test_image"),
            "--board",
            self._current_board,
            "--test_results_root",
            path_util.ToChrootPath(
                os.path.join(self._test_root, "image_test_results")
            ),
            path_util.ToChrootPath(stage.GetImageDirSymlink()),
        ]
        self.assertCommandContains(cmd)
