# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""debugger: Handle debug server and client connection for both GDB and LLDB."""

import abc
import contextlib
import logging
from pathlib import Path
import re
import subprocess
import time
from typing import List, Optional

from chromite.lib import cros_build_lib
from chromite.lib import remote_access
from chromite.utils import shell_util


class TunnelError(Exception):
    """No remote device was provided when attempting to establish SSH tunnel."""


class RemoteServerError(Exception):
    """No remote device was provided when attempting to start remote server."""


_RemoteDevice = remote_access.ChromiumOSDevice
MAX_PORT_NUM = 65535
_GDB_START_PORT = 2159
_PLATFORM_START_PORT = 2160


class Debugger(abc.ABC):
    """Represents a debugger and its actions on local or remote devices."""

    _PortMap = List[remote_access.PortForwardSpec]

    def __init__(
        self,
        debugger_path: Path,
        debugger_args: Optional[List[str]] = None,
        remote_device: Optional[_RemoteDevice] = None,
        ssh_settings: Optional[List[str]] = None,
        sysroot: Optional[str] = None,
        port_forwards: Optional[_PortMap] = None,
    ):
        self.debugger_path = debugger_path
        self.remote_device = remote_device
        logging.info("remote device is: %s", remote_device)
        self.ssh_settings = ssh_settings
        self.port_forwards = [] if port_forwards is None else port_forwards
        self.sysroot = sysroot
        self.debugger_args = [] if debugger_args is None else debugger_args

    def tunnel_to_remote(self) -> subprocess.Popen:
        """Establish SSH tunnel(s) to the remote device."""

        if not self.port_forwards:
            # Nothing to forward, so return early.
            logging.warning(
                "No port forwards were provided, no tunnel(s) established. "
                "Did you mean to provide a mapping?"
            )
            return

        if self.remote_device is None:
            raise TunnelError(
                "device is None; cannot establish SSH tunnel without a device"
            )
        return self.remote_device.agent.CreateTunnel(
            to_local=self.port_forwards, connect_settings=self.ssh_settings
        )

    @abc.abstractmethod
    def debug_existing_process(self, pid) -> None:
        raise NotImplementedError("Must override this abstract method.")

    @abc.abstractmethod
    def debug_new_process(self, exe) -> None:
        raise NotImplementedError("Must override this abstract method.")

    @abc.abstractmethod
    def start_server(self) -> None:
        raise NotImplementedError("Must override this abstract method.")

    @staticmethod
    def _mockable_popen(*args, **kwargs):
        """This wraps subprocess.Popen so it can be mocked in unit tests."""
        return subprocess.Popen(*args, **kwargs)


