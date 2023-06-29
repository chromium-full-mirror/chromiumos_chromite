# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import subprocess
from chromite.contrib.sdk_server.grpc_server import client
from chromite.contrib.sdk_server.grpc_server import sdk_server_defs_grpc
from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2
from chromite.contrib.sdk_server.grpc_server import server

from chromite.contrib.sdk_server.grpc_server.chromite.api import image_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sdk_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sysroot_pb2
from chromite.contrib.sdk_server.grpc_server.chromiumos import common_pb2
import pytest
import types
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    TYPE_CHECKING,
    Union,
    Generator
)



CHROOT = sdk_server_defs_grpc.SdkChroot()
def test_workon_info():
    
    target = common_pb2.BuildTarget(name="betty")
    target_package = common_pb2.PackageInfo(package_name="sys-apps/frecon")
    request = sdk_server_pb2.WorkonInfoRequest(
        package_info=target_package, build_target=target
    )

    response = CHROOT.cros_workon_info(request, None)
    assert isinstance(response, sdk_server_pb2.WorkonInfoResponse)

def test_workon_list():
    target = common_pb2.BuildTarget(name="betty")
    request = sdk_server_pb2.WorkonListRequest(build_target=target)
    response = CHROOT.cros_workon_list(request, None)
    assert isinstance(response, sdk_server_pb2.WorkonListResponse)

def test_workon_start():
    target = common_pb2.BuildTarget(name="betty")
    target_package = common_pb2.PackageInfo(package_name="sys-apps/frecon")
    request = sdk_server_pb2.WorkonStartRequest(
        package_info=target_package, build_target=target
    )
    response = CHROOT.cros_workon_start(request, None)
    assert isinstance(response, sdk_server_pb2.WorkonStartResponse)

def test_workon_stop():
    target = common_pb2.BuildTarget(name="betty")
    target_package = common_pb2.PackageInfo(package_name="sys-apps/frecon")
    request = sdk_server_pb2.WorkonStopRequest(
        package_info=target_package, build_target=target
    )
    response = CHROOT.cros_workon_stop(request, None)
    assert isinstance(response, sdk_server_pb2.WorkonStopResponse)

def test_chroot_path():
    request = sdk_server_pb2.ChrootPathRequest()
    response = CHROOT.chroot_path(request, None)
    assert isinstance(response, sdk_server_pb2.ChrootPathResponse)

def test_all_packages():
    target = common_pb2.BuildTarget(name="betty")
    request = sdk_server_pb2.AllPackagesRequest(build_target=target)
    response = CHROOT.all_packages(request, None)
    assert isinstance(response, sdk_server_pb2.AllPackagesResponse)

def test_repo_status():
    request = sdk_server_pb2.RepoStatusRequest()
    response = CHROOT.repo_status(request, None)
    assert isinstance(response, sdk_server_pb2.RepoStatusResponse)

def test_update_chroot():
    request = sdk_server_pb2.UpdateChrootRequest()
    for response in CHROOT.update_chroot(request, None):
        assert (isinstance(response, sdk_server_pb2.UpdateChrootResponse))

def create_sdk(self):
    request = sdk_server_pb2.CreateSdkRequest()
    internal_req = sdk_pb2.CreateRequest()
    internal_req.flags.no_replace = True
    request.request.CopyFrom(internal_req)
    for response in CHROOT.create_sdk(request, None):
        assert isinstance(response, sdk_server_pb2.CreateSdkResponse)

    # def replace_sdk(self):
    #     response = client.replace_sdk()
    #     assert isinstance(response, sdk_server_pb2.ReplaceSdkResponse)

    # def delete_sdk(self):
    #     response = client.delete_sdk()
    #     assert isinstance(response, sdk_server_pb2.DeleteSdkResponse)

def test_build_packages():
    request = sdk_server_pb2.BuildPackagesRequest()

    create_internal_req = sysroot_pb2.SysrootCreateRequest()
    request.create_req.CopyFrom(create_internal_req)

    toolchain_internal_req = sysroot_pb2.InstallToolchainRequest()
    request.toolchain_req.CopyFrom(toolchain_internal_req)

    packages_internal_req = sysroot_pb2.InstallPackagesRequest()
    request.packages_req.CopyFrom(packages_internal_req)

    for response in CHROOT.build_packages(request, None):
        assert isinstance(response, sdk_server_pb2.BuildPackagesResponse)

def test_build_image():
    request = sdk_server_pb2.BuildImageRequest()
    internal_req = image_pb2.CreateImageRequest()
    request.request.CopyFrom(internal_req)

    for response in CHROOT.build_image(request, None):
        assert isinstance(response, sdk_server_pb2.BuildImageResponse)

