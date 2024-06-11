# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for cros_sdk.py."""

import logging

from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import testing_utils
from chromite.lib import cros_test_lib


class CrosSdkTestCase(testing_utils.TestCase):
    """Test cases for cros_sdk.CrosSdk."""

    def test_generate_compile_commands(self) -> None:
        """Test case for cros_sdk.CrosSdk.generate_compile_commands()."""
        pkg = self.new_package()
        pkg_chroot_build_dir = self.setup.chroot.chroot_path(pkg.build_dir)
        # Patch run() directly instead of inheriting RunCommandTestCase so that
        # we can set up the mock package correctly.
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()
        self.cros_sdk.generate_compile_commands(pkg_chroot_build_dir)
        rc.assertCommandCalled(
            ["ninja", "-C", pkg_chroot_build_dir, "-t", "compdb", "cc", "cxx"],
            enter_chroot=True,
            chroot_args=self.setup.chroot.get_enter_args(),
            extra_env={},
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    def _test_generate_dependency_tree(self, with_tests: bool) -> None:
        """Configurable test for CrosSdk.generate_dependency_tree()."""
        self.setup.with_tests = with_tests

        # Patch run() directly instead of inheriting RunCommandTestCase so that
        # we can still set up the mock packages.
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.SetDefaultCmdResult()

        # We pass the main script's logging level into the called script.
        # Mock the logging level to ensure a consistent test.
        my_logger = logging.Logger("my_logger", level=logging.INFO)
        with self.PatchObject(logging, "getLogger", return_value=my_logger):
            self.cros_sdk.generate_dependency_tree(
                ["chromeos-base/pkg1", "chromeos-base/pkg2"]
            )

        expected_command = [
            "sudo",
            "--",
            self.setup.chroot.chroot_path(constants.PRINT_DEPS_SCRIPT_PATH),
            self.build_target,
            "chromeos-base/pkg1",
            "chromeos-base/pkg2",
            "--log-level=info",
        ]
        if with_tests:
            expected_command.insert(1, "FEATURES=test")
        rc.assertCommandContains(
            expected_command,
            enter_chroot=True,
            chroot_args=self.setup.chroot.get_enter_args(),
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    def test_generate_dependency_tree(self) -> None:
        """Test generate_dependency_tree() without the --with-tests feature."""
        self._test_generate_dependency_tree(False)

    def test_generate_dependency_tree_with_tests(self) -> None:
        """Test generate_dependency_tree() with the --with-tests feature."""
        self._test_generate_dependency_tree(True)
