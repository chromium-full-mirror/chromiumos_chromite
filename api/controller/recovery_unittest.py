# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recovery service tests."""

from chromite.api import api_config
from chromite.api.controller import controller_util
from chromite.api.controller import recovery as recovery_controller
from chromite.api.gen.chromite.api import recovery_pb2
from chromite.lib import cros_test_lib


class CreateRecoveryKernelTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create recovery kernel tests."""

    def setUp(self) -> None:
        self.response = recovery_pb2.CreateRecoveryKernelResponse()

    def _GetRequest(self, board=None):
        """Helper to build a request instance."""
        return recovery_pb2.CreateRecoveryKernelRequest(
            build_target={"name": board},
        )

    def testCreateRecoveryKernel(self) -> None:
        """Verify nothing breaks."""
        request = self._GetRequest(board="board")
        recovery_controller.CreateRecoveryKernel(
            request, self.response, self.api_config
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(controller_util, "ParseChroot")

        request = self._GetRequest(board="board")
        recovery_controller.CreateRecoveryKernel(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()
