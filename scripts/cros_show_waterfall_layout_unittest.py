# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for cros_show_waterfall_layout."""

import os

import pytest

from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.scripts import cros_show_waterfall_layout


# pylint: disable=protected-access


class DumpTest(cros_test_lib.TestCase):
    """Test the dumping functionality of cros_show_waterfall_layout."""

    def setUp(self) -> None:
        bin_name = os.path.basename(__file__).rstrip("_unittest.py")
        self.bin_path = constants.CHROMITE_BIN_DIR / bin_name

    @pytest.mark.usefixtures("legacy_capture_output")
    def testTextDump(self) -> None:
        """Make sure text dumping is capable of being produced."""
        cros_show_waterfall_layout.main([])
        captured = self.capfd.readouterr()
        assert captured.out
        assert not captured.err
