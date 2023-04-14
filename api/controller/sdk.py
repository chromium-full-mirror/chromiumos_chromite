# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""SDK chroot operations."""

import os
from typing import Dict, Union

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import cros_build_lib
from chromite.lib import path_util
from chromite.service import sdk


def _ChrootVersionResponse(_input_proto, output_proto, _config):
    """Add a fake chroot version to a successful response."""
    output_proto.version.version = 168


def _BinhostCLs(_input_proto, output_proto, _config):
    """Add fake CL identifiers to a successful response."""
    output_proto.cls = [
        "fakecl:1",
        "fakecl:2",
    ]


def _BuildSdkTarballResponse(_input_proto, output_proto, _config):
    """Populate a fake BuildSdkTarballResponse."""
    output_proto.sdk_tarball_path.path = "/fake/sdk/tarball.tar.gz"
    output_proto.sdk_tarball_path.location = common_pb2.Path.OUTSIDE


@faux.success(_BuildSdkTarballResponse)
@validate.require("chroot")
@validate.validation_complete
def BuildSdkTarball(
    input_proto: "BuildSdkTarballRequest",
    output_proto: "BuildSdkTarballResponse",
    _config: "api_config.ApiConfig",
) -> None:
    chroot = controller_util.ParseChroot(input_proto.chroot)
    output_proto.sdk_tarball_path.path = str(sdk.BuildSdkTarball(chroot))
    output_proto.sdk_tarball_path.location = common_pb2.Path.OUTSIDE


def _CreateManifestFromSdkResponse(_input_proto, output_proto, _config):
    """Populate a fake CreateManifestFromSdkResponse."""
    output_proto.manifest_path.path = "/fake/sdk/tarball.tar.gz.Manifest"
    output_proto.manifest_path.location = common_pb2.Path.Location.INSIDE


