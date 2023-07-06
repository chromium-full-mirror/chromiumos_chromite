# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Definitions of sdk server client functions.

These functions send requests to the sdk server
"""
import asyncio
from collections import UserDict
import logging
from typing import AsyncGenerator, Awaitable, Generator, List, Optional, Union

from chromite.third_party.google.protobuf import json_format
import grpc

from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2
from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2_grpc
from chromite.contrib.sdk_server.grpc_server.chromite.api import image_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sdk_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sysroot_pb2
from chromite.contrib.sdk_server.grpc_server.chromiumos import common_pb2


async def cros_workon_info(
    request: sdk_server_pb2.WorkonInfoRequest,
) -> sdk_server_pb2.WorkonInfoResponse:
    """sends grpc request for cros workon info to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = await stub.cros_workon_info(request)
        return response


async def cros_workon_list(
    request: sdk_server_pb2.WorkonListRequest,
) -> sdk_server_pb2.WorkonListResponse:
    """sends grpc request for cros workon list to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = stub.cros_workon_list(request)
        return response


async def cros_workon_start(
    request: sdk_server_pb2.WorkonStartRequest,
) -> sdk_server_pb2.WorkonStartResponse:
    """sends grpc request for cros workon start to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = await stub.cros_workon_start(request)
        return response


async def cros_workon_stop(
    request: sdk_server_pb2.WorkonStopRequest,
) -> sdk_server_pb2.WorkonStopResponse:
    """sends grpc request for cros workon stop to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = await stub.cros_workon_stop(request)
        return response


async def chroot_path(
    request: sdk_server_pb2.ChrootPathRequest,
) -> sdk_server_pb2.ChrootPathResponse:
    """sends grpc request for the chroot path to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = await stub.chroot_path(request)
        return response


async def all_packages(
    request: sdk_server_pb2.AllPackagesRequest,
) -> sdk_server_pb2.AllPackagesResponse:
    """sends grpc request for cros workon --all list to sdk server."""
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = stub.all_packages(request)
        return response


async def repo_sync(
    request: sdk_server_pb2.RepoSyncRequest,
) -> sdk_server_pb2.RepoSyncResponse:
    """sends grpc request for repo sync to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = await stub.repo_sync(request)
        return response


async def repo_status(
    request: sdk_server_pb2.RepoStatusRequest,
) -> sdk_server_pb2.RepoStatusResponse:
    """sends grpc request for repo status to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = await stub.repo_status(request)
        return response


async def update_chroot(request: sdk_server_pb2.UpdateChrootRequest):
    """sends grpc request for update chroot to sdk server."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        finalResp = None
        async for response in stub.update_chroot(request):
            finalResp = response
            yield response

        yield finalResp


async def create_sdk(
    request: sdk_server_pb2.CreateSdkRequest,
) -> AsyncGenerator[sdk_server_pb2.CreateSdkResponse, None]:
    """sends grpc request to sdk server for BAPI create sdk endpoint."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        finalResp = None
        async for response in stub.create_sdk(request):
            finalResp = response
            yield response

        yield finalResp


async def replace_sdk(
    request: sdk_server_pb2.ReplaceSdkRequest,
) -> AsyncGenerator[sdk_server_pb2.ReplaceSdkResponse, None]:
    """sends grpc request to sdk server for BAPI update sdk endpoint.

    See: update sdk endpoint is the create sdk endpoint with no_replace = False
    """
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        internal_req = sdk_pb2.CreateRequest()
        request.request.CopyFrom(internal_req)

        finalResp = None
        async for response in stub.replace_sdk(request):
            finalResp = response
            yield response

        yield finalResp