class LLVMDebugger(Debugger):
    """A Debugger representing LLDB."""

    def __init__(
        self,
        debugger_path: Path,
        platform_port_local: Optional[int] = None,
        platform_port_remote: Optional[int] = None,
        gdbserver_port: Optional[int] = None,
        **kwargs,
    ):
        super().__init__(debugger_path, **kwargs)

        # set default platform for local, overwritten for remote
        platform_string = "host"

        self.local_cmd = [
            str(self.debugger_path),
        ]

        # remote only setup
        if self.remote_device is not None:
            platform_string = "remote-linux"
            self.platform_port_local = platform_port_local
            self.platform_port_remote = platform_port_remote
            self.gdb_server_port = gdbserver_port
            self.platform_spec = None
            self.gdbserver_spec = None

            self.port_forwards = self._set_port_forwards(
                _GDB_START_PORT, _PLATFORM_START_PORT
            )

            self.server_cmd = self.remote_device.agent.GetSSHCommand() + [
                "-v",  # verbose SSH, required for detecting server launch
                "-n",  # redirect stdin to /dev/null (i.e., disable stdin)
                "--",
                "lldb-server",
                "platform",
                "--listen",
                f"*:{self.platform_port_remote}",
                "--gdbserver-port",
                f"{self.gdb_server_port}",
            ]
            logging.info("server_cmd is: %s", self.server_cmd)

        # set sysroot and debug symbols paths appropriately
        if self.sysroot is not None:
            if self.remote_device is None:
                self.local_cmd += ["-O", f"platform settings -w {self.sysroot}"]

            self.local_cmd += [
                "-O",
                f"platform select --sysroot {self.sysroot} {platform_string}",
                "-O",
                "settings append target.debug-file-search-paths "
                f"{self.sysroot}/usr/lib/debug",
            ]
        else:
            self.local_cmd += [f"platform select {platform_string}"]

        # Checks remote device again since connect must be the final argument
        if self.remote_device is not None:
            self.local_cmd.extend(
                [
                    "-O",
                    "platform connect "
                    f"connect://localhost:{self.platform_port_local}",
                ]
            )

    def _set_port_forwards(
        self, gdb_start: int, platform_start: int
    ) -> Debugger._PortMap:
        if self.platform_port_remote is None:
            self.platform_port_remote = self._get_unused_remote_port(
                platform_start
            )

        if self.gdb_server_port is None:
            self.gdb_server_port = self._get_unused_remote_port(gdb_start)

        if self.platform_port_local is None:
            self.platform_port_local = remote_access.GetUnusedPort()

        self.platform_spec = remote_access.PortForwardSpec(
            local_port=self.platform_port_local,
            remote_port=self.platform_port_remote,
        )
        self.gdbserver_spec = remote_access.PortForwardSpec(
            local_port=self.gdb_server_port,
            remote_port=self.gdb_server_port,
        )

        return [self.platform_spec, self.gdbserver_spec]

    def _get_unused_remote_port(self, start_port: int) -> Optional[int]:
        if self.remote_device is None:
            raise TunnelError(
                "Remote device is None, cannot obtain a remote port"
            )

        for port in range(start_port, MAX_PORT_NUM):
            output = self.remote_device.run(["netstat", "-natu"]).stdout
            if re.search(rf":{port}\b", output) is None:
                return port
            logging.warning("Port %d is in use, trying next port number", port)

        logging.error(
            "No available ports found equal or greater to %d.", start_port
        )
        return None

    def _lldb_board_prompt(self, board: Optional[str] = None) -> List[str]:
        return ["-O", f'settings set prompt "(lldb-{board}) "'] if board else []

    def debug_existing_process(
        self, pid: int, board: Optional[str] = None
    ) -> cros_build_lib.CompletedProcess:
        return cros_build_lib.run(
            self.local_cmd
            + self._lldb_board_prompt(board=board)
            + [
                "-O",
                f"attach {pid}",
            ]
            + self.debugger_args
        )

    def debug_new_process(
        self,
        exe: str,
        use_remote_binary: bool = False,
        board: Optional[str] = None,
    ) -> cros_build_lib.CompletedProcess:
        remote_bin_flag = "-r " if use_remote_binary else ""
        return cros_build_lib.run(
            self.local_cmd
            + self._lldb_board_prompt(board=board)
            + [
                "-O",
                f"target create {remote_bin_flag}{exe}",
            ]
            + self.debugger_args
        )

    @contextlib.contextmanager
    def start_server(self):
        if self.remote_device is None:
            raise RemoteServerError(
                "No remote device provided, cannot start remote server."
            )

        tunnel = self.tunnel_to_remote()

        logging.log(
            self.remote_device.agent.debug_level,
            "%s",
            shell_util.cmd_to_str(self.server_cmd),
        )

        server_proc = Debugger._mockable_popen(
            self.server_cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            # Wait for server to launch before yielding
            seen_sending = False
            seen_fork = False
            for line in iter(server_proc.stderr.readline, ""):
                if b"Sending command" in line:
                    seen_sending = True
                if b"pledge: fork" in line:
                    seen_fork = True
                if seen_sending and seen_fork:
                    # wait a little longer to let server fully launch
                    time.sleep(2)
                    break
            yield server_proc
        finally:
            server_proc.terminate()
            tunnel.terminate()
