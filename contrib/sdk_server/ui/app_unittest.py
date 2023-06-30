# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for SDK Server Flask App."""

from copy import deepcopy

import pytest

# Tests require multiple dependencies CQ will not be able to resolve.
try:
    from chromite.contrib.sdk_server.ui import app as sdk_app
except ModuleNotFoundError:
    sdk_app = None

reason = "Requires Flask and gRPC server code."

@pytest.fixture()
def app():
    """Yields clean app from main Flask file in testing mode."""
    app = sdk_app.app
    app.config.update(
        {
            "TESTING": True,
        }
    )

    yield app


@pytest.fixture()
def client(app):
    """Yields unaltered app test client for requests/responses."""

    return app.test_client()


@pytest.fixture()
def client_one_package(client):
    """Test client fixture with package configuration for workon_stop."""

    p = {"name": "media-libs/libsync", "plus": "116", "minus": "40"}
    sdk_app.index_data["packages"] = {"amd64-generic": [p]}
    return client


@pytest.mark.skipif(sdk_app is None, reason=reason)
def test_page_loads(client):
    """Tests basic app loading by checking for title in index head."""
    response = client.get("/")
    assert b"<title>SDK Server</title>" in response.data


@pytest.mark.skipif(sdk_app is None, reason=reason)
def test_workon_stop_empty_redirect(client):
    """workon-stop redirects with empty request (i.e. user visited route)."""

    orig_packages = deepcopy(sdk_app.index_data["packages"])
    response = client.get("/workon-stop", follow_redirects=True)

    assert len(response.history) == 1
    assert response.request.path == "/"
    assert sdk_app.index_data["packages"] == orig_packages


@pytest.mark.skipif(sdk_app is None, reason=reason)
def test_workon_stop_bad_redirect(client):
    """workon-stop redirects with bad request."""
    orig_packages = deepcopy(sdk_app.index_data["packages"])

    response = client.get(
        "/workon-stop",
        query_string={
            "board": "boardThatDoesntExist",
            "package": "notARealPackage",
        },
        follow_redirects=True,
    )

    assert len(response.history) == 1
    assert response.request.path == "/"
    assert sdk_app.index_data["packages"] == orig_packages


@pytest.mark.skipif(sdk_app is None, reason=reason)
def test_workon_stop(client_one_package):
    """workon-stop properly deletes package from index data."""
    board = "amd64-generic"
    package = "media-libs/libsync"

    response = client_one_package.get(
        "/workon-stop", query_string={"board": board, "package": package}
    )

    assert sdk_app.index_data["packages"][board] == []
    assert response.status_code == 204
