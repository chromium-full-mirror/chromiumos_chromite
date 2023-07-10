# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the test stages."""

import os

from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import generic_stages
from chromite.lib import constants
from chromite.lib import osutils
from chromite.lib import timeout_util


class UnitTestStage(
    generic_stages.BoardSpecificBuilderStage, generic_stages.ArchivingStageMixin
):
    """Run unit tests."""

    option_name = "tests"
    config_name = "unittests"
    category = constants.PRODUCT_OS_STAGE

    # If the unit tests take longer than 90 minutes, abort. They usually take
    # thirty minutes to run, but they can take twice as long if the machine is
    # under load (e.g. in canary groups).
    #
    # If the processes hang, parallel_emerge will print a status report after 60
    # minutes, so we picked 120 minutes because it gives us a little buffer
    # time.
    #
    # Increased to 2 hours because of b/187793223.
    UNIT_TEST_TIMEOUT = 2 * 60 * 60

    def WaitUntilReady(self):
        """Block until UploadTestArtifacts completes.

        The attribute 'test_artifacts_uploaded' is set by UploadTestArtifacts.

        Returns:
            Boolean that authorizes running this stage.
        """
        self.board_runattrs.GetParallel("test_artifacts_uploaded", timeout=None)
        self.board_runattrs.GetParallel("debug_symbols_completed", timeout=None)
        return True

    def PerformStage(self):
        extra_env = {}
        if self._run.config.useflags:
            extra_env["USE"] = " ".join(self._run.config.useflags)
        r = " Reached UnitTestStage timeout."
        with timeout_util.Timeout(self.UNIT_TEST_TIMEOUT, reason_message=r):
            commands.RunUnitTests(
                self._build_root,
                self._current_board,
                extra_env=extra_env,
                build_stage=self._run.config.build_packages,
            )


class ImageTestStage(
    generic_stages.BoardSpecificBuilderStage, generic_stages.ArchivingStageMixin
):
    """Stage that launches tests on the produced disk image."""

    option_name = "image_test"
    config_name = "image_test"
    category = constants.CI_INFRA_STAGE

    # Give the tests 60 minutes to run. Image tests should be really quick but
    # the umount/rmdir bug (see osutils.UmountDir) may take a long time.
    IMAGE_TEST_TIMEOUT = 60 * 60

    def PerformStage(self):
        test_results_dir = commands.CreateTestRoot(self._build_root)
        # CreateTestRoot returns a temp directory inside chroot.
        # We bring that back out to the build root.
        test_results_dir = os.path.join(self._build_root, test_results_dir[1:])
        test_results_dir = os.path.join(test_results_dir, "image_test_results")
        osutils.SafeMakedirs(test_results_dir)
        with timeout_util.Timeout(self.IMAGE_TEST_TIMEOUT):
            commands.RunTestImage(
                self._build_root,
                self._current_board,
                self.GetImageDirSymlink(),
                test_results_dir,
            )
