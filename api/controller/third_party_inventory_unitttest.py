# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for third-party inventory controller."""

import os

from chromite.api import api_config
from chromite.api.controller import third_party_inventory
from chromite.api.gen.chromite.api import sysroot_pb2
from chromite.api.gen.chromite.api import third_party_inventory_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.service import (
    third_party_inventory as third_party_inventory_service,
)


class ThirdPartyInventoryTest(
    cros_test_lib.MockTempDirTestCase,
    cros_test_lib.RunCommandTestCase,
    api_config.ApiConfigMixin,
):
    """Test for ThirdPartyInventory controller."""

    def setUp(self):
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=True)
        self.board = "board"

        self.response = (
            third_party_inventory_pb2.CollectPackageMetadataResponse()
        )
        self.request = third_party_inventory_pb2.CollectPackageMetadataRequest(
            chroot=common_pb2.Chroot(
                path=os.path.join(self.tempdir, "chroot"),
            ),
            sysroot=sysroot_pb2.Sysroot(
                build_target=common_pb2.BuildTarget(name=self.board),
            ),
        )

    def testCollect(self):
        fake_output = [
            '{"name": "pkg1"}',
            '{"name": "pkg2"}',
        ]
        self.PatchObject(
            third_party_inventory_service,
            "collect_inventory",
            return_value=fake_output,
        )

        third_party_inventory.CollectPackageMetadata(
            self.request, self.response, self.api_config
        )

        assert self.response.success
        assert len(self.response.metadata_protojson) == 2

    def testCollectFailure(self):
        self.PatchObject(
            third_party_inventory_service,
            "collect_inventory",
            side_effect=Exception("Collection failure"),
        )

        with self.assertRaises(Exception):
            third_party_inventory.CollectPackageMetadata(
                self.request, self.response, self.api_config
            )

        assert not self.response.success
        assert not self.response.metadata_protojson
