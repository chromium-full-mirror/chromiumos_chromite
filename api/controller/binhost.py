# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Portage Binhost operations."""

import os
import shutil
from typing import TYPE_CHECKING
import urllib.parse

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import binhost_pb2
from chromite.lib import binpkg
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import sysroot_lib
from chromite.service import binhost
from chromite.utils import gs_urls_util


if TYPE_CHECKING:
    from chromite.api import api_config

_OVERLAY_TYPE_TO_NAME = {
    binhost_pb2.OVERLAYTYPE_PUBLIC: constants.PUBLIC_OVERLAYS,
    binhost_pb2.OVERLAYTYPE_PRIVATE: constants.PRIVATE_OVERLAYS,
    binhost_pb2.OVERLAYTYPE_BOTH: constants.BOTH_OVERLAYS,
    binhost_pb2.OVERLAYTYPE_NONE: None,
}

# Default maximum number of URIs to be stored in Binhost conf file.
_DEFAULT_BINHOST_MAX_URIS = 1


def _GetBinhostsResponse(_request, response, _config) -> None:
    """Add fake binhosts to a successful response."""
    new_binhost = response.binhosts.add()
    new_binhost.uri = (
        f"{constants.TRASH_BUCKET}/board/amd64-generic/"
        "paladin-R66-17.0.0-rc2/packages/"
    )
    new_binhost.package_index = "Packages"


@faux.success(_GetBinhostsResponse)
@faux.empty_error
@validate.require("build_target.name")
@validate.validation_complete
def GetBinhosts(request, response, _config) -> None:
    """Get a list of binhosts."""
    build_target = controller_util.ParseBuildTarget(request.build_target)

    binhosts = binhost.GetBinhosts(build_target)

    for current in binhosts:
        new_binhost = response.binhosts.add()
        new_binhost.uri = current
        new_binhost.package_index = "Packages"


def _GetPrivatePrebuiltAclArgsResponse(_request, response, _config) -> None:
    """Add fake acls to a successful response."""
    new_arg = response.args.add()
    new_arg.arg = "-g"
    new_arg.value = "group1:READ"


@faux.success(_GetPrivatePrebuiltAclArgsResponse)
@faux.empty_error
@validate.require("build_target.name")
@validate.validation_complete
def GetPrivatePrebuiltAclArgs(request, response, _config) -> None:
    """Get the ACL args from the files in the private overlays."""
    build_target = controller_util.ParseBuildTarget(request.build_target)

    try:
        args = binhost.GetPrebuiltAclArgs(build_target)
    except binhost.Error as e:
        cros_build_lib.Die(e)

    for arg, value in args:
        new_arg = response.args.add()
        new_arg.arg = arg
        new_arg.value = value


def _PrepareBinhostUploadsResponse(_request, response, _config) -> None:
    """Add fake binhost upload targets to a successful response."""
    response.uploads_dir = "/upload/directory"
    response.upload_targets.add().path = "upload_target"


@faux.success(_PrepareBinhostUploadsResponse)
@faux.empty_error
@validate.require("uri")
def PrepareBinhostUploads(
    request: binhost_pb2.PrepareBinhostUploadsRequest,
    response: binhost_pb2.PrepareBinhostUploadsResponse,
    config: "api_config.ApiConfig",
):
    """Return a list of files to upload to the binhost.

    See BinhostService documentation in api/proto/binhost.proto.

    Args:
        request: The input proto.
        response: The output proto.
        config: The API call config.
    """
    if request.sysroot.build_target.name:
        build_target_msg = request.sysroot.build_target
    else:
        build_target_msg = request.build_target
    sysroot_path = request.sysroot.path

    if not sysroot_path and not build_target_msg.name:
        cros_build_lib.Die("Sysroot.path is required.")

    build_target = controller_util.ParseBuildTarget(build_target_msg)
    chroot = controller_util.ParseChroot(request.chroot)

    if not sysroot_path:
        sysroot_path = build_target.root
    sysroot = sysroot_lib.Sysroot(sysroot_path)

    uri = request.uri
    # For now, we enforce that all input URIs are Google Storage buckets.
    if not gs_urls_util.PathIsGs(uri):
        raise ValueError("Upload URI %s must be Google Storage." % uri)

    package_index_paths = [f.path.path for f in request.package_index_files]

    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    parsed_uri = urllib.parse.urlparse(uri)
    upload_uri = gs_urls_util.GetGsURL(
        parsed_uri.netloc,
        for_gsutil=True,
    ).rstrip("/")
    upload_path = parsed_uri.path.lstrip("/")

    # Read all packages and update the index. The index must be uploaded to the
    # binhost for Portage to use it, so include it in upload_targets.
    uploads_dir = binhost.GetPrebuiltsRoot(chroot, sysroot, build_target)
    index_path = binhost.UpdatePackageIndex(
        uploads_dir, upload_uri, upload_path, sudo=True
    )
    upload_targets = binhost.GetPrebuiltsFiles(
        uploads_dir, package_index_paths=package_index_paths, sudo=True
    )
    assert index_path.startswith(
        uploads_dir
    ), "expected index_path to start with uploads_dir"
    upload_targets.append(index_path[len(uploads_dir) :])

    response.uploads_dir = uploads_dir
    for upload_target in upload_targets:
        response.upload_targets.add().path = upload_target.strip("/")


