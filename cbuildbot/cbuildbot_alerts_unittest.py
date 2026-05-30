# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for cbuildbot_alerts."""

import pytest

from chromite.cbuildbot import cbuildbot_alerts
from chromite.lib import cros_test_lib


class CrosloggingTest(cros_test_lib.TestCase):
    """Test logging works as expected."""

    @pytest.mark.usefixtures("legacy_capture_output")
    def testPrintBuildbotFunctionsNoMarker(self) -> None:
        """PrintBuildbot* w/out markers should not be recognized by buildbot."""
        cbuildbot_alerts.PrintBuildbotStepText("text")
        cbuildbot_alerts.PrintBuildbotStepWarnings()

        captured = self.capfd.readouterr()
        assert "STEP_TEXT" in captured.err
        assert "STEP_WARNINGS" in captured.err
        assert "@@@" not in captured.out
        assert "@@@" not in captured.err
