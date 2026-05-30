# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for commands."""

from chromite.cbuildbot import commands
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock


# pylint: disable=protected-access


class ChromeSDKTest(cros_test_lib.RunCommandTempDirTestCase):
    """Basic tests for ChromeSDK commands with run mocked out."""

    BOARD = "daisy_foo"
    EXTRA_ARGS = ("--monkey", "banana")
    EXTRA_ARGS2 = ("--donkey", "kong")
    CHROME_SRC = "chrome_src"
    CMD = ["bar", "baz"]
    CWD = "fooey"

    def setUp(self) -> None:
        self.inst = commands.ChromeSDK(self.CWD, self.BOARD)

    def testRunCommand(self) -> None:
        """Test that running a command is possible."""
        self.inst.Run(self.CMD)
        self.assertCommandContains([self.BOARD] + self.CMD, cwd=self.CWD)

    def testRunCommandWithRunArgs(self) -> None:
        """Test run_args optional argument for run kwargs."""
        self.inst.Run(self.CMD, run_args={"log_output": True})
        self.assertCommandContains(
            [self.BOARD] + self.CMD, cwd=self.CWD, log_output=True
        )

    def testRunCommandKwargs(self) -> None:
        """Exercise optional arguments."""
        custom_inst = commands.ChromeSDK(
            self.CWD,
            self.BOARD,
            extra_args=list(self.EXTRA_ARGS),
            chrome_src=self.CHROME_SRC,
            debug_log=True,
        )
        custom_inst.Run(self.CMD, list(self.EXTRA_ARGS2))
        self.assertCommandContains(
            ["debug", self.BOARD]
            + list(self.EXTRA_ARGS)
            + list(self.EXTRA_ARGS2)
            + self.CMD,
            cwd=self.CWD,
        )

    def MockGetDefaultTarget(self) -> None:
        self.rc.AddCmdResult(
            partial_mock.In("qlist-%s" % self.BOARD),
            stdout="%s" % constants.CHROME_CP,
        )

    def testNinjaWithRunArgs(self) -> None:
        """Test that running ninja with run_args.

        run_args is an optional argument for run kwargs.
        """
        self.MockGetDefaultTarget()
        self.inst.Ninja(run_args={"log_output": True})
        self.assertCommandContains(
            [
                "autoninja",
                "-C",
                "out_%s/Release" % self.BOARD,
                "chromiumos_preflight",
            ],
            cwd=self.CWD,
            log_output=True,
        )

    def testNinjaOptions(self) -> None:
        """Test that running ninja with non-default options."""
        self.MockGetDefaultTarget()
        custom_inst = commands.ChromeSDK(self.CWD, self.BOARD)
        custom_inst.Ninja(debug=True)
        self.assertCommandContains(
            [
                "autoninja",
                "-C",
                "out_%s/Debug" % self.BOARD,
                "chromiumos_preflight",
            ]
        )
