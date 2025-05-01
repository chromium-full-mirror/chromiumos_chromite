# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros cp: Copy files to/from a target device."""

from typing import Optional

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import remote_access


@command.command_decorator("cp")
class CpCommand(command.CliCommand):
    """Copy files to/from a target device.

    Can be used to copy files to/from a target device via scp(default) or
    rsync.
    """

    EPILOG = """
Examples:
    Copy files to/from a target devices:
        cros cp <ip>:<src_path> <dest_path>
        cros cp <ip>:<src_path> <dest_path> --mode=<scp/rsync>
        cros cp <src_path> <ip>:<dest_path>
        cros cp <user>@<ip>:<src_path> <dest_path> --port=<port>
        # Copy a remote file to stdout.
        cros cp <host>:<path> - | sort -u
"""

    def __init__(self, options) -> None:
        """Initializes CpCommand."""
        super().__init__(options)
        self.device: Optional[remote_access.ChromiumOSDevice] = None
        self.hostname: Optional[str] = None
        self.port: Optional[int] = None
        self.username: Optional[str] = None
        self.to_local: Optional[bool] = None
        self.mode: Optional[str] = None
        self.src: Optional[list[commandline.Device]] = None
        self.dest: Optional[commandline.Device] = None
        # Store raw option values, process them into kwargs later.
        self._chmod: Optional[str] = None
        self._chown: Optional[str] = None

    @classmethod
    def AddParser(cls, parser) -> None:
        """Adds a parser."""
        super(cls, CpCommand).AddParser(parser)
        # TODO(b:271334340): Need to implement for stdin/stdout as input/output.
        parser.add_argument(
            "device",
            nargs="+",
            type=commandline.DeviceParser(
                (
                    commandline.DeviceScheme.SCP,
                    commandline.DeviceScheme.FILE,
                )
            ),
            help="Device hostname or IP in the format hostname[:path] "
            "for remote. File Path for local.",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=22,
            help="Port to connect (default: %(default)s)",
        )
        parser.add_argument(
            "--mode",
            default="scp",
            choices=("rsync", "scp"),
            help="Transfer mode (default: %(default)s)",
        )
        parser.add_argument(
            "--chmod",
            type=str,
            help="Change file permission on remote device. Only for rsync.",
        )
        parser.add_argument(
            "--chown",
            type=str,
            help="Change file owner/group on remote device. Only for rsync.",
        )

    @classmethod
    def ProcessOptions(cls, parser, options) -> None:
        """Post process options."""
        if len(options.device) < 2:
            parser.error("Need at least 2 args, src and dest")

    def _ReadOptions(self) -> None:
        """Processes options and set variables."""
        self.src = self.options.device[0:-1]
        self.dest = self.options.device[-1]
        self.to_local = self.dest.scheme != commandline.DeviceScheme.SCP
        remote = self.src[0] if self.to_local else self.dest
        self.hostname = remote.hostname
        self.username = remote.username
        self.port = self.options.port
        self.mode = self.options.mode
        # Store raw options to be processed later.
        self._chmod = self.options.chmod
        self._chown = self.options.chown

    def _StartCp(self) -> None:
        """Starts copying files from/to device.

        Requires that _ReadOptions() has already been called to provide the
        remote access configuration.

        Raises:
            RemoteAccessException on remote access failure.
        """
        self.device = remote_access.ChromiumOSDevice(
            self.hostname,
            port=self.port,
            username=self.username,
        )
        func = (
            self.device.CopyFromDevice
            if self.to_local
            else self.device.CopyToDevice
        )

        for src in self.src:
            func(
                src=src.path,
                dest=self.dest.path,
                mode=self.mode,
                chmod=self._chmod,
                chown=self._chown,
            )

    def Run(self):
        """Runs `cros cp`."""
        self._ReadOptions()

        try:
            self._StartCp()
        except remote_access.RemoteAccessException:
            if self.options.debug:
                raise
            else:
                return 1

        return 0
