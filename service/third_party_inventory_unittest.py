# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the third_party_inventory service."""

import json

from chromite.third_party.google.protobuf import json_format
import pytest

from chromite.api.gen.chromiumos.build.api import third_party_inventory_pb2
from chromite.lib import build_target_lib
from chromite.lib import chromeos_version
from chromite.lib import cros_test_lib
from chromite.lib import sysroot_lib
from chromite.lib import unittest_lib
from chromite.service import third_party_inventory


# pylint: disable=protected-access


@pytest.mark.usefixtures("as_root_user")
class ThirdPartyInventoryTest(cros_test_lib.MockTempDirTestCase):
    """Tests for third_party_inventory.py"""

    def setUp(self):
        self.board = "board"
        self.sysroot_path = self.tempdir / "build" / self.board
        self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)

        self.sysroot.WriteConfig("BOARD_USE=foo")
        unittest_lib.create_stub_make_conf(self.sysroot_path)

        self.PatchObject(
            build_target_lib,
            "get_default_sysroot_path",
            return_value=self.sysroot_path,
        )

        self.PatchObject(
            chromeos_version.VersionInfo,
            "from_repo",
            return_value=chromeos_version.VersionInfo(
                version_string="12345.0.0", chrome_branch="136"
            ),
        )

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
        assert pkgs[0].portage_repository == "portage-stable"
        assert pkgs[0].description == "Test package"
        assert len(pkgs[0].homepages) == 2

    def testCollectOutputIntoJSON(self):
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
                    D(
                        "test-data/pkg2-2.0_p2-r2",
                        (
                            F("pkg2-2.0_p2-r2.ebuild", ""),
                            F("DESCRIPTION", "Test package 2"),
                            F(
                                "HOMEPAGE",
                                "http://example.com\nhttps://example.com",
                            ),
                            F("SIZE", "2048"),
                            F("repository", "chromiumos-overlay"),
                            F("EAPI", "7"),
                        ),
                    ),
                ),
            ),
        )

        cros_test_lib.CreateOnDiskHierarchy(self.sysroot_path, fs_layout)
        out_json_strs = third_party_inventory.collect_inventory(self.board)

        assert isinstance(out_json_strs, list)

        out_pkgs = []
        for json_str in out_json_strs:
            # Check the ProtoJSON is serialized into a single line.
            assert isinstance(json_str, str)
            assert "\n" not in json_str

            # Check board and os_ver are filled correctly.
            pkg = third_party_inventory_pb2.PackageMetadata()
            json_format.Parse(json_str, pkg)
            out_pkgs.append(pkg)
            assert pkg.board == self.board
            assert pkg.os_ver.milestone == 136
            assert pkg.os_ver.build == 12345
            assert pkg.os_ver.branch == 0
            assert pkg.os_ver.patch == 0

            # Check numerical 0 isn't omitted in the serialized JSON, because
            # protobuf omits the entire field if its value is the default
            # value of the field type (e.g. 0 for integer fields).
            out_json = json.loads(out_json_strs[0])
            assert out_json["os_ver"]["branch"] == 0

        assert len(out_pkgs) == 2
        assert {pkg.name for pkg in out_pkgs} == {"pkg1", "pkg2"}
