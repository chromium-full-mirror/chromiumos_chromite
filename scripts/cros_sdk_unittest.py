# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for cros_sdk."""

import os
import re
import sys
from typing import List, Optional
from unittest import mock

import pytest  # type: ignore

from chromite.lib import chromite_config
from chromite.lib import constants
from chromite.lib import cros_sdk_lib
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock
from chromite.scripts import cros_sdk


_PARSER, _COMMANDS = cros_sdk.CreateParser(
    cros_sdk_lib.SdkVersionConfig("1", "2")
)


class CrosSdkUtilsTest(cros_test_lib.MockTempDirTestCase):
    """Tests for misc util funcs."""

    def test_get_sdk_tarball_urls(self) -> None:
        """Basic test of get_sdk_tarball_urls."""
        self.assertCountEqual(
            [
                "https://storage.googleapis.com/chromiumos-sdk/"
                "cros-sdk-123.tar.xz",
                "https://storage.googleapis.com/chromiumos-sdk/"
                "cros-sdk-123.tar.zst",
            ],
            cros_sdk.get_sdk_tarball_urls("123"),
        )

    def test_get_sdk_tarball_urls_with_bucket(self) -> None:
        """Test of get_sdk_tarball_urls with a custom bucket."""
        self.assertCountEqual(
            [
                "https://storage.googleapis.com/staging-chromiumos-sdk/"
                "cros-sdk-123.tar.xz",
                "https://storage.googleapis.com/staging-chromiumos-sdk/"
                "cros-sdk-123.tar.zst",
            ],
            cros_sdk.get_sdk_tarball_urls(
                "123",
                bucket="staging-chromiumos-sdk",
            ),
        )

    def testLogPathHolders(self) -> None:
        """Check log_path_holders handling."""
        rc = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc.AddCmdResult(
            partial_mock.ListRegex(f"lsof.*{self.tempdir}"),
            0,
            stdout="123\n456\n",
        )
        rc.AddCmdResult(["ps", "123"], 0, stdout="foo\n")
        cros_sdk.log_path_holders(self.tempdir, ignore_pids={"456"})


class CrosSdkParserCommandLineTest(cros_test_lib.MockTestCase):
    """Tests involving the CLI."""

    # pylint: disable=protected-access

    # A typical sys.argv[0] that cros_sdk sees.
    ARGV0 = "/home/chronos/chromiumos/chromite/bin/cros_sdk"

    def testSudoCommand(self) -> None:
        """Verify basic sudo command building works."""
        # Stabilize the env for testing.
        for v in (
            constants.CHROOT_ENVIRONMENT_ALLOWLIST + constants.ENV_PASSTHRU
        ):
            os.environ[v] = "value"
        os.environ["PATH"] = "path"

        cmd = cros_sdk._SudoCommand()
        assert cmd[0] == "sudo"
        assert "CHROMEOS_SUDO_PATH=path" in cmd
        rlimits = [x for x in cmd if x.startswith("CHROMEOS_SUDO_RLIMITS=")]
        assert len(rlimits) == 1

        # Spot check some pass thru vars.
        assert "GIT_AUTHOR_EMAIL=value" in cmd
        assert "https_proxy=value" in cmd

        # Make sure we only pass vars after `sudo`.
        for i in range(1, len(cmd)):
            assert "=" in cmd[i]
            v = cmd[i].split("=", 1)[0]
            assert re.match(r"^[A-Za-z0-9_]+$", v) is not None

    def testReexecCommand(self) -> None:
        """Verify reexec command line building."""
        # Stub sudo logic since we tested it above already.
        self.PatchObject(cros_sdk, "_SudoCommand", return_value=["sudo"])
        opts = _PARSER.parse_args([])
        new_cmd = cros_sdk._BuildReExecCommand([self.ARGV0], opts)
        assert new_cmd == ["sudo", "--", sys.executable, self.ARGV0]

    def testReexecCommandStrace(self) -> None:
        """Verify reexec command line building w/strace."""
        # Stub sudo logic since we tested it above already.
        self.PatchObject(cros_sdk, "_SudoCommand", return_value=["sudo"])

        # Strace args passed, but not enabled.
        opts = _PARSER.parse_args(["--strace-arguments=-s4096 -v"])
        new_cmd = cros_sdk._BuildReExecCommand([self.ARGV0], opts)
        assert new_cmd == ["sudo", "--", sys.executable, self.ARGV0]

        # Strace enabled.
        opts = _PARSER.parse_args(["--strace"])
        new_cmd = cros_sdk._BuildReExecCommand([self.ARGV0], opts)
        assert new_cmd == [
            "sudo",
            "--",
            "strace",
            "--",
            sys.executable,
            self.ARGV0,
        ]

        # Strace enabled w/args.
        opts = _PARSER.parse_args(["--strace", "--strace-arguments=-s4096 -v"])
        new_cmd = cros_sdk._BuildReExecCommand([self.ARGV0], opts)
        assert new_cmd == [
            "sudo",
            "--",
            "strace",
            "-s4096",
            "-v",
            "--",
            sys.executable,
            self.ARGV0,
        ]


# pylint: disable=protected-access


def test_freeze_options() -> None:
    """Test that we can't change options after finalization."""
    options = _PARSER.parse_args([])
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)

    with pytest.raises(Exception):
        options.enter = True
        options.enter = False


def test_replace_alias() -> None:
    """Test the replace -> delete/create alias."""
    options = _PARSER.parse_args(["--replace"])
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)
    assert options.delete
    assert options.create


