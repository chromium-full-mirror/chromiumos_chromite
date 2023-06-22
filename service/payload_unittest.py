# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Payload service tests."""

from chromite.api.gen.chromite.api import payload_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import cros_test_lib
from chromite.lib.paygen import gspaths
from chromite.lib.paygen import paygen_payload_lib
from chromite.service import payload


class PayloadServiceTest(cros_test_lib.MockTestCase):
    """Unsigned payload generation tests."""

    def setUp(self):
        """Set up a payload test with the Run method mocked."""
        self.PatchObject(
            paygen_payload_lib.PaygenPayload,
            "Run",
            return_value={1: ("/foo/path", None)},
        )

        # Common build defs.
        self.src_build = payload_pb2.Build(
            version="1.0.0",
            bucket="test",
            channel="test-channel",
            build_target=common_pb2.BuildTarget(name="cave"),
        )
        self.tgt_build = payload_pb2.Build(
            version="2.0.0",
            bucket="test",
            channel="test-channel",
            build_target=common_pb2.BuildTarget(name="cave"),
        )

    def testUnsigned(self):
        """Test the happy path on unsigned images."""

        # Image defs.
        src_image = payload_pb2.UnsignedImage(
            build=self.src_build, image_type="IMAGE_TYPE_BASE", milestone="R79"
        )
        tgt_image = payload_pb2.UnsignedImage(
            build=self.tgt_build, image_type="IMAGE_TYPE_BASE", milestone="R80"
        )

        payload_config = payload.PayloadConfig(
            tgt_image=tgt_image,
            src_image=src_image,
            dest_bucket="test",
            verify=True,
            upload=True,
        )

        payload_config.GeneratePayload()

    def testSigned(self):
        """Test the happy path on signed images."""

        # Image defs.
        src_image = payload_pb2.SignedImage(
            build=self.src_build, image_type="IMAGE_TYPE_BASE", key="cave-mp-v4"
        )
        tgt_image = payload_pb2.SignedImage(
            build=self.tgt_build, image_type="IMAGE_TYPE_BASE", key="cave-mp-v4"
        )

        payload_config = payload.PayloadConfig(
            tgt_image=tgt_image,
            src_image=src_image,
            dest_bucket="test",
            verify=True,
            upload=True,
        )

        self.assertEqual("cave-mp-v4", payload_config.payload.tgt_image.key)

        payload_config.GeneratePayload()

    def testFullUpdate(self):
        """Test the happy path on full updates."""

        # Image def.
        tgt_image = payload_pb2.UnsignedImage(
            build=self.tgt_build, image_type="IMAGE_TYPE_BASE", milestone="R80"
        )

        payload_config = payload.PayloadConfig(
            tgt_image=tgt_image,
            src_image=None,
            dest_bucket="test",
            verify=True,
            upload=True,
        )

        payload_config.GeneratePayload()

    def testSignedMiniOS(self):
        """Test the happy path on signed minios images."""

        # Image defs.
        src_image = payload_pb2.SignedImage(
            build=self.src_build, image_type="IMAGE_TYPE_BASE", key="cave-mp-v4"
        )
        tgt_image = payload_pb2.SignedImage(
            build=self.tgt_build, image_type="IMAGE_TYPE_BASE", key="cave-mp-v4"
        )

        payload_config = payload.PayloadConfig(
            tgt_image=tgt_image,
            src_image=src_image,
            dest_bucket="test",
            minios=True,
            verify=True,
            upload=True,
        )

        payload_config.GeneratePayload()
        self.assertTrue(gspaths.IsMiniOSImage(payload_config.payload.tgt_image))

    def testUnsignedMiniOS(self):
        """Test the happy path on unsigned minios images."""

        # Image defs.
        src_image = payload_pb2.UnsignedImage(
            build=self.src_build, image_type="IMAGE_TYPE_BASE", milestone="R79"
        )
        tgt_image = payload_pb2.UnsignedImage(
            build=self.tgt_build, image_type="IMAGE_TYPE_BASE", milestone="R80"
        )

        payload_config = payload.PayloadConfig(
            tgt_image=tgt_image,
            src_image=src_image,
            dest_bucket="test",
            minios=True,
            verify=True,
            upload=True,
        )

        payload_config.GeneratePayload()
        self.assertTrue(
            gspaths.IsUnsignedMiniOSImageArchive(
                payload_config.payload.tgt_image
            )
        )
