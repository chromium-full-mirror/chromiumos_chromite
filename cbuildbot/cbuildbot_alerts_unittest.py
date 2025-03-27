# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for cbuildbot_alerts."""

import pytest

from chromite.cbuildbot import cbuildbot_alerts
from chromite.lib import cros_test_lib


class CrosloggingTest(cros_test_lib.TestCase):
    """Test logging works as expected."""

    def setUp(self) -> None:
        # pylint: disable=protected-access
        cbuildbot_alerts._buildbot_markers_enabled = False

    @pytest.mark.usefixtures("legacy_capture_output")
    def testPrintBuildbotFunctionsNoMarker(self) -> None:
        """PrintBuildbot* w/out markers should not be recognized by buildbot."""
        cbuildbot_alerts.PrintBuildbotLink("name", "url")
        cbuildbot_alerts.PrintBuildbotStepText("text")
        cbuildbot_alerts.PrintBuildbotStepWarnings()
        cbuildbot_alerts.PrintBuildbotStepFailure()
        cbuildbot_alerts.PrintBuildbotStepName("name")
        cbuildbot_alerts.PrintKitchenSetBuildProperty("name", {"a": "value"})

        captured = self.capfd.readouterr()
        assert "STEP_LINK" in captured.err
        assert "STEP_TEXT" in captured.err
        assert "STEP_WARNINGS" in captured.err
        assert "STEP_FAILURE" in captured.err
        assert "BUILD_STEP" in captured.err
        assert "SET_BUILD_PROPERTY" in captured.err
        assert "@@@" not in captured.out
        assert "@@@" not in captured.err

    @pytest.mark.usefixtures("legacy_capture_output")
    def testPrintBuildbotFunctionsWithMarker(self) -> None:
        """PrintBuildbot* with markers should be recognized by buildbot."""
        cbuildbot_alerts.EnableBuildbotMarkers()
        cbuildbot_alerts.PrintBuildbotLink("name", "url")
        cbuildbot_alerts.PrintBuildbotStepText("text")
        cbuildbot_alerts.PrintBuildbotStepWarnings()
        cbuildbot_alerts.PrintBuildbotStepFailure()
        cbuildbot_alerts.PrintBuildbotStepName("name")
        cbuildbot_alerts.PrintKitchenSetBuildProperty("name", "value")

        captured = self.capfd.readouterr()
        assert "@@@STEP_LINK@name@url@@@" in captured.err
        assert "@@@STEP_TEXT@text@@@" in captured.err
        assert "@@@STEP_WARNINGS@@@" in captured.err
        assert "@@@STEP_FAILURE@@@" in captured.err
        assert "@@@BUILD_STEP@name@@@" in captured.err
        assert '@@@SET_BUILD_PROPERTY@name@"value"@@@' in captured.err
