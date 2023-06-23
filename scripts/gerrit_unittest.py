# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the gerrit module."""

import pytest

from chromite.scripts import gerrit


def test_main_usage():
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