def test_implied_download() -> None:
    """Test that create implies download."""
    options = _PARSER.parse_args(["--create"])
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)
    assert options.download


@pytest.mark.parametrize(
    "arglist",
    (
        [],
        ["--enter"],
        ["--working-dir", "."],
    ),
)
def test_implied_enter(arglist: List[str]) -> None:
    """Test for implicit --enter."""
    options = _PARSER.parse_args(arglist)
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)
    assert options.enter


@pytest.mark.parametrize(
    "command",
    (
        "--create",
        "--replace",
        "--delete",
        "--download",
    ),
)
def test_commands(command: str) -> None:
    """Test options that don't imply --enter."""
    options = _PARSER.parse_args([command])
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)
    assert not options.enter


@pytest.mark.parametrize(
    "arglist",
    (
        ["--delete", "--enter"],
        ["--force"],  # without --delete
        ["--read-only-sticky"],  # without --[no-]read-only
    ),
)
def test_conflicting_args(arglist: List[str]) -> None:
    """Test args that conflict raise an error."""
    options = _PARSER.parse_args(arglist)
    with pytest.raises(SystemExit):
        cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)


def test_chroot_ready() -> None:
    """Ensure no implicit create when chroot is ready."""
    options = _PARSER.parse_args([])

    with mock.patch(
        "chromite.lib.cros_sdk_lib.IsChrootReady", return_value=True
    ):
        cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)

    assert not options.create
    assert options.enter


def test_chroot_not_ready() -> None:
    """Test implicit create when chroot isn't ready."""
    options = _PARSER.parse_args([])

    with mock.patch(
        "chromite.lib.cros_sdk_lib.IsChrootReady", return_value=False
    ):
        cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)

    assert options.create
    assert options.enter


@pytest.mark.parametrize(
    ["arglist", "confcontents", "expect_ro"],
    [
        ([], None, False),  # no args; no conf; default read-only=False
        ([], "1", True),  # no args; conf is "1"; read-only=True
        (
            [],
            "garbage",
            True,
        ),  # no args; conf is garbage, but contents are ignored
        (["--read-only"], "1", True),  # --read-only arg always wins
        (["--read-only"], "garbage", True),  # --read-only arg always wins
        (
            ["--no-read-only"],
            "garbage",
            False,
        ),  # --no-read-only arg always wins
        (["--no-read-only"], "1", False),  # --no-read-only arg always wins
        ([], "    0   \n", True),  # conf contents are ignored
    ],
)
def test_readonly_configuration(
    monkeypatch,
    tmp_path,
    arglist: List[str],
    confcontents: Optional[str],
    expect_ro: bool,
) -> None:
    """Test read-only configuration file and flags."""
    conf_file = tmp_path / "readonlyconf"
    if confcontents is not None:
        conf_file.touch()
    monkeypatch.setattr(
        chromite_config, "SDK_READONLY_STICKY_CONFIG", conf_file
    )

    options = _PARSER.parse_args(arglist)
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)
    assert options.read_only == expect_ro


@pytest.mark.parametrize(
    ["orig_contents", "arglist", "expect_conf_exists"],
    (
        (None, [], False),
        (None, ["--read-only"], False),
        (None, ["--no-read-only"], False),
        ("0", ["--read-only"], True),
        ("1", ["--no-read-only"], True),
        (None, ["--read-only", "--read-only-sticky"], True),
        (None, ["--no-read-only", "--read-only-sticky"], False),
        ("0", ["--read-only", "--read-only-sticky"], True),
        ("1", ["--no-read-only", "--read-only-sticky"], False),
    ),
)
def test_readonly_sticky(
    monkeypatch,
    tmp_path,
    orig_contents: Optional[str],
    arglist: List[str],
    expect_conf_exists: bool,
) -> None:
    """Test that we write expected read-only-sticky contents.

    orig_contents: Optional pre-existing contents of the configuration file.
    arglist: The cros_sdk argument list to test.
    expect_conf_exists: Whether we expect the conf file to exist.
    """
    conf_file = tmp_path / "readonlyconf"
    if orig_contents is not None:
        conf_file.write_text(orig_contents)
    monkeypatch.setattr(
        chromite_config, "SDK_READONLY_STICKY_CONFIG", conf_file
    )

    options = _PARSER.parse_args(arglist)
    cros_sdk._FinalizeOptions(_PARSER, options, _COMMANDS)

    assert conf_file.exists() == expect_conf_exists


@pytest.mark.parametrize(
    ["args", "expected"],
    (
        (["--replace"], True),
        (["--update"], False),
        (["--replace", "--no-delete-out-dir"], False),
        (["--update", "--delete-out-dir"], True),
        ([], False),
    ),
)
def test_delete_out(
    args,
    expected,
) -> None:
    """Test the resolved value for --delete-out-dir/--no-delete-out-dir.

    Args:
        args: The command line args.
        expected: The expected opts.delete_out_dir.
    """
    opts = _PARSER.parse_args(args)
    cros_sdk._FinalizeOptions(_PARSER, opts, _COMMANDS)

    assert opts.delete_out_dir is expected


@pytest.mark.parametrize(
    ["args", "expected"],
    (
        (["--delete"], False),
        (["--delete", "--update"], False),
        ([], True),
    ),
)
def test_update_with_delete(
    args,
    expected,
) -> None:
    """cros_sdk --delete should disable --update behavior.

    Args:
        args: The command line args.
        expected: The expected opts.update.
    """
    opts = _PARSER.parse_args(args)
    cros_sdk._FinalizeOptions(_PARSER, opts, _COMMANDS)

    assert opts.update is expected
