# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flask app main file for frontend."""
# !/usr/bin/env vpython3

import asyncio
from typing import List, Optional

# pylint: disable=import-error
from flask import Flask
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from chromite.api.controller import controller_util
from chromite.contrib.sdk_server.grpc_server import client
from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sdk_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sysroot_pb2
from chromite.contrib.sdk_server.grpc_server.chromiumos import (
    common_pb2 as common,
)
from chromite.contrib.sdk_server.ui.constants import constants
from chromite.lib.parser import package_info


app = Flask("SDK Server")
app.config["TEMPLATES_AUTO_RELOAD"] = True


index_data = constants.get_index_data()

# Code 204 "No content" for endpoints which just execute a function.
NO_RESPONSE_OK = ("", 204)


@app.route("/workon-start", methods=["GET", "POST"])
async def workon_start():
    try:
        board = str(request.args.get("board"))
        package = str(request.args.get("package"))

        parsed_pkg = package_info.parse(package)
        package = common.PackageInfo()
        controller_util.serialize_package_info(parsed_pkg, package)

        req = sdk_server_pb2.WorkonStartRequest(
            build_target=common.BuildTarget(name=board),
            package_info=package,
        )
        await client.cros_workon_start(req)
        return NO_RESPONSE_OK

    except KeyError:
        # Handles user just going to /workon-start, rather than via the button.
        return redirect(url_for("index"))


@app.route("/workon-stop", methods=["GET", "POST"])
async def workon_stop():
    try:
        board = str(request.args.get("board"))
        package = str(request.args.get("package"))

        parsed_pkg = package_info.parse(package)
        package = common.PackageInfo()
        controller_util.serialize_package_info(parsed_pkg, package)

        req = sdk_server_pb2.WorkonStopRequest(
            build_target=common.BuildTarget(name=board),
            package_info=package,
        )

        await client.cros_workon_stop(req)

        return NO_RESPONSE_OK

    except KeyError:
        # Handles user just going to /workon-stop, rather than via the button.
        return redirect(url_for("index"))


@app.route("/repo-refresh", methods=["GET", "POST"])
def repo_refresh():
    """App route to run gRPC repo status endpoint and parse."""

    if request.method == "POST":
        # POST only sent by script.
        response = client.repo_status(sdk_server_pb2.RepoStatusRequest())

        project = ""
        branch = ""
        files = []
        for line in response.info:
            text = line.split()
            if text[0] == "project":
                project = text[1]
                branch = text[3]
            else:
                files += [
                    {"file": text[1], "head": text[0][0], "working": text[0][1]}
                ]

        # Returns dict-like format which JS parses into HTML.
        return jsonify(
            {
                "project": project,
                "branch": branch,
                "files": files,
            }
        )

    # GET (user visiting URL) redirects to homepage.
    return redirect(url_for("index"))


@app.route("/get-packages", methods=["GET", "POST"])
async def get_packages():
    """App route to get packages from gRPC server."""

    if request.method == "POST":
        # POST only sent by script

        packages_json = {}
        current_boards = await client.current_boards(
            sdk_server_pb2.CurrentBoardsRequest()
        )
        for board in current_boards.build_target:
            req = sdk_server_pb2.WorkonListRequest(
                build_target=common.BuildTarget(name=board.name)
            )
            board_packages = (await client.cros_workon_list(req)).package_info
            board_packages = sorted([p.package_name for p in board_packages])
            board_packages = [
                {"name": p, "plus": "0", "minus": "0"} for p in board_packages
            ]

            packages_json[board.name] = board_packages

        return jsonify(packages_json)

    # GET (user visiting URL) redirects to homepage.
    return redirect(url_for("index"))


@app.route("/update-chroot", methods=["GET", "POST"])
async def update_chroot():
    """App route to call BAPI Update."""

    if request.method == "POST":
        flags = sdk_pb2.UpdateRequest.Flags(
            build_source=request.json["buildSource"],
            toolchain_changed=request.json["toolchainChanged"],
        )

        targets = request.json["toolchainTargets"]
        toolchain_targets = [common.BuildTarget(name=b) for b in targets]

        req = sdk_server_pb2.UpdateChrootRequest(
            request=sdk_pb2.UpdateRequest(
                flags=flags, toolchain_targets=toolchain_targets
            )
        )

        # Exhausts asynchronous generator.
        async for _ in client.update_chroot(req):
            pass

        return NO_RESPONSE_OK

    return redirect(url_for("index"))


@app.route("/replace-chroot", methods=["GET", "POST"])
async def replace_chroot():
    """Forwards requests for replace chroot endpoint."""
    if request.method == "POST":
        flags = sdk_pb2.CreateRequest.Flags(
            no_replace=False,
            bootstrap=request.json["bootstrap"],
            no_use_image=request.json["noUseImage"],
        )

        req = sdk_server_pb2.UpdateChrootRequest(
            sdk_pb2.UpdateRequest(
                flags=flags, sdk_version=request.json["version"]
            )
        )

        async for _ in client.replace_chroot(req):
            pass

        return NO_RESPONSE_OK

    return redirect(url_for("index"))


@app.route("/build-packages", methods=["GET", "POST"])
async def build_packages():
    """Formulates/forwards all 3 requests for build packages endpoint."""
    if request.method == "POST":
        create_sysroot = sysroot_pb2.SysrootCreateRequest(
            flags=sysroot_pb2.SysrootCreateRequest.Flags(
                chroot_current=request.json["chrootCurrent"],
                replace=request.json["replace"],
                toolchain_changed=request.json["toolchainChanged"],
                use_cq_prebuilts=request.json["CQPrebuilts"],
            ),
            build_target=common.BuildTarget(name=request.json["buildTarget"]),
        )

        install_toolchain = sysroot_pb2.InstallToolchainRequest(
            flags=sysroot_pb2.InstallToolchainRequest.Flags(
                compile_source=request.json["compileSource"],
                toolchain_changed=request.json["toolchainChanged"],
            )
        )

        install_packages = sysroot_pb2.InstallPackagesRequest(
            flags=sysroot_pb2.InstallPackagesRequest.Flags(
                compile_source=request.json["compileSource"],
                toolchain_changed=request.json["toolchainChanged"],
                dryrun=request.json["dryrun"],
                workon=request.json["workon"],
            )
        )

        req = sdk_server_pb2.BuildPackagesRequest(
            create_req=create_sysroot,
            toolchain_req=install_toolchain,
            packages_req=install_packages,
        )

        async for _ in client.build_packages(req):
            pass

    return redirect(url_for("index"))


@app.route("/", methods=["GET", "POST"])
def index():
    """Home page route. Renders index.html file with templating data."""

    return render_template("index.html", data=index_data)


async def setup():
    """Populates initial templating data from gRPC requests."""

    # List of all boards for various menus.
    all_boards = await client.query_boards(sdk_server_pb2.QueryBoardsRequest())
    all_boards = sorted([b.name for b in all_boards.build_target])
    index_data["all_boards"] = all_boards

    # List of boards with active sysroots for packages display.
    current_boards = await client.current_boards(
        sdk_server_pb2.CurrentBoardsRequest()
    )
    current_boards = sorted([b.name for b in current_boards.build_target])
    index_data["current_boards"] = current_boards


# pylint: disable=unused-argument
def main(argv: Optional[List[str]]) -> Optional[int]:
    """Runs setup and hosts the Flask app."""

    asyncio.run(setup())
    app.jinja_env.auto_reload = True
    app.run(debug=True, host="0.0.0.0")
