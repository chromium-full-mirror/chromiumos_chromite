# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Paygen provision payload tests."""

from unittest import mock

from chromite.lib import chroot_lib
from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import parallel_unittest
from chromite.lib import partial_mock
from chromite.lib.paygen import partition_lib
from chromite.lib.paygen import paygen_provision_payload


class GenerateProvisionPayloadsTest(cros_test_lib.MockTempDirTestCase):
    """Test cases for the provision payloads generation."""

    def setUp(self) -> None:
        self.StartPatcher(parallel_unittest.ParallelMock())

        self.target_image = (
            self.tempdir
            / "link"
            / "R37-5952.0.2014_06_12_2302-a1"
            / "chromiumos_test_image.bin"
        )
        osutils.Touch(self.target_image, makedirs=True)
        self.sample_dlc_image = (
            self.tempdir
            / "link"
            / "R37-5952.0.2014_06_12_2302-a1"
            / "dlc"
            / "sample-dlc"
            / "package"
            / "dlc.img"
        )
        osutils.Touch(self.sample_dlc_image, makedirs=True)

        self.chroot = chroot_lib.Chroot(
            self.tempdir / "chroot", out_path=self.tempdir / "out"
        )

    def testGenerateProvisionPayloads(self) -> None:
        """Verifies correct files are created for provisioning."""
        extract_kernel_mock = self.PatchObject(partition_lib, "ExtractKernel")
        extract_root_mock = self.PatchObject(partition_lib, "ExtractRoot")
        has_minios_mock = self.PatchObject(
            partition_lib, "HasMiniOSPartitions", return_value=False
        )
        compress_file_mock = self.PatchObject(compression_lib, "compress_file")

        paygen_provision_payload.GenerateProvisionPayloads(
            self.target_image, self.tempdir
        )

        extract_kernel_mock.assert_called_once_with(
            self.target_image, partial_mock.HasString("kernel.bin")
        )
        extract_root_mock.assert_called_once_with(
            self.target_image,
            partial_mock.HasString("rootfs.bin"),
            truncate=False,
        )
        has_minios_mock.assert_called_once()

        calls = [
            mock.call(
                partial_mock.HasString("kernel.bin"),
                partial_mock.HasString(
                    constants.QUICK_PROVISION_PAYLOAD_KERNEL
                ),
                compression_level=None,
            ),
            mock.call(
                partial_mock.HasString("rootfs.bin"),
                partial_mock.HasString(
                    constants.QUICK_PROVISION_PAYLOAD_ROOTFS
                ),
                compression_level=None,
            ),
            mock.call(
                partial_mock.HasString("kernel.bin"),
                partial_mock.HasString(constants.FULL_PAYLOAD_KERN),
                compression_level=19,
            ),
            mock.call(
                partial_mock.HasString("rootfs.bin"),
                partial_mock.HasString(constants.FULL_PAYLOAD_ROOT),
                compression_level=19,
            ),
        ]
        compress_file_mock.assert_has_calls(calls)

    def testGenerateProvisionPayloadsWithMiniOS(self) -> None:
        """Verifies correct files are created for provisioning."""
        extract_kernel_mock = self.PatchObject(partition_lib, "ExtractKernel")
        extract_root_mock = self.PatchObject(partition_lib, "ExtractRoot")
        extract_minios_mock = self.PatchObject(partition_lib, "ExtractMiniOS")
        has_minios_mock = self.PatchObject(
            partition_lib, "HasMiniOSPartitions", return_value=True
        )
        compress_file_mock = self.PatchObject(compression_lib, "compress_file")

        paygen_provision_payload.GenerateProvisionPayloads(
            self.target_image, self.tempdir
        )

        extract_kernel_mock.assert_called_once_with(
            self.target_image, partial_mock.HasString("kernel.bin")
        )
        extract_root_mock.assert_called_once_with(
            self.target_image,
            partial_mock.HasString("rootfs.bin"),
            truncate=False,
        )
        extract_minios_mock.assert_called_once_with(
            self.target_image, partial_mock.HasString("minios.bin")
        )
        has_minios_mock.assert_called_once()

        calls = [
            mock.call(
                partial_mock.HasString("kernel.bin"),
                partial_mock.HasString(
                    constants.QUICK_PROVISION_PAYLOAD_KERNEL
                ),
                compression_level=None,
            ),
            mock.call(
                partial_mock.HasString("rootfs.bin"),
                partial_mock.HasString(
                    constants.QUICK_PROVISION_PAYLOAD_ROOTFS
                ),
                compression_level=None,
            ),
            mock.call(
                partial_mock.HasString("minios.bin"),
                partial_mock.HasString(
                    constants.QUICK_PROVISION_PAYLOAD_MINIOS
                ),
                compression_level=None,
            ),
            mock.call(
                partial_mock.HasString("kernel.bin"),
                partial_mock.HasString(constants.FULL_PAYLOAD_KERN),
                compression_level=19,
            ),
            mock.call(
                partial_mock.HasString("rootfs.bin"),
                partial_mock.HasString(constants.FULL_PAYLOAD_ROOT),
                compression_level=19,
            ),
            mock.call(
                partial_mock.HasString("minios.bin"),
                partial_mock.HasString(constants.FULL_PAYLOAD_MINIOS),
                compression_level=19,
            ),
        ]
        compress_file_mock.assert_has_calls(calls)
