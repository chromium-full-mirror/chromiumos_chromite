# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the kernel image service."""

import os
from pathlib import Path

import pytest

from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import kernel_builder
from chromite.service import kernel_image


@pytest.mark.usefixtures("testcase_caplog")
class BuildKernelImageTest(cros_test_lib.MockTempDirTestCase):
    """Test calling `BuildKernel` with various options."""

    # Test path expected by the command logic.
    BOARD = "the-board"
    WORK_DIR = "/work/dir"
    INSTALL_ROOT_PATH_STR = "/build/the-board"
    KERNEL_IMG_PATH = "/path/to/kernel.bin"

    def setUp(self) -> None:
        """Set up test environment and patches."""
        # Mock the main builder class using autospec.
        # Autospec ensures the mock has the same interface as the real class.
        builder_patcher = self.PatchObject(
            kernel_builder, "Builder", autospec=True
        )
        self.builder_mock = builder_patcher.return_value

        # Mock the chroot check.
        self.chroot_mock = self.PatchObject(
            cros_build_lib, "AssertInsideChroot"
        )

        # Default mock return values for methods known by autospec.
        # Convert string path to Path object for consistency.
        self.builder_mock.BuildCustomKernelImage.return_value = Path(
            self.KERNEL_IMG_PATH
        )
        # NOTE: generate_bootable_image is NOT mocked because autospec
        # likely determined it does not exist on the real Builder class.

    def testBasicBuildSuccess(self) -> None:
        """Tests a basic successful kernel build."""
        kernel_image.BuildKernel(
            board=self.BOARD,
            work_dir=self.WORK_DIR,
            install_root=self.INSTALL_ROOT_PATH_STR,
            bootable_image=False,
            jobs=16,
        )

        self.chroot_mock.assert_called_once()

        # Check Builder initialization.
        # Expect Path object for install_root.
        kernel_builder.Builder.assert_called_once_with(
            board=self.BOARD,
            work_dir=self.WORK_DIR,
            install_root=self.INSTALL_ROOT_PATH_STR,
            jobs=16,
        )

        # Check build call.
        self.builder_mock.BuildCustomKernelImage.assert_called_once()

        # Check log message.
        self.assertIn(
            f"Successfully generated kernel image: {self.KERNEL_IMG_PATH}",
            self.caplog.text,
        )

    def testOptionalKernelArgs(self) -> None:
        """Tests passing optional kernel arguments."""
        flag_value_2 = "disable_feature_y"
        keys_dir_path = self.tempdir / "keys"
        os.mkdir(keys_dir_path)
        args = {
            "kernel_ramfs": "recovery_ramfs",
            "kernel_version": "5.15.1",
            "kernel_flags": ["+myflag", flag_value_2],
            "keys_dir": keys_dir_path,
        }
        kernel_image.BuildKernel(
            board=self.BOARD,
            work_dir=self.WORK_DIR,
            install_root=self.INSTALL_ROOT_PATH_STR,
            bootable_image=False,
            **args,
        )

        # Defaults shouldn't be passed if not specified.
        # Expect Path object for keys_dir.
        # Expect updated flag list.
        self.builder_mock.BuildCustomKernelImage.assert_called_once_with(
            kernel_ramfs="recovery_ramfs",
            kernel_version="5.15.1",
            kernel_flags=["+myflag", flag_value_2],
            keys_dir=keys_dir_path,
        )

    def testCreateBootableImageFlagWarning(self) -> None:
        """Tests warning when --create-bootable-image used."""
        # This test verifies the warning logged when the flag is used,
        # but the underlying Builder (as mocked by autospec) lacks the
        # necessary method. setUp's autospec handles the mock setup.

        kernel_image.BuildKernel(
            board=self.BOARD,
            work_dir=self.WORK_DIR,
            install_root=self.INSTALL_ROOT_PATH_STR,
            bootable_image=True,
        )

        self.builder_mock.BuildCustomKernelImage.assert_called_once()

        # Verify the specific warning about the missing method is logged.
        self.assertIn(
            "The 'generate_bootable_image' method is not available on the "
            "Builder object. Bootable image generation skipped.",
            self.caplog.text,
        )
        # Verify the standard success message for kernel image is still logged.
        self.assertIn(
            f"Successfully generated kernel image: {self.KERNEL_IMG_PATH}",
            self.caplog.text,
        )
        # Verify NO message about successful *bootable* image generation.
        self.assertNotIn(
            "Placeholder generated bootable image:",
            self.caplog.text,
        )

    def testKernelBuildFailure(self) -> None:
        """Tests when BuildCustomKernelImage fails."""
        # Configure mock to raise a standard error.
        build_error = RuntimeError("Kernel compilation failed")
        self.builder_mock.BuildCustomKernelImage.side_effect = build_error

        # Expect Run() to raise the RuntimeError directly
        with self.assertRaises(RuntimeError) as context_manager:
            kernel_image.BuildKernel(
                board=self.BOARD,
                work_dir=self.WORK_DIR,
                install_root=self.INSTALL_ROOT_PATH_STR,
                bootable_image=False,
            )

        # Check that the raised exception is the one we set up
        self.assertEqual(context_manager.exception, build_error)

        self.builder_mock.BuildCustomKernelImage.assert_called_once()
        self.assertIn(
            "Starting kernel image generation for board:",
            self.caplog.text,
        )

        # Ensure the success message was NOT logged
        self.assertNotIn(
            "Successfully generated kernel image:",
            self.caplog.text,
        )
