# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the debugger library for the cros debug command."""

from unittest import mock

from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import debugger
from chromite.lib import remote_access


class MockCompletedProcess:
    """Mocked out CompletedProcess to avoid communicating with a real remote"""

    def __init__(self, run_output):
        self.stdout = run_output


class MockRemoteDevice(remote_access.ChromiumOSDevice):
    """Mocked remote device for returning arbitrary output from run commands"""

    def __init__(self, hostname, run_output, **kwargs):
        super().__init__(hostname, **kwargs)
        self.run_output = run_output

    def run(self, cmd, **kwargs):
        return MockCompletedProcess(self.run_output)


class MockIO:
    """Imitates an IO generator for testing reading of subprocess output"""

    def __init__(self, lines):
        self._lines = lines

    def readline(self):
        for line in self._lines:
            yield line


class MockPopen:
    """Mocked subprocess.Popen class for reading output"""

    def __init__(self, lines):
        self.stderr = MockIO(lines)

    def terminate(self):
        pass


class TestLLVMDebugger(cros_test_lib.MockTempDirTestCase):
    """Test shared and LLDB specific functionality and methods"""

    def create_simple_debugger(self):
        return debugger.LLVMDebugger(
            "lldb",
            remote_device=MockRemoteDevice("localhost", "this is a command"),
            port_forwards=[
                remote_access.PortForwardSpec(
                    local_port=3333,
                    remote_host=4444,
                ),
            ],
        )

    @mock.patch.object(
        remote_access.RemoteAccess,
        "CreateTunnel",
        autospec=True,
    )
    @mock.patch.object(
        debugger.LLVMDebugger,
        "_set_port_forwards",
        autospec=True,
        return_value=None,
    )
    def test_tunnel_remote_no_forward(
        self,
        _,
        mock_create_tunnel,
    ):
        """Ensure no call is made to CreateTunnel if no port map is provided."""

        dbg = debugger.LLVMDebugger("lldb")

        dbg.tunnel_to_remote()
        mock_create_tunnel.assert_not_called()

    def test_tunnel_remote_no_device(self):
        """Verify exception is raised if no device is present, but ports are."""
        dbg = debugger.LLVMDebugger(
            "lldb",
            remote_device=None,
            port_forwards=[
                remote_access.PortForwardSpec(local_port=1234, remote_port=5678)
            ],
        )

        with self.assertRaises(debugger.TunnelError):
            dbg.tunnel_to_remote()

    @mock.patch.object(
        remote_access.RemoteAccess,
        "CreateTunnel",
        autospec=True,
    )
    def test_tunnel_remote_with_ports(self, mock_create_tunnel):
        """Verify CreateTunnel is called properly with a device and ports."""
        dbg = debugger.LLVMDebugger(
            "lldb",
            remote_device=MockRemoteDevice(
                "localhost", run_output="no ports here"
            ),
            port_forwards=[
                remote_access.PortForwardSpec(local_port=1234, remote_port=5678)
            ],
        )
        dbg.tunnel_to_remote()
        mock_create_tunnel.assert_called()

    def test_sysroot_given(self):
        """Check that sysroot is specified in local command if provided"""
        dbg = debugger.LLVMDebugger(
            "lldb", sysroot="/path/to/sysroot", remote_device=None
        )

        self.assertIn(
            "platform select --sysroot /path/to/sysroot host",
            dbg.local_cmd,
        )

    def test_sysroot_empty(self):
        """Check that sysroot flag is not provided if sysroot=None"""
        dbg = debugger.LLVMDebugger("lldb", sysroot=None, remote_device=None)

        self.assertIn(
            "platform select host",
            dbg.local_cmd,
        )

    def test_platform_connect(self):
        """Verify platform connection command to remote device when present"""
        local_platform_port = 1111
        dbg = debugger.LLVMDebugger(
            "lldb",
            remote_device=MockRemoteDevice("localhost", "this is a command"),
            platform_port_local=local_platform_port,
            platform_port_remote=2222,
            gdbserver_port=3333,
        )

        self.assertIn(
            f"platform connect connect://localhost:{local_platform_port}",
            dbg.local_cmd,
        )

    @mock.patch.object(
        MockPopen,
        "terminate",
        autospec=True,
    )
    @mock.patch.object(
        debugger.LLVMDebugger,
        "tunnel_to_remote",
        autospec=True,
    )
    @mock.patch.object(
        debugger.Debugger,
        "_mockable_popen",
        return_value=MockPopen(
            [b"Sending command", b"another line", b"pledge: fork"]
        ),
    )
    def test_start_server(
        self,
        _,
        mock_tunnel,
        mock_terminate,
    ):
        """Verify start server can call tunnel and launch subprocess"""
        dbg = self.create_simple_debugger()

        with dbg.start_server():
            mock_tunnel.assert_called()
        mock_terminate.assert_called()

    @mock.patch.object(cros_build_lib, "run", autospec=True)
    def test_debug_new_local_binary(self, mock_run):
        """Verify new process target creation"""
        dbg = self.create_simple_debugger()

        exe = "test-exe"
        dbg.debug_new_process(exe, use_remote_binary=False)
        self.assertIn(f"target create {exe}", mock_run.call_args.args[0])

    @mock.patch.object(cros_build_lib, "run", autospec=True)
    def test_debug_new_remote_binary(self, mock_run):
        """Verify new process target creation with remote binary flag"""
        dbg = self.create_simple_debugger()

        exe = "test-exe"
        dbg.debug_new_process(exe, use_remote_binary=True)
        self.assertIn(f"target create -r {exe}", mock_run.call_args.args[0])

    @mock.patch.object(cros_build_lib, "run", autospec=True)
    def test_debug_existing(self, mock_run):
        """Verify command to attach to existing process"""
        dbg = self.create_simple_debugger()

        pid = 1234
        dbg.debug_existing_process(pid)
        self.assertIn(f"attach {pid}", mock_run.call_args.args[0])

    @mock.patch.object(
        cros_build_lib,
        "run",
        autospec=True,
    )
    def test_board_prompt_new(self, mock_run):
        """Verify board prompt is set if provided for new process"""
        dbg = self.create_simple_debugger()

        board = "brya"
        dbg.debug_new_process("/test/prog", board=board)
        self.assertIn(
            f'settings set prompt "(lldb-{board}) "',
            mock_run.call_args.args[0],
        )

    @mock.patch.object(
        cros_build_lib,
        "run",
        autospec=True,
    )
    def test_board_prompt_existing(self, mock_run):
        """Verify board prompt is set if provided for existing process"""
        dbg = self.create_simple_debugger()

        board = "brya"
        dbg.debug_existing_process(1234, board=board)
        self.assertIn(
            f'settings set prompt "(lldb-{board}) "',
            mock_run.call_args.args[0],
        )
