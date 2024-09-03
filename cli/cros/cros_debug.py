# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros debug: Debug the applications on the target device."""

import logging
import os
import pathlib
import shlex
import shutil
import sys
from typing import List, Optional

from chromite.cli import command
from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import debugger
from chromite.lib import namespaces
from chromite.lib import osutils
from chromite.lib import qemu
from chromite.lib import remote_access
from chromite.utils import shell_util


_DEBUGGER_LLDB = "lldb"
_DEBUGGER_GDB = "gdb"
_BIND_MOUNT_PATHS = (
    pathlib.Path("dev"),
    pathlib.Path("dev/pts"),
    pathlib.Path("proc"),
    pathlib.Path("mnt/host/source"),
    pathlib.Path("sys"),
)


class RunningPidsError(Exception):
    """Raised when not able to get pids on the local machine."""


@command.command_decorator("debug")
class DebugCommand(command.CliCommand):
    """Use LLDB to debug a process running on the target device.

    This command starts an LLDB session to debug a process running locally or on
    a remote device. The remote process can either be an existing process or
    newly started by calling this command. Local processes must be started using
    this command.

    This command can also be used to find out information about all running
    processes of an executable on the target device.
    """

    EPILOG = """
To list all running processes of an executable:
    cros debug --device device --list --exe=/path/to/executable

To debug an executable:
    cros debug --device device --exe=/path/to/executable

To debug a process by its pid:
    cros debug --device device --pid=1234
"""

    def __init__(self, options: commandline.ArgumentNamespace) -> None:
        """Initialize DebugCommand."""
        super().__init__(options)
        # SSH connection settings.
        self.device: Optional[remote_access.RemoteDevice] = None
        self.ssh_hostname: Optional[str] = None
        self.ssh_port: Optional[int] = None
        self.ssh_username: Optional[str] = None
        self.ssh_private_key: Optional[str] = None
        # The board name of the target device.
        self.board: Optional[str] = None
        # Settings of the process to debug.
        self.list: bool = False
        self.exe: Optional[pathlib.Path] = None
        self.pid: Optional[int] = None

        self.debugger_name: Optional[str] = None
        self.debugger_path: Optional[pathlib.Path] = None
        self.use_remote_exe: bool = False
        self.sysroot: Optional[pathlib.Path] = None
        self.debug_server: Optional[debugger.Debugger] = None
        self.qemu: Optional[qemu.Qemu] = None
        self.debugger_args: Optional[List[str]] = None
        self.corefile: Optional[pathlib.Path] = None

    @classmethod
    def AddParser(cls, parser: commandline.ArgumentParser) -> None:
        """Add parser arguments."""
        super(cls, DebugCommand).AddParser(parser)
        cls.AddDeviceArgument(parser, positional=False)
        parser.add_argument(
            "--board",
            help="The board to use. By default it is "
            "automatically detected. You can override the detected board with "
            "this option.",
        )
        parser.add_argument(
            "--private-key",
            type="str_path",
            help="SSH identity file (private key).",
        )
        parser.add_argument(
            "-l",
            "--list",
            action="store_true",
            help="List running processes of the executable on the target "
            "device.",
        )

        parser.add_argument(
            "--use-remote-exe",
            action="store_true",
            help="Interpret the path given with --exe as a remote only path, "
            "and use the '-r' flag for lldb. Only works with --debugger=lldb "
            "and remote debugging.",
        )

        parser.add_argument(
            "--sysroot",
            help="Path to the sysroot to pass to the debugger. In local "
            "debugging, both the debugger and the target binary are run under "
            "this sysroot. By default this is autodetected using the provided "
            "board.",
        )

        # Enforce that either --exe or --pid is provided, but not both.
        debug_target = parser.add_mutually_exclusive_group(required=True)
        debug_target.add_argument(
            "--exe",
            type=pathlib.Path,
            help="Full path of the executable on the target device.",
        )
        debug_target.add_argument(
            "-p",
            "--pid",
            type=int,
            help="The pid of the process on the target device.",
        )

        parser.add_argument(
            "--debugger",
            default=_DEBUGGER_LLDB,
            choices=[_DEBUGGER_LLDB, _DEBUGGER_GDB],
            help="Choose the debugger to use. The corresponding server will be "
            "used on the remote device in remote debugging mode.",
        )

        parser.add_argument(
            "--debugger-path",
            type=pathlib.Path,
            help="Override the path to use for the local debugger binary. If "
            "unspecified, defaults to the value of --debugger.",
        )

        parser.add_argument(
            "--platform-port-local",
            type=int,
            help="Select a port to use for the LLDB platform connection on the "
            "local machine. Defaults to automatically choosing an available "
            "port. Requires --debugger=lldb.",
        )
        parser.add_argument(
            "--platform-port-remote",
            type=int,
            help="Select a port to use for the LLDB platform connection on the "
            "remote device. Defaults to automatically choosing an available "
            "port. Requires --debugger=lldb.",
        )
        parser.add_argument(
            "--gdbserver-port",
            type=int,
            help="Select a port to use for the gdbserver connection. The same "
            "port number will be used for both the local and remote devices. "
            "Defaults to automatically selecting an available port.",
        )

        parser.add_argument(
            "-g",
            "--debug-arg",
            type=str,
            action="append",
            dest="debugger_args",
            metavar="DEBUGGER_ARG",
            help="Provide additional sets of argument(s) to the debugger. Can "
            "be specified multiple times. Arguments are placed after all other "
            "setup commands. Groups of arguments given to a single -g are "
            "split on spaces just as a shell would interpret them.",
        )

        parser.add_argument(
            "--corefile",
            type=pathlib.Path,
            help="Provide a path to a coredump file to open with the debugger. "
            "The matching executable must also be provided with --exe. Note "
            "that this path is rooted in the board sysroot.",
        )

    @classmethod
    def ProcessOptions(cls, parser, options) -> None:
        """Post process options."""
        if not (options.pid or options.exe):
            parser.error(
                "Must use --exe or --pid to specify the process to debug."
            )

        if options.device is None:
            if options.pid is not None:
                parser.error(
                    "--pid is unsupported for local debugging. Use --exe to "
                    "specify a new process target, or specify a remote device."
                )

            if options.board is None:
                parser.error(
                    "--board must be specified if remote device is not given."
                )

        if options.pid and (options.list or options.exe):
            parser.error("--list and --exe are disallowed when --pid is used.")

        if options.exe is not None and not options.exe.is_absolute():
            parser.error(
                "--exe must have a full pathname, rooted in the board's build "
                "root."
            )

        if options.corefile is not None:
            if not options.corefile.is_absolute():
                parser.error(
                    "--corefile must have a full pathname, rooted in the "
                    "board's build root."
                )
            if options.exe is None:
                parser.error(
                    "If providing --corefile, --exe must also be provided."
                )

        if options.debugger != _DEBUGGER_LLDB:
            if options.use_remote_exe:
                parser.error("--use-remote-exe requires --debugger=lldb.")

            if options.platform_port_local:
                parser.error("--platform-port-local requires --debugger=lldb.")

            if options.platform_port_remote:
                parser.error("--platform-port-remote requires --debugger=lldb.")

    def _ListProcesses(self, device, pids) -> None:
        """Print out information of the processes in |pids|."""
        if not pids:
            logging.info(
                "No running process of %s on device %s",
                self.exe,
                self.ssh_hostname,
            )
            return

        try:
            result = device.run(["ps", "aux"])
            lines = result.stdout.splitlines()
            try:
                header, procs = lines[0], lines[1:]
                info = os.linesep.join(
                    [p for p in procs if int(p.split()[1]) in pids]
                )
            except ValueError:
                cros_build_lib.Die("Parsing output failed:\n%s", result.stdout)

            print(
                "\nList running processes of %s on device %s:\n%s\n%s"
                % (self.exe, self.ssh_hostname, header, info)
            )
        except cros_build_lib.RunCommandError:
            cros_build_lib.Die(
                "Failed to find any running process on device %s",
                self.ssh_hostname,
            )

    def _ReadOptions(self) -> None:
        """Process options and set variables."""
        if self.options.device:
            self.ssh_hostname = self.options.device.hostname
            self.ssh_username = self.options.device.username
            self.ssh_port = self.options.device.port
            self.device = self.options.device
        self.ssh_private_key = self.options.private_key
        self.list = self.options.list
        self.exe = self.options.exe
        self.pid = self.options.pid
        self.use_remote_exe = self.options.use_remote_exe
        self.debugger_name = self.options.debugger
        self.sysroot = self.options.sysroot
        self.board = self.options.board
        self.corefile = self.options.corefile

        self.debugger_path = (
            self.debugger_name
            if self.options.debugger_path is None
            else self.options.debugger_path
        )

        self.debugger_args = (
            []
            if self.options.debugger_args is None
            # properly escape all debugger args
            else [
                a
                for arg in self.options.debugger_args
                for a in shlex.split(arg)
            ]
        )

    def _DebugNewProcess(self) -> None:
        """Start a new process on the target device and attach gdb to it."""
        logging.info(
            "Ready to start and debug %s on device %s",
            self.exe,
            self.ssh_hostname,
        )
        with self.debug_server.start_server():
            self.debug_server.debug_new_process(
                self.exe,
                use_remote_binary=self.use_remote_exe,
                board=self.board,
            )

    def _DebugRunningProcess(self, pid) -> None:
        """Start gdb and attach it to the remote running process with |pid|."""
        logging.info(
            "Ready to debug process %d on device %s", pid, self.ssh_hostname
        )
        with self.debug_server.start_server():
            self.debug_server.debug_existing_process(pid, board=self.board)

    def _RunLocal(self) -> None:
        # Set sysroot to build dir within the chroot
        if self.sysroot is None:
            self.sysroot = build_target_lib.get_default_sysroot_path(self.board)

        # adding mounts and calling chroot require root privilege, so
        # reexecute the program as root if needed.
        if osutils.IsNonRootUser():
            cmd = ["sudo", "-E", "--"] + sys.argv
            os.execvp(cmd[0], cmd)

        # unshare so that bind mounts are cleaned up on program exit
        namespaces.Unshare(namespaces.CLONE_NEWNS)

        qemu_arch = qemu.Qemu.DetectArch(self.debugger_name, self.sysroot)
        if qemu_arch is not None:
            logging.info("qemu_arch detected: %s", qemu_arch)
            self.qemu = qemu.Qemu(self.sysroot, arch=qemu_arch)
            self.qemu.Install(self.sysroot)
            self.qemu.RegisterBinfmt()

        # set up sysroot
        for mount in _BIND_MOUNT_PATHS:
            path = os.path.join(self.sysroot, mount)
            osutils.SafeMakedirs(path)
            osutils.Mount(
                os.path.join("/", mount), path, "none", osutils.MS_BIND
            )

        os.chroot(self.sysroot)

        if shutil.which(self.debugger_path) is None:
            cros_build_lib.Die(
                "Debugger path %s was not found in the board sysroot."
                " Did you build dev-util/lldb-server for your board "
                "with the USE='local-lldb' flag?",
                self.debugger_path,
            )

        self.debug_server = debugger.LLVMDebugger(
            debugger_path=self.debugger_path,
            debugger_args=self.debugger_args,
            sysroot=self.sysroot,
        )
        self.debug_server.debug_new_process(self.exe, board=self.board)

    def _RunRemote(self) -> None:
        using_lldb = self.debugger_name == _DEBUGGER_LLDB
        with remote_access.ChromiumOSDeviceHandler(
            self.ssh_hostname,
            port=self.ssh_port,
            username=self.ssh_username,
            private_key=self.ssh_private_key,
        ) as device:
            self.board = cros_build_lib.GetBoard(
                device_board=device.board,
                override_board=self.options.board,
                strict=True,
            )
            logging.info("Board is %s", self.board)

            if self.sysroot is None:
                self.sysroot = build_target_lib.get_default_sysroot_path(
                    self.board
                )

            self.debug_server = debugger.LLVMDebugger(
                debugger_path=self.debugger_path,
                debugger_args=self.debugger_args,
                remote_device=device,
                sysroot=self.sysroot,
            )

            if self.pid:
                self._DebugRunningProcess(self.pid)
                return

            logging.debug("Executable path is %s", self.exe)
            if not using_lldb and not device.IsFileExecutable(self.exe):
                cros_build_lib.Die(
                    'File path "%s" does not exist or is not executable on '
                    "device %s",
                    self.exe,
                    self.ssh_hostname,
                )

            pids = device.GetRunningPids(self.exe)
            self._ListProcesses(device, pids)

            if self.list:
                # If '--list' flag is on, do not launch a debugger.
                return

            if pids:
                choices = ["Start a new process under LLDB"]
                choices.extend(pids)
                idx = cros_build_lib.GetChoice(
                    "Please select the process pid to debug (select [0] to "
                    "start a new process):",
                    choices,
                )
                if idx == 0:
                    self._DebugNewProcess()
                else:
                    self._DebugRunningProcess(pids[idx - 1])
            else:
                self._DebugNewProcess()

    def Run(self) -> None:
        """Run cros debug."""
        commandline.RunInsideChroot(self)
        self._ReadOptions()

        if self.debugger_name == _DEBUGGER_GDB:
            logging.error(
                "gdb is not yet supported. Please use --debugger=lldb instead."
            )
            return

        # Prepend corefile so that -g args appear last, as stated in help text
        if self.corefile is not None:
            self.debugger_args = [
                "-c",
                shell_util.quote(self.corefile),
            ] + self.debugger_args

        # local debugging
        if self.device is None:
            return self._RunLocal()

        # remote debugging
        return self._RunRemote()
