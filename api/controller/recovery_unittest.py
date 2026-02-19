# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recovery service tests."""

from unittest import mock

from chromite.api import api_config
from chromite.api.controller import recovery as recovery_controller
from chromite.api.gen.chromite.api import recovery_pb2
from chromite.lib import build_target_lib
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.service import kernel_image


class CreateRecoveryKernelTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create recovery kernel tests."""

    def setUp(self) -> None:
        self.response = recovery_pb2.CreateRecoveryKernelResponse()
        self.PatchObject(
            build_target_lib, "get_default_sysroot_path", return_value="/sys"
        )
        self.PatchObject(osutils, "SafeMakedirs")
        self.PatchObject(osutils, "Chown")

    def _GetRequest(self, board=None):
        """Helper to build a request instance."""
        return recovery_pb2.CreateRecoveryKernelRequest(
            build_target={"name": board},
            flags={
                "create_bootable_image": False,
                "ramfs_type": (
                    recovery_pb2.CreateRecoveryKernelRequest.DESKTOP_RECOVERY_RAMFS
                ),
            },
        )

    def testCreateRecoveryKernel(self) -> None:
        """Verify nothing breaks."""
        patch = self.PatchObject(kernel_image, "BuildKernel")

        request = self._GetRequest(board="board")
        recovery_controller.CreateRecoveryKernel(
            request, self.response, self.api_config
        )
        patch.assert_called_with(
            "board",
            "/sys/custom-packages",
            "/sys",
            False,
            mock.ANY,
            kernel_ramfs="desktop_recovery_ramfs",
            public_key=constants.RECOVERY_PUBLIC_KEY,
            private_key=constants.RECOVERY_DATA_PRIVATE_KEY,
            keyblock=constants.RECOVERY_KEYBLOCK,
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(kernel_image, "BuildKernel")

        request = self._GetRequest(board="board")
        recovery_controller.CreateRecoveryKernel(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()
