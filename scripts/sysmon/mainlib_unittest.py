# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for git_metrics."""

from unittest import mock

from chromite.lib import cros_test_lib
from chromite.scripts.sysmon import mainlib


# pylint: disable=protected-access


class TestTimedCallback(cros_test_lib.TestCase):
    """Tests for _TimedCallback."""

    def setUp(self) -> None:
        patcher = mock.patch("time.time", autospec=True)
        self.time = patcher.start()
        self.addCleanup(patcher.stop)

    def test_initial_call_should_callback(self) -> None:
        """Test that initial call goes through."""
        cb = mock.Mock([])

        self.time.return_value = 0
        obj = mainlib._TimedCallback(cb, 10)

        obj()
        cb.assert_called_once()

    def test_call_within_interval_should_not_callback(self) -> None:
        """Test that call too soon does not callback."""
        cb = mock.Mock([])

        self.time.return_value = 0
        obj = mainlib._TimedCallback(cb, 10)

        obj()
        cb.assert_called_once()

        cb.reset_mock()
        obj()
        cb.assert_not_called()

    def test_call_after_interval_should_callback(self) -> None:
        """Test that later call does callback."""
        cb = mock.Mock([])

        self.time.return_value = 0
        obj = mainlib._TimedCallback(cb, 10)

        obj()
        cb.assert_called_once()

        self.time.return_value = 10
        cb.reset_mock()
        obj()
        cb.assert_called_once()
