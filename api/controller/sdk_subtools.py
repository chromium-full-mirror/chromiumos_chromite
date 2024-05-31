# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SDK Subtools builder Controller.

Build API endpoint for converting protos to/from chromite.service.sdk_subtools.
"""

from pathlib import Path
from typing import Optional

from chromite.api import api_config
from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import sdk_subtools_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_target_lib
from chromite.lib import cros_build_lib
from chromite.lib import sysroot_lib
from chromite.service import sdk_subtools


@faux.empty_success
@validate.validation_complete
def BuildSdkSubtools(
    request: sdk_subtools_pb2.BuildSdkSubtoolsRequest,
    response: sdk_subtools_pb2.BuildSdkSubtoolsResponse,
    config: api_config.ApiConfig,
) -> Optional[int]:
    """Setup, and update packages in an SDK, then bundle subtools for upload."""
    build_target = build_target_lib.BuildTarget(
        # Note `request.chroot`` is not passed to `build_root` here:
        # api.router.py clears the `chroot` field when entering the chroot, so
        # it should always be empty when this endpoint is invoked.
        name="amd64-subtools-host",
        build_root="/",
    )
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    sdk_subtools.setup_base_sdk(build_target, setup_chroot=True, sudo=True)

    if request.packages:
        packages = [
            controller_util.deserialize_package_info(x).atom
            for x in request.packages
        ]
    else:
        # TODO: Drop the default once we always have a value passed.
        packages = ["virtual/target-sdk-subtools"]

    try:
        sdk_subtools.update_packages(packages)
    except sysroot_lib.PackageInstallError as e:
        if not e.failed_packages:
            # No packages to report, so just exit with an error code.
            return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY

        host_sysroot = sysroot_lib.Sysroot("/")
        controller_util.retrieve_package_log_paths(
            e.failed_packages, response, host_sysroot
        )

        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE

    (bundles, _) = sdk_subtools.bundle_and_prepare_upload(
        upload_filter=[x.name for x in request.upload_filter],
        private_only=request.private_only,
    )
    response.bundle_paths.extend(
        common_pb2.Path(path=str(b), location=common_pb2.Path.INSIDE)
        for b in bundles
    )
    return None


@faux.empty_success
@validate.validation_complete
def UploadSdkSubtools(
    request: sdk_subtools_pb2.UploadSdkSubtoolsRequest,
    response: sdk_subtools_pb2.UploadSdkSubtoolsResponse,
    config: api_config.ApiConfig,
) -> Optional[int]:
    """Uploads a list of bundled subtools."""
    if any(p.location != common_pb2.Path.OUTSIDE for p in request.bundle_paths):
        cros_build_lib.Die(
            "UploadSdkSubtools requires outside-chroot bundle paths."
        )

    bundles = [Path(path.path) for path in request.bundle_paths]
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    result = sdk_subtools.upload_prepared_bundles(
        request.use_production, bundles
    )
    unchanged_count = len(bundles) - len(result.uploaded_subtool_names)
    if result.uploaded_instances_markdown:
        summary = step_text = "Uploaded: "
        summary += ", ".join(result.uploaded_instances_markdown)
        summary += f" ({unchanged_count} bundled but unchanged)."
        step_text += ", ".join(result.uploaded_subtool_names)
    else:
        summary = f"{unchanged_count} tools bundled. No interesting changes."
        step_text = summary

    response.step_text = step_text
    response.summary_markdown = summary
    return None
