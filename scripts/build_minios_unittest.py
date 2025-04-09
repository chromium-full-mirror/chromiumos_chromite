# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for build_minios.py"""

import os
from pathlib import Path
import shutil
import tempfile
from unittest import mock

from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import minios
from chromite.lib import osutils
from chromite.scripts import build_minios


class BuildMiniosTest(cros_test_lib.RunCommandTempDirTestCase):
    """Unit tests for build_minios."""

    def setUp(self) -> None:
        self.create_minios_mock_return = "/some/kernel/path"
        self.create_minios_mock = self.PatchObject(
            minios,
            "CreateMiniOsKernelImage",
            return_value=self.create_minios_mock_return,
        )

        self.insert_minios_mock = self.PatchObject(
            minios, "InsertMiniOsKernelImage"
        )

        self.copy_mock = self.PatchObject(shutil, "copy")
        # Patch to assert against the tempdir that's created under the anchored.
        # tempdir created by cros_test_lib.
        self._tempdir = os.path.join(self.tempdir, "test-dir")
        self.PatchObject(tempfile, "mkdtemp", return_value=self._tempdir)
        # Create the temporary directory if it doesn't exist.
        os.makedirs(self._tempdir, exist_ok=True)

        # Define the path for the test file within the temporary directory.
        self._test_file_path = os.path.join(self._tempdir, "test_file.txt")

        # Create an empty file at the specified path.
        osutils.Touch(self._test_file_path)

    def testDefaultArguments(self) -> None:
        """Test that default arguments of build_minios are formatted correct."""
        test_board = "test-board"
        test_version = "0.0.0.0"
        test_image = self._test_file_path
        test_work_dir = self._tempdir
        self.PatchObject(
            os,
            "cpu_count",
            return_value=777,
        )
        build_minios.main(
            [
                # --board is a required argument.
                "--board",
                test_board,
                # --version is a required argument.
                "--version",
                test_version,
                # --image is a required argument.
                "--image",
                test_image,
            ]
        )

        self.assertEqual(
            self.create_minios_mock.mock_calls,
            [
                mock.call(
                    test_board,
                    test_version,
                    test_work_dir,
                    constants.VBOOT_DEVKEYS_DIR,
                    constants.RECOVERY_PUBLIC_KEY,
                    constants.MINIOS_DATA_PRIVATE_KEY,
                    constants.MINIOS_KEYBLOCK,
                    None,
                    777,
                    True,
                    False,
                )
            ],
        )

        self.assertEqual(
            self.insert_minios_mock.mock_calls,
            [
                mock.call(
                    Path(test_image),
                    self.create_minios_mock_return,
                )
            ],
        )

    def testOverridenArguments(self) -> None:
        """Test overridden arguments of build_minios are formatted correctly."""
        test_board = "test-board"
        test_version = "1.0.0.0"
        test_keys_dir = "/some/path/test-keys-dir"
        test_public_key = "test-public-key"
        test_private_key = "test-private-key"
        test_keyblock = "test-keyblock"
        test_serial = "test-serial"
        test_jobs = 777
        test_work_dir = self._tempdir
        test_image = self._test_file_path
        build_minios.main(
            [
                # --board is a required argument.
                "--board",
                test_board,
                # --version is a required argument.
                "--version",
                test_version,
                # --image is a required argument.
                "--image",
                test_image,
                "--keys-dir",
                test_keys_dir,
                "--public-key",
                test_public_key,
                "--private-key",
                test_private_key,
                "--keyblock",
                test_keyblock,
                "--serial",
                test_serial,
                "--force-build",
                "--jobs",
                str(test_jobs),
            ]
        )

        self.assertEqual(
            self.create_minios_mock.mock_calls,
            [
                mock.call(
                    test_board,
                    test_version,
                    test_work_dir,
                    test_keys_dir,
                    test_public_key,
                    test_private_key,
                    test_keyblock,
                    test_serial,
                    test_jobs,
                    True,
                    False,
                )
            ],
        )

        self.assertEqual(
            self.insert_minios_mock.mock_calls,
            [
                mock.call(
                    Path(test_image),
                    self.create_minios_mock_return,
                )
            ],
        )

    def testModForDev(self) -> None:
        """Test that default arguments of build_minios are formatted correct."""
        test_board = "test-board"
        test_version = "0.0.0.0"
        test_work_dir = self._tempdir
        test_image = self._test_file_path
        test_jobs = 777
        self.PatchObject(
            os,
            "cpu_count",
            return_value=str(test_jobs),
        )

        build_minios.main(
            [
                # --board is a required argument.
                "--board",
                test_board,
                # --version is a required argument.
                "--version",
                test_version,
                # --image is a required argument.
                "--image",
                test_image,
                "--mod-for-dev",
            ]
        )

        self.assertEqual(
            self.create_minios_mock.mock_calls,
            [
                mock.call(
                    test_board,
                    test_version,
                    test_work_dir,
                    constants.VBOOT_DEVKEYS_DIR,
                    constants.RECOVERY_PUBLIC_KEY,
                    constants.MINIOS_DATA_PRIVATE_KEY,
                    constants.MINIOS_KEYBLOCK,
                    None,
                    test_jobs,
                    False,
                    True,
                )
            ],
        )

        self.assertEqual(
            self.insert_minios_mock.mock_calls,
            [
                mock.call(
                    Path(test_image),
                    self.create_minios_mock_return,
                )
            ],
        )

    def testModForDevWithForceBuild(self) -> None:
        """Test that default arguments of build_minios are formatted correct."""
        test_board = "test-board"
        test_version = "0.0.0.0"
        test_work_dir = self._tempdir
        test_image = self._test_file_path
        test_jobs = 777
        build_minios.main(
            [
                # --board is a required argument.
                "--board",
                test_board,
                # --version is a required argument.
                "--version",
                test_version,
                # --image is a required argument.
                "--image",
                test_image,
                "--mod-for-dev",
                "--force-build",
                "--jobs",
                str(test_jobs),
            ]
        )

        self.assertEqual(
            self.create_minios_mock.mock_calls,
            [
                mock.call(
                    test_board,
                    test_version,
                    test_work_dir,
                    constants.VBOOT_DEVKEYS_DIR,
                    constants.RECOVERY_PUBLIC_KEY,
                    constants.MINIOS_DATA_PRIVATE_KEY,
                    constants.MINIOS_KEYBLOCK,
                    None,
                    test_jobs,
                    True,
                    True,
                )
            ],
        )

        self.assertEqual(
            self.insert_minios_mock.mock_calls,
            [
                mock.call(
                    Path(test_image),
                    self.create_minios_mock_return,
                )
            ],
        )

    def testKernelOnlyArguments(self) -> None:
        """Test that default arguments of build_minios are formatted correct."""
        test_board = "test-board"
        test_version = "0.0.0.0"
        test_work_dir = self._tempdir
        self.PatchObject(
            os,
            "cpu_count",
            return_value=777,
        )
        build_minios.main(
            [
                # --board is a required argument.
                "--board",
                test_board,
                # --version is a required argument.
                "--version",
                test_version,
                # --kernel-only to build standalone kernel.
                "--kernel-only",
                # --kernel-output is a required argument in case --kernel-only.
                "--kernel-output",
                test_work_dir,
            ]
        )

        self.assertEqual(
            self.create_minios_mock.mock_calls,
            [
                mock.call(
                    test_board,
                    test_version,
                    test_work_dir,
                    constants.VBOOT_DEVKEYS_DIR,
                    constants.RECOVERY_PUBLIC_KEY,
                    constants.MINIOS_DATA_PRIVATE_KEY,
                    constants.MINIOS_KEYBLOCK,
                    None,
                    777,
                    True,
                    False,
                )
            ],
        )

        self.assertEqual(
            self.copy_mock.mock_calls,
            [mock.call(self.create_minios_mock_return, Path(test_work_dir))],
        )
