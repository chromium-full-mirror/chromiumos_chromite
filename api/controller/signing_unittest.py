# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Signing service tests."""

import os

from chromite.api import api_config
from chromite.api.controller import signing as signing_controller
from chromite.api.gen.chromite.api import signing_pb2
from chromite.lib import cros_test_lib
from chromite.service import image as image_service


class CreatePreMPKeysTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create image tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.CreatePreMPKeysResponse()
        self.docker_image = "us-docker.pkg.dev/chromeos-bot/signing/signing:123"

        os.environ["LUCI_CONTEXT"] = "/tmp/foo/bar/luci_context.1234"
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_IP"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_ROOT"] = "127.0.0.1:12345"

    def _GetRequest(
        self,
        board=None,
        dry_run=False,
    ):
        """Helper to build a request instance."""
        return signing_pb2.CreatePreMPKeysRequest(
            docker_image="signing:latest",
            release_keys_checkout=str(self.tempdir),
            build_target={"name": board},
            dry_run=dry_run,
        )

    def testDockerCalledWith(self) -> None:
        """Verify that docker is called with the correct arguments."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(board="board")
        signing_controller.CreatePreMPKeys(
            request, self.response, self.api_config
        )

        rc.assertCommandContains(
            ["docker", "inspect", "--type=image", "signing:latest"]
        )
        rc.assertCommandContains(
            [
                "docker",
                "run",
                "--privileged",
                "--network",
                "host",
                "-v",
                "/tmp/foo/bar/luci_context.1234:/tmp/luci/luci_context.1234",
                "-e",
                "LUCI_CONTEXT=/tmp/luci/luci_context.1234",
                "-e",
                "GCE_METADATA_HOST=127.0.0.1:12345",
                "-e",
                "GCE_METADATA_IP=127.0.0.1:12345",
                "-e",
                "GCE_METADATA_ROOT=127.0.0.1:12345",
                "-v",
                f"{self.tempdir}:/keys",
                "--entrypoint",
                "./create_premp.sh",
                "signing:latest",
                "board",
            ]
        )

    def testDryRun(self) -> None:
        """Verify that dryrun mode passes --dev to the entrypoint."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            board="board",
            dry_run=True,
        )
        signing_controller.CreatePreMPKeys(
            request, self.response, self.api_config
        )

        rc.assertCommandContains(
            ["docker", "inspect", "--type=image", "signing:latest"]
        )
        rc.assertCommandContains(
            [
                "docker",
                "run",
                "--privileged",
                "--network",
                "host",
                "-v",
                "/tmp/foo/bar/luci_context.1234:/tmp/luci/luci_context.1234",
                "-e",
                "LUCI_CONTEXT=/tmp/luci/luci_context.1234",
                "-e",
                "GCE_METADATA_HOST=127.0.0.1:12345",
                "-e",
                "GCE_METADATA_IP=127.0.0.1:12345",
                "-e",
                "GCE_METADATA_ROOT=127.0.0.1:12345",
                "-v",
                f"{self.tempdir}:/keys",
                "--entrypoint",
                "./create_premp.sh",
                "signing:latest",
                "--dev",
                "board",
            ]
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(image_service, "CallDocker")

        request = self._GetRequest(board="board")
        signing_controller.CreatePreMPKeys(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()
