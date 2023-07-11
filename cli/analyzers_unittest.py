# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the analyzers module."""

from chromite.cli import analyzers


def test_get_files_from_commit(run_mock) -> None:
    run_mock.AddCmdResult(
        ["git", "rev-parse", "--show-toplevel"], stdout="/path/to/root\n"
    )
    run_mock.SetDefaultCmdResult(stdout="file1\nsub/file2\n")
    assert analyzers.GetFilesFromCommit("ignored") == [
        "/path/to/root/file1",
        "/path/to/root/sub/file2",
    ]


def test_has_uncommitted_changes(run_mock) -> None:
    run_mock.SetDefaultCmdResult(stdout="M file\n")
    assert analyzers.HasUncommittedChanges(["/path/to/file"]) is True


def test_has_no_uncommitted_changes(run_mock) -> None:
    run_mock.SetDefaultCmdResult(stdout="")
    assert analyzers.HasUncommittedChanges(["/path/to/file"]) is False