def _PrepareDevInstallBinhostUploadsResponse(
    _request, response, _config
) -> None:
    """Add fake binhost files to a successful response."""
    response.upload_targets.add().path = "app-arch/zip-3.0-r3.tbz2"
    response.upload_targets.add().path = "virtual/python-enum34-1.tbz2"
    response.upload_targets.add().path = "Packages"


@faux.success(_PrepareDevInstallBinhostUploadsResponse)
@faux.empty_error
@validate.require("uri", "sysroot.path")
@validate.exists("uploads_dir")
def PrepareDevInstallBinhostUploads(
    request: binhost_pb2.PrepareDevInstallBinhostUploadsRequest,
    response: binhost_pb2.PrepareDevInstallBinhostUploadsResponse,
    config: "api_config.ApiConfig",
):
    """Return a list of files to upload to the binhost"

    The files will also be copied to the uploads_dir.
    See BinhostService documentation in api/proto/binhost.proto.

    Args:
        request: The input proto.
        response: The output proto.
        config: The API call config.
    """
    sysroot_path = request.sysroot.path

    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = sysroot_lib.Sysroot(sysroot_path)

    uri = request.uri
    # For now, we enforce that all input URIs are Google Storage buckets.
    if not gs_urls_util.PathIsGs(uri):
        raise ValueError("Upload URI %s must be Google Storage." % uri)

    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    parsed_uri = urllib.parse.urlparse(uri)
    upload_uri = gs_urls_util.GetGsURL(
        parsed_uri.netloc, for_gsutil=True
    ).rstrip("/")
    upload_path = parsed_uri.path.lstrip("/")

    # Calculate the filename for the to-be-created Packages file, which will
    # contain only devinstall packages.
    devinstall_package_index_path = os.path.join(
        request.uploads_dir, "Packages"
    )
    upload_targets_list = binhost.ReadDevInstallFilesToCreatePackageIndex(
        chroot, sysroot, devinstall_package_index_path, upload_uri, upload_path
    )

    package_dir = chroot.full_path(sysroot.path, "packages")
    for upload_target in upload_targets_list:
        # Copy each package to target/category/package
        upload_target = upload_target.strip("/")
        category = upload_target.split(os.sep)[0]
        target_dir = os.path.join(request.uploads_dir, category)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)
        full_src_pkg_path = os.path.join(package_dir, upload_target)
        full_target_src_path = os.path.join(request.uploads_dir, upload_target)
        shutil.copyfile(full_src_pkg_path, full_target_src_path)
        response.upload_targets.add().path = upload_target
    response.upload_targets.add().path = "Packages"


def _PrepareChromeBinhostUploadsResponse(_request, response, _config) -> None:
    """Add fake binhost files to a successful response."""
    response.upload_targets.add().path = (
        "chromeos-base/chromeos-chrome-100-r1.tbz2"
    )
    response.upload_targets.add().path = "chromeos-base/chrome-icu-100-r1.tbz2"
    response.upload_targets.add().path = (
        "chromeos-base/chromeos-lacros-100-r1.tbz2"
    )
    response.upload_targets.add().path = "Packages"


@faux.success(_PrepareChromeBinhostUploadsResponse)
@faux.empty_error
@validate.require("uploads_dir", "uri", "sysroot.path")
@validate.validation_complete
def PrepareChromeBinhostUploads(
    request: binhost_pb2.PrepareChromeBinhostUploadsRequest,
    response: binhost_pb2.PrepareChromeBinhostUploadsResponse,
    config: "api_config.ApiConfig",
):
    """Return a list of Chrome files to upload to the binhost.

    The files will also be copied to the uploads_dir.
    See BinhostService documentation in api/proto/binhost.proto.

    Args:
        request: The input proto.
        response: The output proto.
        config: The API call config.
    """
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = sysroot_lib.Sysroot(request.sysroot.path)

    uri = request.uri
    # For now, we enforce that all input URIs are Google Storage buckets.
    if not gs_urls_util.PathIsGs(uri):
        raise ValueError("Upload URI %s must be Google Storage." % uri)
    parsed_uri = urllib.parse.urlparse(uri)
    gs_bucket = gs_urls_util.GetGsURL(
        parsed_uri.netloc, for_gsutil=True
    ).rstrip("/")
    upload_path = parsed_uri.path.lstrip("/")

    # Determine the filename for the to-be-created Packages file, which will
    # contain only Chrome packages.
    chrome_package_index_path = os.path.join(request.uploads_dir, "Packages")
    upload_targets_list = binhost.CreateChromePackageIndex(
        chroot, sysroot, chrome_package_index_path, gs_bucket, upload_path
    )

    package_dir = chroot.full_path(sysroot.path, "packages")
    for upload_target in upload_targets_list:
        # Copy each package to uploads_dir/category/package
        upload_target = upload_target.strip("/")
        category = upload_target.split("/")[0]
        target_dir = os.path.join(request.uploads_dir, category)
        if not os.path.exists(target_dir):
            osutils.SafeMakedirs(target_dir)
        full_src_pkg_path = os.path.join(package_dir, upload_target)
        full_target_src_path = os.path.join(request.uploads_dir, upload_target)
        shutil.copyfile(full_src_pkg_path, full_target_src_path)
        response.upload_targets.add().path = upload_target
    response.upload_targets.add().path = "Packages"


