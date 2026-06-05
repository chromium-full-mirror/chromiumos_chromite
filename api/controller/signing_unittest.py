# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Signing service tests."""

import os
from typing import Optional

from chromite.api import api_config
from chromite.api.controller import signing as signing_controller
from chromite.api.gen.chromite.api import signing_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.service import image as image_service


class CreatePreMPKeysTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create image tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.CreatePreMPKeysResponse()
        self.docker_image = (
            "us-docker.pkg.dev/chromeos-release-bot/signing/signing:123"
        )

        os.environ["LUCI_CONTEXT"] = "/tmp/foo/bar/luci_context.1234"
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_IP"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_ROOT"] = "127.0.0.1:12345"

    def _GetRequest(
        self,
        board=None,
        dry_run=False,
        add_loem=False,
    ):
        """Helper to build a request instance."""
        return signing_pb2.CreatePreMPKeysRequest(
            docker_image="signing:latest",
            release_keys_checkout=str(self.tempdir),
            build_target={"name": board},
            dry_run=dry_run,
            add_loem=add_loem,
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

    def testAddLoem(self) -> None:
        """Verify that add_loem mode changes the entrypoint."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            board="board",
            add_loem=True,
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
                "./add_loem.py",
                "signing:latest",
                "board",
            ]
        )


class CreateAccessoryKeysTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create image tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.CreateAccessoryKeyResponse()
        self.docker_image = (
            "us-docker.pkg.dev/chromeos-release-bot/signing/signing:123"
        )

        os.environ["LUCI_CONTEXT"] = "/tmp/foo/bar/luci_context.1234"
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_IP"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_ROOT"] = "127.0.0.1:12345"

    def _GetRequest(
        self,
        board=None,
        accessory=None,
        version=None,
        dry_run=False,
        is_pre_mp=False,
        is_staging=False,
    ):
        """Helper to build a request instance."""
        build_target = None
        if board:
            build_target = {"name": board}
        return signing_pb2.CreateAccessoryKeyRequest(
            docker_image="signing:latest",
            release_keys_checkout=str(self.tempdir),
            build_target=build_target,
            accessory=accessory,
            version=version,
            dry_run=dry_run,
            is_pre_mp=is_pre_mp,
            is_staging=is_staging,
        )

    def testDockerCalledForPreMpKey(self) -> None:
        """Verify docker is called with correct arguments for PreMP key."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            board="board", accessory="accessory", is_pre_mp=True
        )
        signing_controller.CreateAccessoryKeys(
            request, self.response, self.api_config
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
                "./generate_accessory_keys.py",
                "signing:latest",
                "-a",
                "accessory",
                "-b",
                "board",
                "--pre-mp",
            ]
        )

    def testDockerCalledForPreMpKeyWithoutBuildTarget(self) -> None:
        """Verify docker is called with correct arguments for PreMP key."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(accessory="accessory", is_pre_mp=True)
        signing_controller.CreateAccessoryKeys(
            request, self.response, self.api_config
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
                "./generate_accessory_keys.py",
                "signing:latest",
                "-a",
                "accessory",
                "--pre-mp",
            ]
        )

    def testDockerCalledForMpKeyWithoutVersion(self) -> None:
        """Verify docker is called with correct arguments for MP key."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(board="board", accessory="accessory")
        signing_controller.CreateAccessoryKeys(
            request, self.response, self.api_config
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
                "./generate_accessory_keys.py",
                "signing:latest",
                "-a",
                "accessory",
                "-b",
                "board",
            ]
        )

    def testDockerCalledForMpKeyWithVersion(self) -> None:
        """Verify correct arguments for MP key with a version."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            board="board", accessory="accessory", version=3
        )
        signing_controller.CreateAccessoryKeys(
            request, self.response, self.api_config
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
                "./generate_accessory_keys.py",
                "signing:latest",
                "-a",
                "accessory",
                "-b",
                "board",
                "-kv",
                "3",
            ]
        )

    def testDryRun(self) -> None:
        """Verify that dryrun mode passes --dev to the entrypoint."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            board="board",
            accessory="accessory",
            dry_run=True,
        )
        signing_controller.CreateAccessoryKeys(
            request, self.response, self.api_config
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
                "./generate_accessory_keys.py",
                "signing:latest",
                "-a",
                "accessory",
                "-b",
                "board",
                "--dry-run",
            ]
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(image_service, "CallDocker")

        request = self._GetRequest(board="board", accessory="accessory")
        signing_controller.CreateAccessoryKeys(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()


class SignTi50PaosTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Sign ti50 paos tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.SignTi50PaosResponse()
        self.docker_image = (
            "us-docker.pkg.dev/chromeos-release-bot/signing/signing:123"
        )

        os.environ["LUCI_CONTEXT"] = "/tmp/foo/bar/luci_context.1234"
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_IP"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_ROOT"] = "127.0.0.1:12345"

    def _GetRequest(
        self,
        project,
        location,
        keyring,
        key,
        version,
        filename,
        result_dir,
    ):
        """Helper to build a request instance."""
        return signing_pb2.SignTi50PaosRequest(
            project=project,
            location=location,
            keyring=keyring,
            key=key,
            version=version,
            filename=filename,
            docker_image="signing:latest",
            archive_dir="/tmp/temp-dir-archives/",
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=str(result_dir),
                    location=common_pb2.Path.Location.OUTSIDE,
                )
            ),
            tmp_path="/docker-tmp/signing_tmp",
        )

    def testDockerCalledWith(self) -> None:
        """Verify that docker is called with the correct arguments."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        result_dir = os.path.join(self.tempdir, "out")
        os.mkdir(result_dir)

        request = self._GetRequest(
            "project",
            "location",
            "keyring",
            "key",
            1,
            "filename",
            result_dir,
        )
        signing_controller.SignTi50Paos(request, self.response, self.api_config)

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
                "/tmp/temp-dir-archives/:/in",
                "-v",
                f"{result_dir}:/out",
                "-v",
                "/docker-tmp/signing_tmp:/tmp",
                "--entrypoint",
                "./ti50_pao_generate.sh",
                "project",
                "location",
                "keyring",
                "key",
                "1",
                "/in/filename",
                "/out/filename",
            ]
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(image_service, "CallDocker")

        request = self._GetRequest(
            "project",
            "location",
            "keyring",
            "key",
            1,
            "filename",
            self.tempdir,
        )
        signing_controller.SignTi50Paos(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()


class CreateCertTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create cert tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.CreateCertResponse()
        self.docker_image = (
            "us-docker.pkg.dev/chromeos-release-bot/signing/signing:123"
        )

        os.environ["LUCI_CONTEXT"] = "/tmp/foo/bar/luci_context.1234"
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_IP"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_ROOT"] = "127.0.0.1:12345"

    def _GetRequest(
        self,
        keyring: Optional[str] = None,
        key_name: Optional[str] = None,
        out_path: Optional[str] = None,
        result_dir: Optional[str] = None,
        dry_run: bool = False,
        is_staging: bool = False,
    ) -> signing_pb2.CreateCertRequest:
        """Helper to build a request instance."""
        return signing_pb2.CreateCertRequest(
            docker_image="signing:latest",
            release_keys_checkout=str(self.tempdir),
            keyring=keyring,
            key_name=key_name,
            out_path=out_path,
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=str(result_dir),
                    location=common_pb2.Path.Location.OUTSIDE,
                )
            ),
            dry_run=dry_run,
            is_staging=is_staging,
        )

    def testCertCreated(self) -> None:
        """Verify docker is called with correct arguments."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        result_dir = os.path.join(self.tempdir, "out")
        os.mkdir(result_dir)

        request = self._GetRequest(
            keyring="keyring",
            key_name="key_name",
            out_path="/out",
            result_dir=result_dir,
        )
        signing_controller.CreateCert(request, self.response, self.api_config)

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
                "-v",
                f"{result_dir}:/out",
                "--entrypoint",
                "./create_cert.py",
                "signing:latest",
                "--keyring",
                "keyring",
                "--key-name",
                "key_name",
                "--out-location",
                "/out",
            ]
        )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(image_service, "CallDocker")

        request = self._GetRequest(
            keyring="keyring",
            key_name="key_name",
            out_path="/out",
        )
        signing_controller.CreateCert(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()


class CreateKeysHsmTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Create key with online HSM tests."""

    def setUp(self) -> None:
        self.response = signing_pb2.CreateKeysHsmResponse()
        self.docker_image = (
            "us-docker.pkg.dev/chromeos-release-bot/signing/signing:123"
        )

        os.environ["LUCI_CONTEXT"] = "/tmp/foo/bar/luci_context.1234"
        os.environ["GCE_METADATA_HOST"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_IP"] = "127.0.0.1:12345"
        os.environ["GCE_METADATA_ROOT"] = "127.0.0.1:12345"

    def _GetRequest(
        self,
        keyset_name: str = "foo",
        dry_run: bool = False,
        exporter_dry_run: Optional[bool] = None,
    ):
        """Helper to build a request instance."""
        req = signing_pb2.CreateKeysHsmRequest(
            docker_image="signing:latest",
            keyset_name=keyset_name,
            dry_run=dry_run,
            release_keys_checkout=str(self.tempdir),
        )

        if exporter_dry_run is not None:
            req.exporter_dry_run = exporter_dry_run
        return req

    def testSuccess(self) -> None:
        """CreateKeysHsm succeeds and returns a populated response."""
        self.PatchObject(
            osutils.TempDir, "__enter__", return_value=self.tempdir
        )
        expected_response = signing_pb2.CreateKeysHsmResponse(
            request_status=signing_pb2.STATUS_PASS
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "out_proto.bin"),
            expected_response.SerializeToString(),
            mode="wb",
        )

        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(keyset_name="setkey")
        res = signing_controller.CreateKeysHsm(
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
                "--entrypoint",
                "./create_keys_with_hsm.py",
                "signing:latest",
                "--keyset-name",
                "setkey",
                "--keyset-repo",
                "/keys",
                "-o",
                "/out",
                "-p",
                "out_proto.bin",
            ]
        )
        self.assertEqual(self.response, expected_response)
        self.assertIsNone(res)

    def testDryRun(self) -> None:
        """Verify that dryrun mode passes --mocks and --exporter-dry-run."""
        self.PatchObject(
            osutils.TempDir, "__enter__", return_value=self.tempdir
        )
        expected_response = signing_pb2.CreateKeysHsmResponse(
            request_status=signing_pb2.STATUS_PASS
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "out_proto.bin"),
            expected_response.SerializeToString(),
            mode="wb",
        )

        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            keyset_name="setkey",
            dry_run=True,
        )
        res = signing_controller.CreateKeysHsm(
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
                "--entrypoint",
                "./create_keys_with_hsm.py",
                "signing:latest",
                "--keyset-name",
                "setkey",
                "--keyset-repo",
                "/keys",
                "-o",
                "/out",
                "-p",
                "out_proto.bin",
                "--mocks",
                "--exporter-dry-run",
            ]
        )
        self.assertEqual(self.response, expected_response)
        self.assertIsNone(res)

    def testExporterDryRunTrue(self) -> None:
        """Verify that exporter_dry_run=True passes --exporter-dry-run."""
        self.PatchObject(
            osutils.TempDir, "__enter__", return_value=self.tempdir
        )
        expected_response = signing_pb2.CreateKeysHsmResponse(
            request_status=signing_pb2.STATUS_PASS
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "out_proto.bin"),
            expected_response.SerializeToString(),
            mode="wb",
        )

        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            keyset_name="setkey",
            exporter_dry_run=True,
        )
        res = signing_controller.CreateKeysHsm(
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
                "--entrypoint",
                "./create_keys_with_hsm.py",
                "signing:latest",
                "--keyset-name",
                "setkey",
                "--keyset-repo",
                "/keys",
                "-o",
                "/out",
                "-p",
                "out_proto.bin",
                "--exporter-dry-run",
            ]
        )
        self.assertEqual(self.response, expected_response)
        self.assertIsNone(res)

    def testExporterDryRunFalse(self) -> None:
        """Verify that exporter_dry_run=False passes neither flag."""
        self.PatchObject(
            osutils.TempDir, "__enter__", return_value=self.tempdir
        )
        expected_response = signing_pb2.CreateKeysHsmResponse(
            request_status=signing_pb2.STATUS_PASS
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "out_proto.bin"),
            expected_response.SerializeToString(),
            mode="wb",
        )

        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            keyset_name="setkey",
            exporter_dry_run=False,
        )
        res = signing_controller.CreateKeysHsm(
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
                "--entrypoint",
                "./create_keys_with_hsm.py",
                "signing:latest",
                "--keyset-name",
                "setkey",
                "--keyset-repo",
                "/keys",
                "-o",
                "/out",
                "-p",
                "out_proto.bin",
            ]
        )
        self.assertEqual(self.response, expected_response)
        self.assertIsNone(res)

    def testMocksWithoutExporterDryRun(self) -> None:
        """Verify dry_run=True & exporter_dry_run=False passes only --mocks."""
        self.PatchObject(
            osutils.TempDir, "__enter__", return_value=self.tempdir
        )
        expected_response = signing_pb2.CreateKeysHsmResponse(
            request_status=signing_pb2.STATUS_PASS
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "out_proto.bin"),
            expected_response.SerializeToString(),
            mode="wb",
        )

        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(
            keyset_name="setkey",
            dry_run=True,
            exporter_dry_run=False,
        )
        res = signing_controller.CreateKeysHsm(
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
                "--entrypoint",
                "./create_keys_with_hsm.py",
                "signing:latest",
                "--keyset-name",
                "setkey",
                "--keyset-repo",
                "/keys",
                "-o",
                "/out",
                "-p",
                "out_proto.bin",
                "--mocks",
            ]
        )
        self.assertEqual(self.response, expected_response)
        self.assertIsNone(res)

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        patch = self.PatchObject(image_service, "CallDockerWithResponse")

        request = self._GetRequest(keyset_name="setkey")
        signing_controller.CreateKeysHsm(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMissingResponse(self) -> None:
        """Verify CreateKeysHsm raises ValueError when response is missing."""
        self.PatchObject(
            osutils.TempDir, "__enter__", return_value=self.tempdir
        )
        # We don't write any out_proto.bin to self.tempdir.

        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        request = self._GetRequest(keyset_name="setkey")
        with self.assertRaises(ValueError):
            signing_controller.CreateKeysHsm(
                request, self.response, self.api_config
            )
