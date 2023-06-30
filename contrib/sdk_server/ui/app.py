# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flask app main file for frontend."""
# !/usr/bin/env vpython3

import time
from chromite.contrib.sdk_server.ui.constants import constants
from typing import Optional, List

# pylint: disable=import-error
from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

app = Flask("SDK Server")
app.config["TEMPLATES_AUTO_RELOAD"] = True


index_data = constants.get_index_data()

@app.route("/workon-stop", methods = ["GET", "POST"])
def stop():
    try:

        board = str(request.args.get("board"))
        package = str(request.args.get("package"))

        index_data["packages"][board] = [
            k for k in index_data["packages"][board] if k["name"] != package
        ]

        time.sleep(5)
        return ('', 204)

    # Handles user just going to /workon-stop, rather than via the button
    except KeyError:
        return redirect(url_for("index"))



@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html", data=index_data)

# pylint: disable=unused-argument
def main(argv: Optional[List[str]]) -> Optional[int]:
    app.jinja_env.auto_reload = True
    app.run(debug=True, host="0.0.0.0")
