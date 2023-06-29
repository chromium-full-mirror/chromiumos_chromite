# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Flask app main file for frontend."""
# !/usr/bin/env vpython3

import time
from constants import constants

# pylint: disable=import-error
from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for


app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True


index_data = constants.get_index_data()

@app.route("/workon-stop")
def stop():
    try:
        board = str(request.args.get("board"))[:-13]
        package = str(request.args.get("package"))

        index_data["packages"][board] = [
            k for k in index_data["packages"][board] if k["name"] != package
        ]
        time.sleep(5)
        return "Nothing"
    # Handles user just going to /workon-stop, rather than via the button
    except KeyError:
        return redirect(url_for("index"))


@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html", data=index_data)


if __name__ == "__main__":
    app.jinja_env.auto_reload = True
    app.run(debug=True, host="0.0.0.0")
