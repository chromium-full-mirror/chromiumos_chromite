# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Signing service tests."""

from chromite.api import api_config
from chromite.api.controller import signing as signing_controller
from chromite.api.gen.chromite.api import signing_pb2
from chromite.lib import cros_test_lib


class CreatePreMPKeysTest(
    cros_test_lib.MockTestCase, api_config.ApiConfigMixin
):
    """Create image tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.CreatePreMPKeysResponse()

    def _GetRequest(
        self,
        board=None,
    ):
        """Helper to build a request instance."""
        return signing_pb2.CreatePreMPKeysRequest(
            build_target={"name": board},
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        request = self._GetRequest(board="board")
        signing_controller.CreatePreMPKeys(
            request, self.response, self.validate_only_config
        )
        # TODO(b/318522770): Verify that no logic called when we have logic.
