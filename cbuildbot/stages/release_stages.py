# Copyright 2013 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the various stages that a builder runs."""

from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import artifact_stages
from chromite.lib import constants
from chromite.lib import timeout_util


class InvalidTestConditionException(Exception):
    """Raised when pre-conditions for a test aren't met."""


class SignerTestStage(artifact_stages.ArchivingStage):
    """Run signer related tests."""

    option_name = "tests"
    config_name = "signer_tests"
    category = constants.CI_INFRA_STAGE

    # If the signer tests take longer than 30 minutes, abort. They usually take
    # five minutes to run.
    SIGNER_TEST_TIMEOUT = 30 * 60

    def PerformStage(self):
        if not self.archive_stage.WaitForRecoveryImage():
            raise InvalidTestConditionException("Missing recovery image.")
        with timeout_util.Timeout(self.SIGNER_TEST_TIMEOUT):
            commands.RunSignerTests(self._build_root, self._current_board)
