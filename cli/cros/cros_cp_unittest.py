# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests the `cros cp` command."""

import pytest  # pylint: disable=import-error

from chromite.cli import command_unittest
from chromite.cli.cros import cros_cp
from chromite.lib import cros_test_lib
from chromite.lib import remote_access


class MockCpCommand(command_unittest.MockCommand):
    """Mock out the cp command."""

    TARGET = "chromite.cli.cros.cros_cp.CpCommand"
    TARGET_CLASS = cros_cp.CpCommand
    COMMAND = "cp"


@pytest.mark.usefixtures("testcase_caplog")
class CpTest(cros_test_lib.MockTempDirTestCase):
    """Test calling `cros cp` with various options."""

    DEVICE_IP = remote_access.TEST_IP

    def SetupCommandMock(self, cmd_args) -> None:
        """Setup command mock."""
        self.cmd_mock = MockCpCommand(
            cmd_args, base_args=["--cache-dir", str(self.tempdir)]
        )
        self.StartPatcher(self.cmd_mock)

    def setUp(self) -> None:
        """Patches objects."""
        self.cmd_mock = None
        self.mock_device = self.PatchObject(
            remote_access, "ChromiumOSDevice", autospec=True
        ).return_value
        self.mock_device.hostname = self.DEVICE_IP
        self.mock_device.port = self.DEVICE_IP

    def testScp(self) -> None:
        """Tests a command _StartCp to copy file from local to remote.

        Examples:
            cros cp /tmp_src 127.0.0.1:/tmp_dest
        """
        self.SetupCommandMock(["/tmp_src", "127.0.0.1:/tmp_dest"])
        self.cmd_mock.inst.Run()
        self.assertTrue(self.cmd_mock.inst.device.CopyToDevice.called)
        self.assertEqual(self.cmd_mock.inst.src[0].path, "/tmp_src")
        self.assertEqual(self.cmd_mock.inst.dest.path, "/tmp_dest")

    def testScpToLocal(self) -> None:
        """Tests a command _StartCp to copy file from remote to local.

        Examples:
            cros cp 127.0.0.1:/tmp_src /tmp_dest
        """
        self.SetupCommandMock(
            [
                "127.0.0.1:/tmp_src",
                "/tmp_dest",
            ]
        )
        self.cmd_mock.inst.Run()
        self.assertTrue(self.cmd_mock.inst.device.CopyFromDevice.called)
        self.assertEqual(self.cmd_mock.inst.src[0].path, "/tmp_src")
        self.assertEqual(self.cmd_mock.inst.dest.path, "/tmp_dest")

    def testRsync(self) -> None:
        """Tests a command _StartCp for Rsync.

        Examples:
            cros cp 127.0.0.1:/tmp_src /tmp_dest --mode=rsync --chmod="0664"
            --chown="owner:group"
        """
        self.SetupCommandMock(
            [
                "127.0.0.1:/tmp_src",
                "/tmp_dest",
                "--mode=rsync",
                "--chmod=0664",
                "--chown=owner:group",
            ]
        )
        self.cmd_mock.inst.Run()
        self.assertTrue(self.cmd_mock.inst.device.CopyFromDevice.called)
        self.assertEqual(self.cmd_mock.inst.src[0].path, "/tmp_src")
        self.assertEqual(self.cmd_mock.inst.dest.path, "/tmp_dest")
        self.assertEqual(self.cmd_mock.inst.options.mode, "rsync")
        self.assertEqual(self.cmd_mock.inst.options.chmod, "0664")
        self.assertEqual(self.cmd_mock.inst.options.chown, "owner:group")
