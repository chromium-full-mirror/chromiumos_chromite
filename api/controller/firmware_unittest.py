# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for Firmware operations."""

import logging
import os
import tempfile
from unittest import mock

from chromite.api import api_config
from chromite.api.controller import firmware
from chromite.api.gen.chromite.api import firmware_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import constants
from chromite.lib import cros_test_lib


class BuildAllFirmwareTestCase(
    cros_test_lib.RunCommandTempDirTestCase, api_config.ApiConfigMixin
):
    """BuildAllFirmware tests."""

    def setUp(self) -> None:
        self.chroot_path = "/path/to/chroot"

    def _GetInput(
        self,
        chroot_path=None,
        fw_location=common_pb2.PLATFORM_EC,
        code_coverage=False,
    ):
        """Helper for creating input message."""
        proto = firmware_pb2.BuildAllFirmwareRequest(
            firmware_location=fw_location,
            chroot={"path": chroot_path},
            code_coverage=code_coverage,
        )
        return proto

    def testBuildAllFirmware(self) -> None:
        """Test endpoint by verifying call to cros_build_lib.run."""
        for fw_loc in common_pb2.FwLocation.values():
            fw_path = firmware.get_fw_loc(fw_loc)
            if not fw_path:
                continue
            request = self._GetInput(
                chroot_path=self.chroot_path,
                fw_location=fw_loc,
                code_coverage=True,
            )
            response = firmware_pb2.BuildAllFirmwareResponse()
            # Call the method under test.
            firmware.BuildAllFirmware(request, response, self.api_config)
            # Because we mock out the function, we verify that it is called as
            # we expect it to be called.
            called_function = os.path.join(
                constants.SOURCE_ROOT, fw_path, "firmware_builder.py"
            )
            self.rc.assertCommandCalled(
                [
                    called_function,
                    "--metrics",
                    mock.ANY,
                    "--code-coverage",
                    "build",
                ],
                check=False,
            )

    @mock.patch("tempfile.mkdtemp")
    def testBundleFirmwareArtifacts(self, mock_mkdtemp) -> None:
        """Test endpoint by verifying call to cros_build_lib.run."""
        outdir = None
        for fw_loc in common_pb2.FwLocation.values():
            fw_path = firmware.get_fw_loc(fw_loc)
            if not fw_path:
                continue
            outdir = os.path.join(tempfile.tempdir, str(fw_loc))
            os.mkdir(outdir)
            temp_dir_count = 0

            def temp_dirs(
                suffix=None,
                prefix=None,
                dir=None,  # pylint: disable=redefined-builtin
            ):
                nonlocal temp_dir_count, outdir
                logging.info(
                    "tempfile.mkdtemp called suffix=%s prefix=%s dir=%s",
                    suffix,
                    prefix,
                    dir,
                )
                ret = outdir
                if temp_dir_count > 0:
                    ret = f"{outdir}_{temp_dir_count}"
                temp_dir_count += 1
                os.makedirs(ret, exist_ok=True)
                return ret

            mock_mkdtemp.side_effect = temp_dirs
            if fw_loc == common_pb2.PLATFORM_ZEPHYR:
                # Create metadata file
                metadata_path = os.path.join(outdir, "firmware_metadata.jsonpb")
                with open(metadata_path, "w", encoding="utf-8") as mfile:
                    mfile.write(
                        """
{
        "objects": [
                { "fileName": "brox.EC.tar.bz2",
                  "tarballInfo": { "type": "EC", "board": ["brox"] } },
                { "fileName": "karis.EC.tar.bz2",
                  "tarballInfo": { "type": "EC", "board": ["rex"] } },
                { "fileName": "screebo.EC.tar.bz2",
                  "tarballInfo": { "type": "EC", "board": ["rex"] } },
                { "fileName": "brox/firmware_from_source.tar.bz2",
                  "tarballInfo": { "type": "EC", "board": ["brox"] } },
                { "fileName": "rex/firmware_from_source.tar.bz2",
                  "tarballInfo": { "type": "EC", "board": ["rex"] } }
        ]
}
                        """
                    )
                logging.info("Wrote metadata file: %s", metadata_path)
            request = firmware_pb2.BundleFirmwareArtifactsRequest(
                chroot={"path": self.chroot_path},
                artifacts={
                    "output_artifacts": [
                        {
                            "location": fw_loc,
                            "artifact_types": [
                                "FIRMWARE_TARBALL",
                                "FIRMWARE_TARBALL_INFO",
                                "FIRMWARE_TOKEN_DATABASE",
                            ],
                        }
                    ],
                },
            )
            response = firmware_pb2.BundleFirmwareArtifactsResponse()
            # Call the method under test.
            firmware.BundleFirmwareArtifacts(request, response, self.api_config)
            # Because we mock out the function, we verify that it is called as
            # we expect it to be called.
            called_function = os.path.join(
                constants.SOURCE_ROOT, fw_path, "firmware_builder.py"
            )
            self.rc.assertCommandCalled(
                [
                    called_function,
                    "--metrics",
                    mock.ANY,
                    "--output-dir",
                    mock.ANY,
                    "--metadata",
                    mock.ANY,
                    "bundle",
                ],
                check=False,
            )
            self.assertEqual(response.artifact_dir.path, outdir)
            self.assertEqual(
                response.artifact_dir.location, common_pb2.Path.INSIDE
            )

    def testValidateOnly(self) -> None:
        """Verify a validate-only call does not execute any logic."""
        for fw_loc in common_pb2.FwLocation.values():
            if not firmware.get_fw_loc(fw_loc):
                continue
            request = self._GetInput(
                chroot_path=self.chroot_path,
                fw_location=fw_loc,
                code_coverage=True,
            )
            response = firmware_pb2.BuildAllFirmwareResponse()
            firmware.BuildAllFirmware(
                request, response, self.validate_only_config
            )
            self.assertFalse(self.rc.called)

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        for fw_loc in common_pb2.FwLocation.values():
            if not firmware.get_fw_loc(fw_loc):
                continue
            request = self._GetInput(
                chroot_path=self.chroot_path,
                fw_location=fw_loc,
                code_coverage=True,
            )
            response = firmware_pb2.BuildAllFirmwareResponse()
            firmware.BuildAllFirmware(request, response, self.mock_call_config)
            self.assertFalse(self.rc.called)
            self.assertEqual(len(response.metrics.value), 1)
            self.assertEqual(response.metrics.value[0].target_name, "foo")
            self.assertEqual(response.metrics.value[0].platform_name, "bar")
            self.assertEqual(len(response.metrics.value[0].fw_section), 1)
            self.assertEqual(
                response.metrics.value[0].fw_section[0].region, "EC_RO"
            )
            self.assertEqual(response.metrics.value[0].fw_section[0].used, 100)
            self.assertEqual(response.metrics.value[0].fw_section[0].total, 150)