@faux.success(_CreateManifestFromSdkResponse)
@validate.require("chroot")
@validate.require("sdk_path")
@validate.require("dest_dir")
@validate.validation_complete
def CreateManifestFromSdk(
    input_proto: "CreateManifestFromSdkRequest",
    output_proto: "CreateManifestFromSdkResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Create a manifest file showing the ebuilds in an SDK."""

    def _assert_path_is_absolute(path: str, name: str):
        """Raise an exception if the given path is not absolute."""
        if not os.path.isabs(path):
            cros_build_lib.Die(f"The {name} must be absolute; got {path}")

    _assert_path_is_absolute(input_proto.chroot.path, "chroot path")
    _assert_path_is_absolute(input_proto.sdk_path.path, "SDK path")
    _assert_path_is_absolute(input_proto.dest_dir.path, "destination directory")

    sdk_path = path_util.ProtoPathToPathlibPath(
        input_proto.sdk_path, input_proto.chroot
    )
    dest_dir = path_util.ProtoPathToPathlibPath(
        input_proto.dest_dir, input_proto.chroot
    )

    manifest_path = sdk.CreateManifestFromSdk(sdk_path, dest_dir)
    output_proto.manifest_path.path = str(manifest_path)
    output_proto.manifest_path.location = common_pb2.Path.Location.OUTSIDE


@faux.success(_ChrootVersionResponse)
@faux.empty_error
def Create(
    input_proto: "CreateRequest",
    output_proto: "CreateResponse",
    config: "api_config.ApiConfig",
) -> Union[int, None]:
    """Chroot creation, includes support for replacing an existing chroot.

    Args:
        input_proto: The input proto.
        output_proto: The output proto.
        config: The API call config.

    Returns:
        An error code, None otherwise.
    """
    replace = not input_proto.flags.no_replace
    bootstrap = input_proto.flags.bootstrap
    use_image = not input_proto.flags.no_use_image

    chroot_path = input_proto.chroot.path
    cache_dir = input_proto.chroot.cache_dir
    sdk_version = input_proto.sdk_version
    skip_chroot_upgrade = input_proto.skip_chroot_upgrade

    if chroot_path and not os.path.isabs(chroot_path):
        cros_build_lib.Die("The chroot path must be absolute.")

    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    args = sdk.CreateArguments(
        replace=replace,
        bootstrap=bootstrap,
        use_image=use_image,
        cache_dir=cache_dir,
        chroot_path=chroot_path,
        sdk_version=sdk_version,
        skip_chroot_upgrade=skip_chroot_upgrade,
    )

    version = sdk.Create(args)

    if version:
        output_proto.version.version = version
    else:
        # This should be very rare, if ever used, but worth noting.
        cros_build_lib.Die(
            "No chroot version could be found. There was likely an"
            "error creating the chroot that was not detected."
        )


@faux.success(_ChrootVersionResponse)
@faux.empty_error
@validate.require_each("toolchain_targets", ["name"])
@validate.validation_complete
def Update(
    input_proto: "UpdateRequest",
    output_proto: "UpdateResponse",
    _config: "api_config.ApiConfig",
):
    """Update the chroot.

    Args:
        input_proto: The input proto.
        output_proto: The output proto.
        _config: The API call config.
    """
    build_source = input_proto.flags.build_source
    targets = [target.name for target in input_proto.toolchain_targets]
    toolchain_changed = input_proto.flags.toolchain_changed

    args = sdk.UpdateArguments(
        build_source=build_source,
        toolchain_targets=targets,
        toolchain_changed=toolchain_changed,
    )

    version = sdk.Update(args)

    if version:
        output_proto.version.version = version
    else:
        # This should be very rare, if ever used, but worth noting.
        cros_build_lib.Die(
            "No chroot version could be found. There was likely an"
            "error creating the chroot that was not detected."
        )


@faux.all_empty
@validate.require("chroot")
@validate.require("binhost_gs_bucket")
@validate.validation_complete
def Uprev(input_proto, output_proto, _config):
    """Update the SDK version and prebuilt files to point to the latest SDK."""
    target_version = input_proto.version or sdk.GetLatestVersion()
    modified_files = sdk.UprevSdkAndPrebuilts(
        controller_util.ParseChroot(input_proto.chroot),
        binhost_gs_bucket=input_proto.binhost_gs_bucket,
        version=target_version,
    )
    for modified_file in modified_files:
        output_proto.modified_files.add(
            common_pb2.Path(
                path=str(modified_file),
                location=common_pb2.Path.OUTSIDE,
            )
        )
    output_proto.version = target_version


@faux.all_empty
@validate.validation_complete
def Delete(input_proto, _output_proto, _config):
    """Delete a chroot."""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    sdk.Delete(chroot, force=True)


@faux.all_empty
@validate.validation_complete
def Unmount(input_proto, _output_proto, _config):
    """Unmount a chroot"""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    sdk.Unmount(chroot)


@faux.all_empty
@validate.require("path.path")
@validate.validation_complete
def UnmountPath(input_proto, _output_proto, _config):
    """Unmount a path"""
    sdk.UnmountPath(input_proto.path.path)


@faux.all_empty
@validate.validation_complete
def Clean(input_proto, _output_proto, _config):
    """Clean unneeded files from a chroot."""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    sdk.Clean(chroot, safe=True, sysroots=True)


@faux.all_empty
@validate.validation_complete
def CreateSnapshot(input_proto, output_proto, _config):
    """Create a chroot snapshot and return a corresponding opaque key."""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    token = sdk.CreateSnapshot(chroot, replace_if_needed=True)
    output_proto.snapshot_token.value = token


@faux.all_empty
@validate.validation_complete
def RestoreSnapshot(input_proto, _output_proto, _config):
    """Restore a chroot snapshot from a snapshot key."""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    token = input_proto.snapshot_token.value
    sdk.RestoreSnapshot(token, chroot)


@faux.all_empty
@validate.validation_complete
def BuildPrebuilts(input_proto, _output_proto, _config):
    """Build the binary packages that comprise the Chromium OS SDK."""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    sdk.BuildPrebuilts(chroot, board=input_proto.build_target.name)


@faux.success(_BinhostCLs)
@faux.empty_error
@validate.require(
    "prepend_version", "version", "upload_location", "sdk_tarball_template"
)
@validate.validation_complete
def CreateBinhostCLs(
    input_proto: "CreateBinhostCLsRequest",
    output_proto: "CreateBinhostCLsResponse",
    _config: "api_config.ApiConfig",
) -> None:
    """Create CLs to update the binhost to point at uploaded prebuilts."""
    output_proto.cls.extend(
        sdk.CreateBinhostCLs(
            input_proto.prepend_version,
            input_proto.version,
            input_proto.upload_location,
            input_proto.sdk_tarball_template,
        )
    )


@faux.all_empty
@validate.require("prepend_version", "version", "upload_location")
@validate.validation_complete
def UploadPrebuiltPackages(input_proto, _output_proto, _config):
    """Upload prebuilt packages."""
    sdk.UploadPrebuiltPackages(
        controller_util.ParseChroot(input_proto.chroot),
        input_proto.prepend_version,
        input_proto.version,
        input_proto.upload_location,
    )


@faux.all_empty
@validate.require("chroot")
@validate.validation_complete
def BuildSdkToolchain(input_proto, output_proto, _config):
    """Build cross-compiler packages for the SDK."""
    chroot = controller_util.ParseChroot(input_proto.chroot)
    extra_env: Dict[str, str] = {}
    if input_proto.use_flags:
        extra_env["USE"] = " ".join(use.flag for use in input_proto.use_flags)
    generated_files = sdk.BuildSdkToolchain(chroot, extra_env=extra_env)
    output_proto.generated_files.extend(generated_files)
