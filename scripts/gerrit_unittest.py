# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the gerrit module."""

import pytest

from chromite.scripts import gerrit


def test_main_usage() -> None:
    """Basic tests for the main help."""
    # Missing subcommand is an error.
    with pytest.raises(SystemExit) as excinfo:
        gerrit.main([])
    assert excinfo.value.code != 0

    with pytest.raises(SystemExit) as excinfo:
        gerrit.main(["--help"])
    assert excinfo.value.code == 0

    actions = gerrit._GetActions()  # pylint: disable=protected-access
    # Don't track exactly how many actions there are, just make sure we have a
    # reasonable return value.
    assert len(actions) > 20
    assert "help" in actions
    assert "search" in actions

    # Check help for all subcommands.
    for action in actions:
        with pytest.raises(SystemExit) as excinfo:
            gerrit.main(["help", action])
        assert excinfo.value.code == 0

    gerrit.main(["help-all"])


DATA_PROCESS_ADD_REMOVE_LISTS = (
    # No inputs means no outputs.
    ([], set(), set()),
    (["a"], {"a"}, set()),
    (["~a"], set(), {"a"}),
    (["a", "~a"], set(), {"a"}),
    (["~a", "a"], {"a"}, set()),
    (["a", "b", "c", "~d"], {"a", "b", "c"}, {"d"}),
    (["-a", "a"], {"a"}, set()),
)


@pytest.mark.parametrize(
    "items, exp_add, exp_remove", DATA_PROCESS_ADD_REMOVE_LISTS
)
def test_process_add_remove_lists(items, exp_add, exp_remove) -> None:
    """Test process_add_remove_lists behavior."""
    add, remove = gerrit.process_add_remove_lists(items)
    assert add == exp_add and remove == exp_remove


def test_process_add_remove_lists_invalid() -> None:
    """Test validation errors."""
    # Never accept the empty string.
    with pytest.raises(SystemExit) as excinfo:
        gerrit.process_add_remove_lists([""])
    assert excinfo.value.code != 0


def test_action_deps_related_changes(capsys, monkeypatch) -> None:
    """Test ActionDeps leverages related changes cache."""
    helper = gerrit.gerrit.GetGerritHelper(remote="cros")

    sha100 = "100" + "0" * 37
    sha99 = "099" + "0" * 37
    sha98 = "098" + "0" * 37

    related_info = {
        "changes": [
            {
                "project": "chromiumos/test",
                "change_id": "I100",
                "_change_number": 100,
                "_current_revision_number": 1,
                "status": "NEW",
                "commit": {
                    "commit": sha100,
                    "parents": [{"commit": sha99}],
                    "subject": "commit 100",
                    "author": {"name": "User", "email": "user@test.org"},
                },
            },
            {
                "project": "chromiumos/test",
                "change_id": "I99",
                "_change_number": 99,
                "_current_revision_number": 1,
                "status": "NEW",
                "commit": {
                    "commit": sha99,
                    "parents": [{"commit": sha98}],
                    "subject": "commit 99",
                    "author": {"name": "User", "email": "user@test.org"},
                },
            },
            {
                "project": "chromiumos/test",
                "change_id": "I98",
                "_change_number": 98,
                "_current_revision_number": 1,
                "status": "MERGED",
                "commit": {
                    "commit": sha98,
                    "parents": [],
                    "subject": "commit 98",
                    "author": {"name": "User", "email": "user@test.org"},
                },
            },
        ]
    }

    initial_patch = gerrit.patch.GerritPatch(
        {
            "project": "chromiumos/test",
            "branch": "main",
            "id": "I100",
            "number": "100",
            "url": "https://chromium-review.googlesource.com/c/100",
            "status": "NEW",
            "subject": "commit 100",
            "commitMessage": "commit 100",
            "owner": {"name": "User", "email": "user@test.org"},
            "dependsOn": [{"revision": sha99}],
            "currentPatchSet": {
                "revision": sha100,
                "number": "1",
                "ref": "refs/changes/00/100/1",
                "approvals": [],
            },
        },
        "cros",
        "https://chromium-review.googlesource.com/",
    )

    query_calls = []

    def fake_query(_opts, query, **_kwargs):
        query_calls.append(query)
        if query == "100":
            return [initial_patch]
        return []

    monkeypatch.setattr(gerrit, "_Query", fake_query)
    monkeypatch.setattr(
        helper, "GetRelatedChangesInfo", lambda _change: related_info
    )

    opts = type(
        "Opts",
        (),
        {
            "query": "100",
            "format": gerrit.OutputFormat.RAW,
            "gob": "chromium",
            "debug": False,
            "gerrit": {"cros": helper},
        },
    )()

    action = gerrit.ActionDeps()
    action(opts)

    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert lines == ["chromium:99", "chromium:100"]
    # Verify the initial query and batch query for open stack changes were made,
    # without making separate 1-by-1 queries for each parent commit hash.
    assert query_calls == ["100", "change:100 OR change:99"]


