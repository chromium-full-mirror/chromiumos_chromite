# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the cros debug command."""

from chromite.cli import command_unittest
from chromite.cli.cros import cros_debug
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import remote_access


pytestmark = cros_test_lib.pytestmark_inside_only


class MockCompletedProcess:
    """Mocked out CompletedProcess to avoid communicating with a real remote"""

    def __init__(self, run_output):
        self.stdout = run_output


class MockDebugCommand(command_unittest.MockCommand):
    """Mock out the debug command."""

    TARGET = "chromite.cli.cros.cros_debug.DebugCommand"
    TARGET_CLASS = cros_debug.DebugCommand
    COMMAND = "debug"
    ATTRS = (
        "_ListProcesses",
        "_DebugNewProcess",
        "_DebugRunningProcess",
        "_RunLocal",
    )

    def _ListProcesses(self, _inst, *_args, **_kwargs) -> None:
        """Mock out _ListProcesses."""

    def _DebugNewProcess(self, _inst, *_args, **_kwargs) -> None:
        """Mock out _DebugNewProcess."""

    def _DebugRunningProcess(self, _inst, *_args, **_kwargs) -> None:
        """Mock out _DebugRunningProcess."""

    def _RunLocal(self, _inst, *_args, **_kwargs) -> None:
        """Mock out _RunLocal."""


class DebugRunThroughTest(cros_test_lib.MockTempDirTestCase):
    """Test the flow of DebugCommand.run with the debug methods mocked out."""

    DEVICE = remote_access.TEST_IP
    EXE = "/path/to/exe"
    PID = "1"

    def SetupCommandMock(self, cmd_args) -> None:
        """Set up command mock."""
        self.cmd_mock = MockDebugCommand(
            cmd_args, base_args=["--cache-dir", str(self.tempdir)]
        )
        self.StartPatcher(self.cmd_mock)

    def setUp(self) -> None:
        """Patches objects."""
        self.cmd_mock = None
        self.device_mock = self.PatchObject(
            remote_access, "ChromiumOSDevice"
        ).return_value
        self.device_mock.run.return_value = MockCompletedProcess("no ports")

    def testDebugNoSingleQuote(self) -> None:
        """Test that error is raised when --debug-arg contains single quote."""
        self.SetupCommandMock(
            [
                "--exe",
                self.EXE,
                "--debug-arg",
                "'has quotes'",
            ]
        )
        self.assertRaises(
            SystemExit,
            self.cmd_mock.inst.ProcessOptions,
            self.cmd_mock.parser,
            self.cmd_mock.inst.options,
        )

    def testMissingExeAndPid(self) -> None:
        """Test that command fails when --exe and --pid are not provided.

        Failure should occur in argument parsing on command setup.
        """
        with self.assertRaises(SystemExit):
            self.SetupCommandMock(["--device", self.DEVICE])

    def testListDisallowedWithPid(self) -> None:
        """Test that --list is disallowed when --pid is used."""
        self.SetupCommandMock(
            ["--device", self.DEVICE, "--list", "--pid", self.PID]
        )
        self.assertRaises(
            SystemExit,
            self.cmd_mock.inst.ProcessOptions,
            self.cmd_mock.parser,
            self.cmd_mock.inst.options,
        )

    def testExeDisallowedWithPid(self) -> None:
        """Test that --exe is disallowed when --pid is used.

        Failure should occur in argument parsing on command setup.
        """
        with self.assertRaises(SystemExit):
            self.SetupCommandMock(
                ["--device", self.DEVICE, "--exe", self.EXE, "--pid", self.PID]
            )

    def testExeMustBeFullPath(self) -> None:
        """Test that --exe only takes full path as a valid argument."""
        self.SetupCommandMock(["--device", self.DEVICE, "--exe", "bash"])
        self.assertRaises(
            SystemExit,
            self.cmd_mock.inst.ProcessOptions,
            self.cmd_mock.parser,
            self.cmd_mock.inst.options,
        )

    def testDebugProcessWithPid(self) -> None:
        """Test that methods are called correctly when pid is provided."""
        self.SetupCommandMock(["--device", self.DEVICE, "--pid", self.PID])
        self.cmd_mock.inst.Run()
        self.assertFalse(self.cmd_mock.patched["_ListProcesses"].called)
        self.assertFalse(self.cmd_mock.patched["_DebugNewProcess"].called)
        self.assertTrue(self.cmd_mock.patched["_DebugRunningProcess"].called)

    def testListProcesses(self) -> None:
        """Test that methods are called correctly for listing processes."""
        self.SetupCommandMock(
            ["--device", self.DEVICE, "--exe", self.EXE, "--list"]
        )
        self.cmd_mock.inst.Run()
        self.assertTrue(self.cmd_mock.patched["_ListProcesses"].called)
        self.assertFalse(self.cmd_mock.patched["_DebugNewProcess"].called)
        self.assertFalse(self.cmd_mock.patched["_DebugRunningProcess"].called)

    def testNoRunningProcess(self) -> None:
        """Test command starts a new process to debug if no process running."""
        self.SetupCommandMock(["--device", self.DEVICE, "--exe", self.EXE])
        self.PatchObject(self.device_mock, "GetRunningPids", return_value=[])
        self.cmd_mock.inst.Run()
        self.assertTrue(self.cmd_mock.patched["_ListProcesses"].called)
        self.assertTrue(self.cmd_mock.patched["_DebugNewProcess"].called)
        self.assertFalse(self.cmd_mock.patched["_DebugRunningProcess"].called)

    def testDebugNewProcess(self) -> None:
        """Test that user can select zero to start a new process to debug."""
        self.SetupCommandMock(["--device", self.DEVICE, "--exe", self.EXE])
        self.PatchObject(self.device_mock, "GetRunningPids", return_value=["1"])
        mock_prompt = self.PatchObject(
            cros_build_lib, "GetChoice", return_value=0
        )
        self.cmd_mock.inst.Run()
        self.assertTrue(mock_prompt.called)
        self.assertTrue(self.cmd_mock.patched["_ListProcesses"].called)
        self.assertTrue(self.cmd_mock.patched["_DebugNewProcess"].called)
        self.assertFalse(self.cmd_mock.patched["_DebugRunningProcess"].called)

    def testDebugRunningProcess(self) -> None:
        """Test that user can select none-zero to debug a running process."""
        self.SetupCommandMock(["--device", self.DEVICE, "--exe", self.EXE])
        self.PatchObject(self.device_mock, "GetRunningPids", return_value=["1"])
        mock_prompt = self.PatchObject(
            cros_build_lib, "GetChoice", return_value=1
        )
        self.cmd_mock.inst.Run()
        self.assertTrue(mock_prompt.called)
        self.assertTrue(self.cmd_mock.patched["_ListProcesses"].called)
        self.assertFalse(self.cmd_mock.patched["_DebugNewProcess"].called)
        self.assertTrue(self.cmd_mock.patched["_DebugRunningProcess"].called)

    def testDebugExtraArgs(self) -> None:
        """Test that the user can supply multiple extra command line args."""
        self.SetupCommandMock(["--exe", self.EXE, "--debug-arg", "arg1"])

        self.PatchObject(self.device_mock, "GetRunningPids", return_value=[])
        self.cmd_mock.inst.Run()
        self.assertTrue(self.cmd_mock.patched["_RunLocal"].called)
