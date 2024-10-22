# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for cros_run_unit_tests.py."""

import os
from typing import List
from unittest import mock

import pytest

from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock
from chromite.scripts import cros_run_unit_tests


pytestmark = cros_test_lib.pytestmark_inside_only


class CrosRunUnitTestsTest(cros_test_lib.MockTestCase):
    """Tests for cros_run_unit_tests functions."""

    def testNonEmptyPackageSet(self) -> None:
        """Asserts that the deps of a known package are non-empty"""
        self.assertTrue(
            cros_run_unit_tests.determine_packages(
                "/", ("virtual/implicit-system",)
            )
        )

    def testGetKeepGoing(self) -> None:
        """Tests set keep_going option based on env virables"""
        self.PatchObject(os, "environ", new={"USE": "chrome_internal coverage"})
        keep_going = cros_run_unit_tests.get_keep_going()
        self.assertEqual(keep_going, True)


@mock.patch("chromite.lib.cros_build_lib.IsInsideChroot", return_value=True)
@mock.patch(
    "chromite.lib.workon_helper.WorkonHelper.InstalledWorkonAtoms",
    return_value=set(("baz/abc", "foo/bar")),
)
@mock.patch(
    "chromite.lib.portage_util.PackagesWithTest", return_value=set(("foo/bar",))
)
@pytest.mark.parametrize(
    "test_args",
    (
        ["--host"],
        ["--board", "amd64-generic"],
        ["--host", "--packages", "foo/bar"],
        ["--board", "amd64-generic", "--packages", "foo/bar"],
    ),
)
def test_failure_code(_, __, ___, run_mock, test_args: List[str]) -> None:
    """Assert we propagate command failures as return codes."""
    run_mock.AddCmdResult(
        partial_mock.In(str(constants.CHROMITE_BIN_DIR / "parallel_emerge")),
        returncode=42,
    )

    # Callers tend to look for non-zero, but we always use "1" for now.
    assert cros_run_unit_tests.main(test_args) == 1

    # Double-check we really hit the (mocked) parallel_emerge.
    assert run_mock.CommandContains(
        [constants.CHROMITE_BIN_DIR / "parallel_emerge"]
    )
