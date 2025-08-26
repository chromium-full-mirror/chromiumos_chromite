# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the `cros build-kernel` command."""

import os
from pathlib import Path

from chromite.cli import command_unittest
from chromite.cli.cros import cros_build_kernel
from chromite.lib import cros_test_lib
from chromite.service import kernel_image


class MockBuildKernelCommand(command_unittest.MockCommand):
    """Mock out the build-kernel command."""

    TARGET = "chromite.cli.cros.cros_build_kernel.BuildKernelCommand"
    TARGET_CLASS = cros_build_kernel.BuildKernelCommand
    COMMAND = "build-kernel"


class BuildKernelTest(cros_test_lib.MockTempDirTestCase):
    """Test calling `cros build-kernel` with various options."""

    # Test path expected by the command logic.
    INSTALL_ROOT_PATH_STR = "/build/the-board"
    KERNEL_IMG_PATH = "/path/to/kernel.bin"

    def SetupCommandMock(self, cmd_args) -> MockBuildKernelCommand:
        """Setup command mock."""
        # Prepend required args if not already present.
        full_args = []
        if "--board" not in cmd_args:
            full_args.extend(["--board", "test-board"])
        if "--working-dir" not in cmd_args:
            full_args.extend(["--working-dir", str(self.tempdir / "work")])
        if "--install-root" not in cmd_args:
            full_args.extend(["--install-root", self.INSTALL_ROOT_PATH_STR])

        full_args.extend(cmd_args)
        # Filter out None values which can happen if flags aren't always added.
        full_args = [arg for arg in full_args if arg is not None]
        cmd_mock = MockBuildKernelCommand(full_args)
        self.StartPatcher(cmd_mock)
        cmd_mock.inst.options.jobs = 4
        return cmd_mock

    def setUp(self) -> None:
        """Set up test environment and patches."""
        self.cmd_mock = None
        # Mock the main builder class using autospec.
        # Autospec ensures the mock has the same interface as the real class.
        self.builder_mock = self.PatchObject(
            kernel_image, "BuildKernel", autospec=True
        )

        # Mock the chroot check.
        self.chroot_mock = self.PatchObject(
            cros_build_kernel.commandline, "RunInsideChroot"
        )

        # Default mock return values for methods known by autospec.
        # Convert string path to Path object for consistency.
        self.builder_mock.return_value = Path(self.KERNEL_IMG_PATH)
        # NOTE: generate_bootable_image is NOT mocked because autospec
        # likely determined it does not exist on the real Builder class.

    def testBasicBuildSuccess(self) -> None:
        """Tests a basic successful kernel build."""
        self.cmd_mock = self.SetupCommandMock([])
        rc = self.cmd_mock.inst.Run()

        self.assertEqual(rc, 0)
        self.chroot_mock.assert_called_once()

        # Check Builder initialization.
        # Expect Path object for install_root.
        self.builder_mock.assert_called_once_with(
            board="test-board",
            work_dir=Path(self.tempdir / "work"),
            install_root=Path(self.INSTALL_ROOT_PATH_STR),
            bootable_image=False,
            jobs=4,
            kernel_ramfs="recovery_ramfs",
            kernel_version="0.0.1",
            extra_pkgs=[],
        )

    def testOptionalKernelArgs(self) -> None:
        """Tests passing optional kernel arguments."""
        # Use a non-hyphenated flag value to avoid argparse confusion in tests.
        flag_value_2 = "disable_feature_y"
        keys_dir_path = self.tempdir / "keys"
        os.mkdir(keys_dir_path)
        args = [
            "--kernel-version",
            "5.15.1",
            "--kernel-flags",
            "+myflag",
            # This was changed from "-otherflag" for test simplicity.
            flag_value_2,
            "--keys-dir",
            str(keys_dir_path),
            "--extra-pkgs",
            "pkga pkgb",
        ]
        self.cmd_mock = self.SetupCommandMock(args)
        rc = self.cmd_mock.inst.Run()

        self.assertEqual(rc, 0)

        # Defaults shouldn't be passed if not specified.
        # Expect Path object for keys_dir.
        # Expect updated flag list.
        self.builder_mock.assert_called_once_with(
            board="test-board",
            work_dir=Path(self.tempdir / "work"),
            install_root=Path(self.INSTALL_ROOT_PATH_STR),
            bootable_image=False,
            jobs=4,
            kernel_ramfs="recovery_ramfs",
            kernel_version="5.15.1",
            kernel_flags=["+myflag", flag_value_2],
            keys_dir=keys_dir_path,
            extra_pkgs=["pkga", "pkgb"],
        )

    def testKernelBuildFailure(self) -> None:
        """Tests when BuildCustomKernelImage fails."""
        # Configure mock to raise a standard error.
        build_error = RuntimeError("Kernel compilation failed")
        self.builder_mock.side_effect = build_error

        self.cmd_mock = self.SetupCommandMock([])

        # Expect Run() to raise the RuntimeError directly
        with self.assertRaises(RuntimeError) as context_manager:
            self.cmd_mock.inst.Run()

        # Check that the raised exception is the one we set up
        self.assertEqual(context_manager.exception, build_error)

        self.builder_mock.assert_called_once()

    def testWorkDirCreation(self) -> None:
        """Tests that the work directory is created if it doesn't exist."""
        work_dir = self.tempdir / "new_work_dir"
        self.assertFalse(work_dir.exists())

        self.PatchObject(
            cros_build_kernel.osutils,
            "SafeMakedirs",
            side_effect=lambda path, sudo=False: os.makedirs(
                path, exist_ok=True
            ),
        )

        self.cmd_mock = self.SetupCommandMock(["--working-dir", str(work_dir)])
        rc = self.cmd_mock.inst.Run()

        self.assertEqual(rc, 0)
        self.assertTrue(work_dir.exists())
        self.assertTrue(work_dir.is_dir())

        # Check Builder was called with the correct Path objects.
        self.builder_mock.assert_called_once_with(
            board="test-board",
            # Expect Path object for work_dir.
            work_dir=work_dir,
            # Expect Path object for install_root.
            install_root=Path(self.INSTALL_ROOT_PATH_STR),
            bootable_image=False,
            jobs=4,
            kernel_ramfs="recovery_ramfs",
            kernel_version="0.0.1",
            extra_pkgs=[],
        )
