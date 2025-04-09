# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Third-Party Inventory Controller.

Handles the Build API endpoint for third-party software inventory.
"""

from chromite.api import faux
from chromite.api import validate
from chromite.api.gen.chromite.api import third_party_inventory_pb2
from chromite.lib import cros_build_lib
from chromite.service import third_party_inventory


CollectResult = third_party_inventory_pb2.CollectPackageMetadataResponse


def _collect_success(_request, response, _config):
    response.success = True
    response.output = ""


@faux.success(_collect_success)
@validate.require("sysroot.build_target.name")
@validate.require("chroot")
@validate.validation_complete
def CollectPackageMetadata(request, response, _config):
    cros_build_lib.AssertInsideChroot()

    out_jsons = third_party_inventory.collect_inventory(
        request.sysroot.build_target.name
    )

    # Sets response after `collect_inventory` finishes.
    #
    # If an exception was raised in `collect_inventory`, don't set
    # `response.success`.
    response.success = True
    response.metadata_protojson.extend(out_jsons)
