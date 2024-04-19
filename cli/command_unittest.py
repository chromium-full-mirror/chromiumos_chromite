# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the command module."""

import argparse
import importlib
import os
from typing import List, Optional

import pytest

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock


# pylint:disable=protected-access

_COMMAND_NAME = "superAwesomeCommandOfFunness"


@command.command_decorator(_COMMAND_NAME)
class TestCommand(command.CliCommand):
    """A fake command."""

    def Run(self) -> None:
        print("Just testing")


class TestCommandTest(cros_test_lib.MockTestCase):
    """This test class tests that Commands method."""

    def testParserSetsCommandClass(self) -> None:
        """Tests that our parser sets command_class correctly."""
        my_parser = argparse.ArgumentParser()
        command.CliCommand.AddParser(my_parser)
        ns = my_parser.parse_args([])
        self.assertEqual(ns.command_class, command.CliCommand)

    def testCommandDecorator(self) -> None:
        """Tests that our decorator correctly adds TestCommand to _commands."""
        # Note this exposes an implementation detail of _commands.
        self.assertEqual(command._commands[_COMMAND_NAME], TestCommand)

    def testBadUseOfCommandDecorator(self) -> None:
        """Tests that our decorator correctly rejects bad test commands."""
        try:
            # pylint: disable=unused-variable
            @command.command_decorator("bad")
            class BadTestCommand:
                """A command that wasn't implemented correctly."""

        except command.InvalidCommandError:
            pass
        else:
            self.fail("Invalid command was accepted by @command_decorator")

    def testAddDeviceArgument(self) -> None:
        """Tests CliCommand.AddDeviceArgument()."""
        parser = argparse.ArgumentParser()
        command.CliCommand.AddDeviceArgument(parser, positional=True)
        # Device should be a positional argument.
        parser.parse_args(["device"])

    def testAddNamedDeviceArgument(self) -> None:
        """Tests CliCommand.AddDeviceArgument()."""
        parser = argparse.ArgumentParser()
        command.CliCommand.AddDeviceArgument(parser, positional=False)
        # Device should be a named argument.
        parser.parse_args(["--device=device"])
        parser.parse_args(["-d", "device"])


class MockCommand(partial_mock.PartialMock):
    """Mock class for a generic CLI command."""

    ATTRS = ("Run",)
    COMMAND = None
    TARGET_CLASS = None

    def __init__(self, args, base_args=None) -> None:
        partial_mock.PartialMock.__init__(self)
        self.args = args
        self.rc_mock = cros_test_lib.RunCommandMock()
        self.rc_mock.SetDefaultCmdResult()
        self.parser = parser = commandline.ArgumentParser(caching=True)
        subparsers = parser.add_subparsers()
        subparser = subparsers.add_parser(
            self.COMMAND,
            caching=self.TARGET_CLASS.use_caching_options,
            dryrun=self.TARGET_CLASS.use_dryrun_options,
        )
        self.TARGET_CLASS.AddParser(subparser)

        args = base_args if base_args else []
        args += [self.COMMAND] + self.args
        options = parser.parse_args(args)
        self.inst = options.command_class(options)

    def Run(self, inst):
        with self.rc_mock:
            return self.backup["Run"](inst)


class CommandTest(cros_test_lib.MockTestCase):
    """This test class tests that we can load modules correctly."""

    def testFindModules(self) -> None:
        """Tests that we can return modules correctly when mocking out glob."""
        fake_command_file = "cros_command_test.py"
        filtered_file = "cros_command_unittest.py"

        self.PatchObject(
            os, "listdir", return_value=[fake_command_file, filtered_file]
        )

        self.assertEqual(command.ListCommands(), {"command-test"})

    def testLoadCommands(self) -> None:
        """Tests import commands correctly."""
        fake_module = "cros_command_test"
        module_path = "chromite.cli.cros.%s" % fake_module

        # The code doesn't use the return value, so stub it out lazy-like.
        load_mock = self.PatchObject(
            importlib, "import_module", return_value=None
        )

        command._commands["command-test"] = 123
        self.assertEqual(command.ImportCommand("command-test"), 123)
        command._commands.pop("command-test")

        load_mock.assert_called_with(module_path)

    def testListCrosCommands(self) -> None:
        """Tests we get a correct `cros` list back."""
        cros_commands = command.ListCommands()
        # Pick some commands that are likely to not go away.
        self.assertIn("chrome-sdk", cros_commands)
        self.assertIn("flash", cros_commands)


class MainGroup(command.CommandGroup):
    """Some group of commands."""


@MainGroup.subcommand("subgroup")
class SubGroup(command.CommandGroup):
    """A nested group under a group."""


@SubGroup.subcommand("subcmd", caching=True, dryrun=True)
class SubSubCommand(command.CliCommand):
    """A subcommand in the nested group."""

    def Run(self) -> Optional[int]:
        """The main handler of this CLI."""
        if self.options.dryrun:
            return 79
        return 42


@MainGroup.subcommand("mainsub")
class MainSub(command.CliCommand):
    """Another subcommand with custom options."""

    @classmethod
    def AddParser(cls, parser: commandline.ArgumentParser) -> None:
        """Add custom options."""
        parser.add_argument("--return-value", type=int, default=12)

    def Run(self) -> Optional[int]:
        """The main handler of this CLI."""
        return self.options.return_value


@pytest.mark.parametrize(
    ["args", "expected_return_code"],
    [
        (["--help"], 0),
        (["subgroup", "--help"], 0),
        (["subgroup", "subcmd", "--help"], 0),
        (["mainsub", "--help"], 0),
        (["subgroup", "subcmd"], 42),
        (["subgroup", "subcmd", "--dry-run"], 79),
        (["mainsub"], 12),
        (["mainsub", "--return-value", "21"], 21),
    ],
)
def test_command_group(args: List[str], expected_return_code: int) -> None:
    """Test CommandGroup helper."""

    def _main(args: List[str]) -> int:
        """Helper to call MainGroup with options."""
        parser = commandline.ArgumentParser()
        MainGroup.AddParser(parser)
        try:
            opts = parser.parse_args(args)
        except SystemExit as e:
            return e.code or 0
        MainGroup.ProcessOptions(parser, opts)
        opts.Freeze()
        cmd = MainGroup(opts)
        try:
            return cmd.Run() or 0
        except SystemExit as e:
            return e.code or 0

    assert _main(args) == expected_return_code