def test_action_rebase(capsys, monkeypatch) -> None:
    """Test ActionRebase invokes RebaseChange."""
    helper = gerrit.gerrit.GetGerritHelper(remote="cros")
    rebase_calls = []

    def fake_rebase_change(change, **kwargs):
        rebase_calls.append((change, kwargs))
        return {"_number": int(change)}

    monkeypatch.setattr(helper, "RebaseChange", fake_rebase_change)

    opts = type(
        "Opts",
        (),
        {
            "cls": ["123", "124"],
            "base": "456",
            "allow_conflicts": False,
            "on_behalf_of_uploader": None,
            "dryrun": False,
            "format": gerrit.OutputFormat.RAW,
            "gob": "chromium",
            "parser": None,
            "gerrit": {"chromium": helper},
        },
    )()

    action = gerrit.ActionRebase()
    action(opts)

    captured = capsys.readouterr()
    assert captured.out.strip().splitlines() == ["123", "124"]
    assert rebase_calls == [
        (
            "123",
            {
                "base": "456",
                "allow_conflicts": False,
                "on_behalf_of_uploader": True,
                "dryrun": False,
            },
        ),
        (
            "124",
            {
                "base": "456",
                "allow_conflicts": False,
                "on_behalf_of_uploader": True,
                "dryrun": False,
            },
        ),
    ]


def test_action_rebase_allow_conflicts_default_uploader(monkeypatch) -> None:
    """Test ActionRebase with allow_conflicts defaults uploader to False."""
    helper = gerrit.gerrit.GetGerritHelper(remote="cros")
    rebase_calls = []

    def fake_rebase_change(change, **kwargs):
        rebase_calls.append((change, kwargs))
        return {"_number": int(change)}

    monkeypatch.setattr(helper, "RebaseChange", fake_rebase_change)

    opts = type(
        "Opts",
        (),
        {
            "cls": ["123"],
            "base": None,
            "allow_conflicts": True,
            "on_behalf_of_uploader": None,
            "dryrun": False,
            "format": gerrit.OutputFormat.RAW,
            "gob": "chromium",
            "parser": None,
            "gerrit": {"chromium": helper},
        },
    )()

    action = gerrit.ActionRebase()
    action(opts)

    assert rebase_calls == [
        (
            "123",
            {
                "base": None,
                "allow_conflicts": True,
                "on_behalf_of_uploader": False,
                "dryrun": False,
            },
        ),
    ]


def test_action_rebase_conflicts_and_on_behalf_of_uploader() -> None:
    """Test ActionRebase rejects combining conflicts with on-behalf.

    Both --allow-conflicts and --on-behalf-of-uploader cannot be used
    together.
    """
    with pytest.raises(SystemExit) as excinfo:
        gerrit.main(
            ["rebase", "--allow-conflicts", "--on-behalf-of-uploader", "123"]
        )
    assert excinfo.value.code != 0