async def delete_sdk(
    request: sdk_server_pb2.DeleteSdkRequest,
) -> AsyncGenerator[sdk_server_pb2.DeleteSdkResponse, None]:
    """sends grpc request to sdk server for BAPI delete sdk endpoint."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        finalResp = None
        async for response in stub.delete_sdk(request):
            finalResp = response
            yield response

        yield finalResp


async def build_packages(request: sdk_server_pb2.BuildPackagesRequest):
    """sends grpc request to sdk server for BAPI build packages.

    Calls the following endpoints:
        Sysroot create
        install toolcahin
        build packages
    """
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        finalResp = None
        async for response in stub.build_packages(request):
            finalResp = response
            yield response

        yield finalResp


async def build_image(
    request: sdk_server_pb2.BuildImageRequest,
) -> AsyncGenerator[sdk_server_pb2.BuildImageResponse, None]:
    """sends grpc request to sdk server for BAPI build image endpoint."""
    async with grpc.aio.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        internal_req = image_pb2.CreateImageRequest()
        request.request.CopyFrom(internal_req)

        finalResp = None
        async for response in stub.build_image(request):
            finalResp = response
            yield response

        yield finalResp


async def query_boards(
    request: sdk_server_pb2.QueryBoardsRequest,
) -> sdk_server_pb2.QueryBoardsResponse:
    """runs cros query boards."""
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = stub.query_boards(request)
        return response


async def current_boards(
    request: sdk_server_pb2.CurrentBoardsRequest,
) -> sdk_server_pb2.CurrentBoardsResponse:
    """returns list of boards in chroot at /build."""
    with grpc.insecure_channel("localhost:50051") as channel:
        stub = sdk_server_pb2_grpc.sdk_server_serviceStub(channel)
        response = stub.current_boards(request)
        return response


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    # asyncio.run(cros_workon_list("betty"))
    target = common_pb2.BuildTarget(name="amd64-generic")
    all_packages_req = sdk_server_pb2.AllPackagesRequest(build_target=target)
    asyncio.run(all_packages(all_packages_req))
    # asyncio.run(
    #     cros_workon_start("sys-kernel/chromeos-kernel-upstream", "betty")
    # )
    # asyncio.run(
    #     cros_workon_stop("sys-kernel/chromeos-kernel-upstream", "betty")
    # )
    # asyncio.run(
    #     cros_workon_info("sys-kernel/chromeos-kernel-upstream", "betty")
    # )
    # asyncio.run(repo_status())


    # async def k():
    #     request = sdk_server_pb2.BuildPackagesRequest()

    #     create_internal_req = sysroot_pb2.SysrootCreateRequest()
    #     create_input = {
    #         "build_target": {"name": "amd64-generic"},
    #         "flags": {"replace": True},
    #     }
    #     json_format.ParseDict(create_input, create_internal_req)
    #     request.create_req.CopyFrom(create_internal_req)

    #     toolchain_internal_req = sysroot_pb2.InstallToolchainRequest()
    #     tool_input = {
    #         "chroot": {"env": {"use_flags": [{"flag": "chrome_internal"}]}},
    #         "sysroot": {
    #             "buildTarget": {"name": "amd64-generic"},
    #             "path": "/build/amd64-generic",
    #         },
    #     }
    #     json_format.ParseDict(tool_input, toolchain_internal_req)
    #     request.toolchain_req.CopyFrom(toolchain_internal_req)

    #     packages_internal_req = sysroot_pb2.InstallPackagesRequest()
    #     packages_input = {
    #         "sysroot": {
    #             "buildTarget": {"name": "amd64-generic"},
    #             "path": "/build/amd64-generic",
    #         },
    #         "use_flags": [{"flag": "chrome_internal"}],
    #     }
    #     json_format.ParseDict(packages_input, packages_internal_req)
    #     request.packages_req.CopyFrom(packages_internal_req)

    #     async for x in build_packages(request):
    #         logging.info(x)

    # asyncio.run(k())


    # asyncio.run(chroot_path())
    # asyncio.run(current_boards())
    # asyncio.run(query_boards())

    # cur_boards_req = sdk_server_pb2.CurrentBoardsRequest()
    # asyncio.run(current_boards(cur_boards_req))

    # workon start, workon info, all packages, current boards
    pass
