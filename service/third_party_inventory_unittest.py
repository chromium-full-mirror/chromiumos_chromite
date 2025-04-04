# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the third_party_inventory service."""

import pytest

from chromite.lib import cros_test_lib
from chromite.lib import sysroot_lib
from chromite.lib import unittest_lib
from chromite.service import third_party_inventory


# pylint: disable=protected-access


@pytest.mark.usefixtures("as_root_user")
class ThirdPartyInventoryTest(cros_test_lib.TempDirTestCase):
    """Tests for third_party_inventory.py"""

    def setUp(self):
        self.board = "board"
        self.sysroot_path = self.tempdir / "build" / self.board
        self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)

        self.sysroot.WriteConfig("BOARD_USE=foo")
        unittest_lib.create_stub_make_conf(self.sysroot_path)

    def testCollectInSysroot(self):
        D = cros_test_lib.Directory
        F = cros_test_lib.File

        fs_layout = (
            D(
                "var/db/pkg",
                (
                    D(
                        "test-data/pkg1-1.0_p1-r1",
                        (
                            F("pkg1-1.0_p1-r1.ebuild", ""),
                            F("DESCRIPTION", "Test package"),
                            F(
                                "HOMEPAGE",
                                "http://example.com\nhttps://example.com",
                            ),
                            F("SIZE", "1024"),
                            F("repository", "portage-stable"),
                            F("EAPI", "7"),
                        ),
                    ),
                ),
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.sysroot_path, fs_layout)
        pkgs = third_party_inventory._collect_in_sysroot(self.sysroot_path)

        assert len(pkgs) == 1
        assert pkgs[0].name == "pkg1"
