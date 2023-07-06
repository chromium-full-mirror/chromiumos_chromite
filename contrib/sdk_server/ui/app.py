# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flask app main file for frontend."""
# !/usr/bin/env vpython3

import asyncio
import time
from typing import List, Optional

# pylint: disable=import-error
from flask import Flask
from flask import jsonify
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from chromite.contrib.sdk_server.grpc_server import client
from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2 as sdk
from chromite.contrib.sdk_server.grpc_server.chromiumos import (
    common_pb2 as common,
)
from chromite.contrib.sdk_server.ui.constants import constants


app = Flask("SDK Server")
app.config["TEMPLATES_AUTO_RELOAD"] = True


index_data = constants.get_index_data()


@app.route("/workon-stop", methods=["GET", "POST"])
def stop():
    try:
        board = str(request.args.get("board"))
        package = str(request.args.get("package"))

        index_data["packages"][board] = [
            k for k in index_data["packages"][board] if k["name"] != package
        ]

        time.sleep(5)
        return ("", 204)

    except KeyError:
        # Handles user just going to /workon-stop, rather than via the button.
        return redirect(url_for("index"))


@app.route("/repo-refresh", methods=["GET", "POST"])
async def repo_refresh():
    """App route to run gRPC repo status endpoint and parse."""

    if request.method == "POST":
        # POST only sent by script.
        response = await client.repo_status(sdk.RepoStatusRequest())

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
    else:
        # GET (user visiting URL) redirects to homepage.
        return redirect(url_for("index"))


@app.route("/get-packages", methods=["GET", "POST"])
async def get_packages():
    """App route to get packages from gRPC server."""

    if request.method == "POST":
        # POST only sent by script

        packages_json = {}
        current_boards = await client.current_boards(sdk.CurrentBoardsRequest())
        for board in current_boards.build_target:
            req = sdk.WorkonListRequest(
                build_target=common.BuildTarget(name=board.name)
            )
            board_packages = (await client.cros_workon_list(req)).package_info
            board_packages = sorted([p.package_name for p in board_packages])
            board_packages = [
                {"name": p, "plus": "0", "minus": "0"} for p in board_packages
            ]

            packages_json[board.name] = board_packages

        return jsonify(packages_json)

    else:
        # GET (user visiting URL) redirects to homepage.
        return redirect(url_for("index"))


@app.route("/", methods=["GET", "POST"])
def index():
    """Home page route. Renders index.html file with templating data."""

    return render_template("index.html", data=index_data)


async def setup():
    """Populates initial templating data from gRPC requests."""

    # List of all boards for various menus.
    all_boards = await client.query_boards(sdk.QueryBoardsRequest())
    all_boards = sorted([b.name for b in all_boards.build_target])
    index_data["all_boards"] = all_boards

    # List of boards with active sysroots for packages display.
    current_boards = await client.current_boards(sdk.CurrentBoardsRequest())
    current_boards = sorted([b.name for b in current_boards.build_target])
    index_data["current_boards"] = current_boards


# pylint: disable=unused-argument
def main(argv: Optional[List[str]]) -> Optional[int]:
    """Runs setup and hosts the Flask app."""

    asyncio.run(setup())
    app.jinja_env.auto_reload = True
    app.run(debug=True, host="0.0.0.0")
