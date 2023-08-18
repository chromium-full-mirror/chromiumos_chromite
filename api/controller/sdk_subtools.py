# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SDK Subtools builder Controller.

Build API endpoint for converting protos to/from chromite.service.sdk_subtools.
"""

from typing import Optional

from chromite.api import api_config
from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import sdk_subtools_pb2
from chromite.lib import build_target_lib
from chromite.lib import sysroot_lib
from chromite.service import sdk_subtools


@faux.empty_success
@validate.validation_complete
def BuildSdkSubtools(
    _input_proto: sdk_subtools_pb2.BuildSdkSubtoolsRequest,
    output_proto: sdk_subtools_pb2.BuildSdkSubtoolsResponse,
    config: api_config.ApiConfig,
) -> Optional[int]:
    """Setup, and update packages in an SDK, then bundle and export subtools."""
    build_target = build_target_lib.BuildTarget(
        # Note `input_proto.chroot`` is not passed to `build_root` here:
        # api.router.py clears the `chroot` field when entering the chroot, so
        # it should always be empty when this endpoint is invoked.
        name="amd64-subtools-host",
        build_root="/",
    )
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    sdk_subtools.setup_base_sdk(build_target, setup_chroot=True, sudo=True)

    try:
        # Use shellcheck as a placeholder for testing. Eventually this will be
        # a virtual package target.
        sdk_subtools.update_packages(["dev-util/shellcheck"])
    except sysroot_lib.PackageInstallError as e:
        if not e.failed_packages:
            # No packages to report, so just exit with an error code.
            return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY

        host_sysroot = sysroot_lib.Sysroot("/")
        controller_util.retrieve_package_log_paths(
            e.failed_packages, output_proto, host_sysroot
        )

        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE

    sdk_subtools.bundle_and_export()
    return None
