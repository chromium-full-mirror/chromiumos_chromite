# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros cp: Copy files to/from a target device."""

import argparse

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
"""

    def __init__(self, options):
        """Initializes CpCommand."""
        super().__init__(options)
        self.device = None
        self.hostname = None
        self.port = None
        self.username = None
        self.to_local = None
        self.permission = None
        self.mode = None
        self.src = None
        self.dest = None

    @classmethod
    def AddParser(cls, parser):
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
        # TODO(b:271334340): Need to support permission.
        parser.add_argument(
            "--permission",
            type=str,
            help=argparse.SUPPRESS,
        )
        parser.add_argument(
            "--mode",
            default="scp",
            choices=("rsync", "scp"),
            help="Transfer mode (default: %(default)s)",
        )

    @classmethod
    def ProcessOptions(cls, parser, options):
        """Post process options."""
        if len(options.device) < 2:
            parser.error("Need at least 2 args, src and dest")

    def _ReadOptions(self):
        """Processes options and set variables."""
        self.src = self.options.device[0:-1]
        self.dest = self.options.device[-1]
        self.to_local = self.dest.scheme != commandline.DeviceScheme.SCP
        remote = self.src[0] if self.to_local else self.dest
        self.hostname = remote.hostname
        self.username = remote.username
        self.port = self.options.port
        self.permission = self.options.permission
        self.mode = self.options.mode

    def _StartCp(self):
        """Starts copying files from/to device.

        Requires that _ReadOptions() has already been called to provide the
        remote access configuration.

        Returns:
            The return of CopyFromDevice or CopyToDevice.

        Raises:
            RemoteAccessException on remote access failure.
        """
        self.device = remote_access.ChromiumOSDevice(
            self.hostname,
            port=self.port,
            username=self.username,
        )
        for src in self.src:
            if self.to_local:
                ret = self.device.CopyFromDevice(
                    src=src.path,
                    dest=self.dest.path,
                    mode=self.mode,
                )
            else:
                ret = self.device.CopyToDevice(
                    src=src.path,
                    dest=self.dest.path,
                    mode=self.mode,
                )
            if ret:
                break
        return ret

    def Run(self):
        """Runs `cros cp`."""
        self._ReadOptions()

        try:
            return self._StartCp()
        except remote_access.RemoteAccessException:
            if self.options.debug:
                raise
            else:
                return 1
