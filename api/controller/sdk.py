# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SDK chroot operations."""

import logging
import os
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING, Union

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import cros_build_lib
from chromite.lib import path_util
from chromite.lib import sysroot_lib
from chromite.service import sdk


if TYPE_CHECKING:
    from chromite.api import api_config
    from chromite.api.gen.chromite.api import sdk_pb2


def _ChrootVersionResponse(
    _request: Union["sdk_pb2.CreateRequest", "sdk_pb2.UpdateRequest"],
    response: Union["sdk_pb2.CreateResponse", "sdk_pb2.UpdateResponse"],
    _config: "api_config.ApiConfig",
) -> None:
    """Add a fake chroot version to a successful response."""
    response.version.version = 168


def _BinhostCLs(
    _request: "sdk_pb2.CreateBinhostCLsRequest",
    response: "sdk_pb2.CreateBinhostCLsResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Add fake CL identifiers to a successful response."""
    response.cls = [
        "fakecl:1",
        "fakecl:2",
    ]


def _BuildSdkTarballResponse(
    _request: "sdk_pb2.BuildSdkTarballRequest",
    response: "sdk_pb2.BuildSdkTarballResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Populate a fake BuildSdkTarballResponse."""
    response.sdk_tarball_path.path = "/fake/sdk/tarball.tar.gz"
    response.sdk_tarball_path.location = common_pb2.Path.OUTSIDE


@faux.success(_BuildSdkTarballResponse)
@validate.require("chroot")
@validate.require("sdk_version")
@validate.validation_complete
def BuildSdkTarball(
    request: "sdk_pb2.BuildSdkTarballRequest",
    response: "sdk_pb2.BuildSdkTarballResponse",
    _config: "api_config.ApiConfig",
) -> None:
    chroot = controller_util.ParseChroot(request.chroot)
    tarball_path = sdk.BuildSdkTarball(
        chroot=chroot,
        sdk_version=request.sdk_version,
    )
    response.sdk_tarball_path.path = str(tarball_path)
    response.sdk_tarball_path.location = common_pb2.Path.OUTSIDE


def _CreateManifestFromSdkResponse(
    _request: "sdk_pb2.BuildSdkTarballRequest",
    response: "sdk_pb2.BuildSdkTarballResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Populate a fake CreateManifestFromSdkResponse."""
    response.manifest_path.path = "/fake/sdk/tarball.tar.gz.Manifest"
    response.manifest_path.location = common_pb2.Path.INSIDE


@faux.success(_CreateManifestFromSdkResponse)
@validate.require("chroot")
@validate.require("sdk_path")
@validate.require("dest_dir")
@validate.validation_complete
def CreateManifestFromSdk(
    request: "sdk_pb2.CreateManifestFromSdkRequest",
    response: "sdk_pb2.CreateManifestFromSdkResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Create a manifest file showing the ebuilds in an SDK."""

    def _assert_path_is_absolute(path: str, name: str) -> None:
        """Raise an exception if the given path is not absolute."""
        if not os.path.isabs(path):
            cros_build_lib.Die(f"The {name} must be absolute; got {path}")

    _assert_path_is_absolute(request.chroot.path, "chroot path")
    _assert_path_is_absolute(request.sdk_path.path, "SDK path")
    _assert_path_is_absolute(request.dest_dir.path, "destination directory")

    sdk_path = controller_util.pb2_path_to_pathlib_path(
        request.sdk_path, request.chroot
    )
    dest_dir = controller_util.pb2_path_to_pathlib_path(
        request.dest_dir, request.chroot
    )

    manifest_path = sdk.CreateManifestFromSdk(sdk_path, dest_dir)
    response.manifest_path.path = str(manifest_path)
    response.manifest_path.location = common_pb2.Path.OUTSIDE


@faux.success(_ChrootVersionResponse)
@faux.empty_error
@validate.require("skip_chroot_upgrade")
@validate.validation_complete
def Create(
    request: "sdk_pb2.CreateRequest",
    response: "sdk_pb2.CreateResponse",
    config: "api_config.ApiConfig",
) -> Optional[int]:
    """Chroot creation, includes support for replacing an existing chroot.

    Args:
        request: The input proto.
        response: The output proto.
        config: The API call config.

    Returns:
        An error code, None otherwise.
    """
    no_delete_out_dir = request.flags.no_delete_out_dir
    bootstrap = request.flags.bootstrap
    chroot = controller_util.ParseChroot(request.chroot)

    sdk_version = request.sdk_version
    ccache_disable = request.ccache_disable

    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    args = sdk.CreateArguments(
        bootstrap=bootstrap,
        chroot=chroot,
        sdk_version=sdk_version,
        # Non-force is supposed to prevent human users from making mistakes when
        # replacing or deleting the chroot. Since the build API is usually not
        # used by humans, it should be safe to assume force.
        force=True,
        ccache_disable=ccache_disable,
        no_delete_out_dir=no_delete_out_dir,
    )

    try:
        version = sdk.Create(args)
    except sdk.SdkCreateError as e:
        cros_build_lib.Die(e)

    if version:
        response.version.version = version
    else:
        # This should be very rare, if ever used, but worth noting.
        cros_build_lib.Die(
            "No chroot version could be found. There was likely an"
            "error creating the chroot that was not detected."
        )

    return None


@faux.success(_ChrootVersionResponse)
@faux.empty_error
@validate.require_each("toolchain_targets", ["name"])
@validate.validation_complete
def Update(
    request: "sdk_pb2.UpdateRequest",
    response: "sdk_pb2.UpdateResponse",
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Update the chroot.

    Args:
        request: The input proto.
        response: The output proto.
        _config: The API call config.

    Returns:
        An error code, None otherwise.
    """
    build_source = request.flags.build_source
    targets = [target.name for target in request.toolchain_targets]
    toolchain_changed = request.flags.toolchain_changed
    force_update = toolchain_changed or request.flags.force_update

    if not force_update:
        logging.info("SDK update skipped.")
        response.skipped = True
        return None

    logging.info("Updating SDK due to force_update = True")

    args = sdk.UpdateArguments(
        build_source=build_source,
        toolchain_targets=targets,
        toolchain_changed=toolchain_changed,
        use_snapshot_binhosts=request.use_snapshot_binhosts,
        log_installed_packages=True,
    )

    result = sdk.Update(args)
    if result.success:
        response.version.version = result.version
        return None
    elif result.failed_pkgs:
        sysroot = sysroot_lib.Sysroot("/")
        controller_util.retrieve_package_log_paths(
            result.failed_pkgs, response, sysroot
        )
        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
    else:
        return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY


@faux.all_empty
@validate.require("binhost_gs_bucket")
@validate.require("toolchain_tarball_template")
@validate.require("version")
@validate.validation_complete
def Uprev(
    request: "sdk_pb2.UprevRequest",
    response: "sdk_pb2.UprevResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Update SDK version file and prebuilt files to point to the latest SDK.

    Files will be changed locally, but not committed.
    """
    # The main uprev logic occurs in service/sdk.py.
    modified_files = sdk.uprev_sdk_and_prebuilts(
        request.version,
        request.toolchain_tarball_template,
        request.binhost_gs_bucket,
        sdk_gs_bucket=request.sdk_gs_bucket or None,
    )
    modified_files += sdk.uprev_toolchain_virtuals()

    # Populate the UprevResponse object with the modified files.
    for modified_file in modified_files:
        proto_path = response.modified_files.add()
        proto_path.path = str(modified_file)
        proto_path.location = common_pb2.Path.OUTSIDE
    response.version = request.version


@faux.all_empty
@validate.validation_complete
def Delete(
    request: "sdk_pb2.DeleteRequest",
    _response: "sdk_pb2.DeleteResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Delete a chroot."""
    chroot = controller_util.ParseChroot(request.chroot)
    sdk.Delete(chroot, force=True)


@faux.all_empty
@validate.validation_complete
def Unmount(
    _request: "sdk_pb2.UnmountRequest",
    _response: "sdk_pb2.UnmountResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Unmount a chroot"""
    # Deprecated. Do nothing.


@faux.all_empty
@validate.require("path.path")
@validate.validation_complete
def UnmountPath(
    request: "sdk_pb2.UnmountPathRequest",
    _response: "sdk_pb2.UnmountPathResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Unmount a path"""
    sdk.UnmountPath(request.path.path)


@faux.all_empty
@validate.validation_complete
def Clean(
    request: "sdk_pb2.CleanRequest",
    _response: "sdk_pb2.CleanResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Clean unneeded files from a chroot."""
    chroot = controller_util.ParseChroot(request.chroot)

    # Default (flagless) call sets 'safe' and 'sysroots'.
    if not (
        request.safe
        or request.images
        or request.sysroots
        or request.tmp
        or request.cache
        or request.logs
        or request.workdirs
        or request.incrementals
    ):
        sdk.Clean(chroot, safe=True, sysroots=True)
    else:
        sdk.Clean(
            chroot,
            safe=request.safe,
            images=request.images,
            sysroots=request.sysroots,
            tmp=request.tmp,
            cache=request.cache,
            logs=request.logs,
            workdirs=request.workdirs,
            incrementals=request.incrementals,
        )


@faux.all_empty
@validate.validation_complete
def BuildPrebuilts(
    request: "sdk_pb2.BuildPrebuiltsRequest",
    response: "sdk_pb2.BuildPrebuiltsResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Build the binary packages that comprise the Chromium OS SDK."""
    chroot = controller_util.ParseChroot(request.chroot)
    host_path, target_path = sdk.BuildPrebuilts(
        chroot,
        board=request.build_target.name,
    )
    # Convert paths to OUTSIDE, rather than using the ResultPath, to avoid
    # unnecessary copying of several-gigabyte directories, and because
    # ResultPath doesn't support returning multiple directories.
    chroot_path_resolver = path_util.ChrootPathResolver(
        chroot_path=Path(request.chroot.path),
        out_path=Path(request.chroot.out_path),
    )
    response.host_prebuilts_path.path = str(
        chroot_path_resolver.FromChroot(host_path),
    )
    response.host_prebuilts_path.location = common_pb2.Path.OUTSIDE
    response.target_prebuilts_path.path = str(
        chroot_path_resolver.FromChroot(target_path),
    )
    response.target_prebuilts_path.location = common_pb2.Path.OUTSIDE


@faux.success(_BinhostCLs)
@faux.empty_error
@validate.require(
    "prepend_version", "version", "upload_location", "sdk_tarball_template"
)
@validate.validation_complete
def CreateBinhostCLs(
    request: "sdk_pb2.CreateBinhostCLsRequest",
    response: "sdk_pb2.CreateBinhostCLsResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Create CLs to update the binhost to point at uploaded prebuilts."""
    response.cls.extend(
        sdk.CreateBinhostCLs(
            request.prepend_version,
            request.version,
            request.upload_location,
            request.sdk_tarball_template,
        )
    )


@faux.all_empty
@validate.require("prepend_version", "version", "upload_location")
@validate.validation_complete
def UploadPrebuiltPackages(
    request: "sdk_pb2.UploadPrebuiltPackagesRequest",
    _response: "sdk_pb2.UploadPrebuiltPackagesResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Upload prebuilt packages."""
    sdk.UploadPrebuiltPackages(
        controller_util.ParseChroot(request.chroot),
        request.prepend_version,
        request.version,
        request.upload_location,
    )


@faux.all_empty
@validate.validation_complete
def BuildSdkToolchain(
    request: "sdk_pb2.BuildSdkToolchainRequest",
    response: "sdk_pb2.BuildSdkToolchainResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Build cross-compiler packages for the SDK."""
    extra_env: Dict[str, str] = {}
    if request.use_flags:
        extra_env["USE"] = " ".join(use.flag for use in request.use_flags)
    generated_files = sdk.BuildSdkToolchain(extra_env=extra_env)
    response.generated_files.extend(generated_files)