def _UpdatePackageIndexResponse(_request, _response, _config) -> None:
    """Set up a fake successful response."""


@faux.success(_UpdatePackageIndexResponse)
@faux.empty_error
@validate.require("package_index_file")
@validate.require_any("set_upload_location")
@validate.validation_complete
def UpdatePackageIndex(
    request: binhost_pb2.UpdatePackageIndexRequest,
    _response: binhost_pb2.UpdatePackageIndexResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Implementation for the BinhostService/UpdatePackageIndex endpoint."""
    # Load the index file.
    index_path = controller_util.pb2_path_to_pathlib_path(
        request.package_index_file,
        chroot=request.chroot,
    )
    pkgindex = binpkg.PackageIndex()
    pkgindex.ReadFilePath(index_path)

    # Set the upload location for all packages.
    if request.set_upload_location:
        if not request.uri:
            raise ValueError("set_upload_location is True, but no uri provided")
        parsed_uri = urllib.parse.urlparse(request.uri)
        pkgindex.SetUploadLocation(
            gs_urls_util.GetGsURL(parsed_uri.netloc, for_gsutil=True).rstrip(
                "/"
            ),
            parsed_uri.path.lstrip("/"),
        )

    # Write the updated index file back to its original location.
    pkgindex.WriteFile(index_path)


def _SetBinhostResponse(_request, response, _config) -> None:
    """Add fake binhost file to a successful response."""
    response.output_file = "/path/to/BINHOST.conf"


@faux.success(_SetBinhostResponse)
@faux.empty_error
@validate.require("build_target.name", "key", "uri")
@validate.validation_complete
def SetBinhost(
    request: binhost_pb2.SetBinhostRequest,
    response: binhost_pb2.SetBinhostResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Set the URI for a given binhost key and build target.

    See BinhostService documentation in api/proto/binhost.proto.

    Args:
        request: The input proto.
        response: The output proto.
        _config: The API call config.
    """
    target = request.build_target.name
    key = binhost_pb2.BinhostKey.Name(request.key)
    uri = request.uri
    private = request.private
    max_uris = request.max_uris or _DEFAULT_BINHOST_MAX_URIS

    response.output_file = binhost.SetBinhost(
        target, key, uri, private=private, max_uris=max_uris
    )


def _GetBinhostConfPathResponse(_request, response, _config) -> None:
    """Add fake binhost file to a successful response."""
    response.conf_path = "/path/to/BINHOST.conf"


@faux.success(_GetBinhostConfPathResponse)
@faux.empty_error
@validate.require("build_target.name", "key")
@validate.validation_complete
def GetBinhostConfPath(
    request: binhost_pb2.GetBinhostConfPathRequest,
    response: binhost_pb2.GetBinhostConfPathResponse,
    _config: "api_config.ApiConfig",
) -> None:
    target = request.build_target.name
    key = binhost_pb2.BinhostKey.Name(request.key)
    private = request.private
    response.conf_path = str(binhost.GetBinhostConfPath(target, key, private))


def _RegenBuildCacheResponse(_request, response, _config) -> None:
    """Add fake binhosts cache path to a successful response."""
    response.modified_overlays.add().path = "/path/to/BuildCache"


@faux.success(_RegenBuildCacheResponse)
@faux.empty_error
@validate.require("overlay_type")
@validate.is_in("overlay_type", _OVERLAY_TYPE_TO_NAME)
@validate.validation_complete
def RegenBuildCache(
    request: binhost_pb2.RegenBuildCacheRequest,
    response: binhost_pb2.RegenBuildCacheResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Regenerate the Build Cache for a build target.

    See BinhostService documentation in api/proto/binhost.proto.

    Args:
        request: The input proto.
        response: The output proto.
        _config: The API call config.
    """
    chroot = controller_util.ParseChroot(request.chroot)
    overlay_type = request.overlay_type
    overlays = binhost.RegenBuildCache(
        chroot, _OVERLAY_TYPE_TO_NAME[overlay_type]
    )

    for overlay in overlays:
        response.modified_overlays.add().path = overlay
