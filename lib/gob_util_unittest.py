# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for gob_util.py"""

import base64
import http.client
import json
from pathlib import Path
import tempfile
import time
import urllib.request

import pytest

from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import gob_util
from chromite.lib import timeout_util


gob_util.TRY_LIMIT = 1


class FakeHTTPResponse:
    """Enough of a HTTPResponse for FetchUrl.

    See https://docs.python.org/3/library/http.client.html#httpresponse-objects
    for more details.
    """

    def __init__(
        self, body=b"", headers=(), reason=None, status=200, version=11
    ) -> None:
        if reason is None:
            reason = http.client.responses[status]

        self.body = body
        self.headers = dict(headers)
        self.msg = None
        self.reason = reason
        self.status = status
        self.version = version

    def read(self):
        return self.body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def getheaders(self):
        return tuple(self.headers.items())


class GobTest(cros_test_lib.MockTestCase):
    """Unittests that use mocks."""

    UTF8_DATA = b"That\xe2\x80\x99s an error. That\xe2\x80\x99s all we know."

    def setUp(self) -> None:
        self.create_http_request = self.PatchObject(
            gob_util, "CreateHttpReq", autospec=False
        )
        self.conn = self.PatchObject(urllib.request, "urlopen")

    def testUtf8Response(self) -> None:
        """Handle gerrit responses w/UTF8 in them."""
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=self.UTF8_DATA
        )
        gob_util.FetchUrl("", "")

    def testUtf8Response502(self) -> None:
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=self.UTF8_DATA, status=502
        )

        with self.assertRaises(gob_util.InternalGOBError):
            gob_util.FetchUrl("", "")

    def testCherryPick(self) -> None:
        """Test correct format of cherry-pick request."""
        body = json.dumps({"change_id": "I0001"}).encode()
        xss_protection_prefix = b")]}'\n"
        body = xss_protection_prefix + body
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body
        )
        gob_util.CherryPick(
            host="chromium",
            change=1234,
            branch="target_branch",
            base_commit="I123",
        )
        self.create_http_request.assert_called_with(
            "chromium",
            "changes/1234/revisions/current/cherrypick",
            reqtype="POST",
            headers=None,
            body={
                "destination": "target_branch",
                "message": "",
                "allow_conflicts": False,
                "base": "I123",
            },
        )

    def testConnectionTimeout(self) -> None:
        """Exercise the timeout process."""
        # To finish the test quickly, we need to shorten the timeout.
        self.PatchObject(gob_util, "REQUEST_TIMEOUT_SECONDS", 1)

        # Setup a 'hanging' network connection.
        def simulateHang(*_args, **_kwargs) -> None:
            time.sleep(30)
            self.fail("Would hang forever.")

        self.conn.return_value.__enter__.side_effect = simulateHang

        # Verify that we fail, with expected timeout error.
        with self.assertRaises(timeout_util.TimeoutError):
            gob_util.FetchUrl("", "")

    def testHtmlParser(self) -> None:
        """Verify that GOB error message is parsed properly."""
        html_data = """
<!DOCTYPE html>
 <html lang=en>
 <meta charset=utf-8>
 <meta name=viewport>
 <title>Error 403 (Forbidden)!!1</title>
 <style>"*{margin:0;padding:0}"</style>
 <div id="af-error-container">
 <a href=//www.google.com><span id=logo aria-label=Google></span></a>

 <p>Error <b>403.</b><br><ins>That's an error.<p>Too bad...</ins>
 </div>
 <div id="come other stuff">
    some other stuff
 </div>
<html>"""
        expected_parsed_data = """Error 403.
That's an error.

Too bad..."""
        ep = gob_util.ErrorParser()
        ep.feed(html_data)
        ep.close()
        self.assertEqual(expected_parsed_data, ep.ParsedDiv())

    def testCreateChange(self) -> None:
        body = json.dumps({"change_num": 123456}).encode()
        xss_protection_prefix = b")]}'\n"
        body = xss_protection_prefix + body
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body, status=200
        )
        change_json = gob_util.CreateChange(
            "some.git.url", "project", "branch", "subject", True
        )
        self.assertEqual(change_json["change_num"], 123456)

        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body, status=201
        )
        change_json = gob_util.CreateChange(
            "some.git.url", "project", "branch", "subject", True
        )
        self.assertEqual(change_json["change_num"], 123456)

    def testChangeEdit(self) -> None:
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body={}, status=204
        )
        gob_util.ChangeEdit(
            "some.git.url", 123456, "some/file/path", "some file contents"
        )

    def testPublishChangeEdit(self) -> None:
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body={}, status=204
        )
        gob_util.PublishChangeEdit("some.git.url", 123456)

    def testGetFileContents(self) -> None:
        expected_contents = "some file contents"
        body = base64.b64encode(expected_contents.encode())
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body, status=200
        )
        contents = gob_util.GetFileContentsOnHead(
            "some.git.url", "some/file/path"
        )
        self.assertEqual(contents, expected_contents)
        contents = gob_util.GetFileContents("some.git.url", "some/file/path")
        self.assertEqual(contents, expected_contents)

    def testGetFileContentsFromGerrit(self) -> None:
        """Test for GetFileContentsFromGerrit()"""

        expected_contents = "some file contents"
        body = base64.b64encode(expected_contents.encode())
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body, status=200
        )
        contents = gob_util.GetFileContentsFromGerrit(
            "some.git.url", "100000", "some/file/path"
        )
        self.assertEqual(contents, expected_contents)

    def testGetChangeMergeable(self) -> None:
        """Test for GetChangeMergeable()"""

        mergeable_info = {"mergeable": True}
        body = json.dumps(mergeable_info).encode()
        xss_protection_prefix = b")]}'\n"
        body = xss_protection_prefix + body
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body, status=200
        )
        result = gob_util.GetChangeMergeable("some.git.url", "100000")
        self.assertEqual(result, mergeable_info)

    def testRebase(self) -> None:
        """Test for Rebase()"""

        change_info = {}
        body = json.dumps(change_info).encode()
        xss_protection_prefix = b")]}'\n"
        body = xss_protection_prefix + body
        self.conn.return_value.__enter__.return_value = FakeHTTPResponse(
            body=body, status=200
        )
        result = gob_util.Rebase("some.git.url", "100000")
        self.assertEqual(result, change_info)


class GetCookieTests(cros_test_lib.TestCase):
    """Unittests for GetCookies()"""

    def testSimple(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w+") as f:
            f.write(".googlesource.com\tTRUE\t/f\tTRUE\t2147483647\to\tfoo=bar")
            f.flush()
            cookies = gob_util.GetCookies(
                "foo.googlesource.com", "/foo", [f.name]
            )
            self.assertEqual(cookies, {"o": "foo=bar"})
            cookies = gob_util.GetCookies("google.com", "/foo", [f.name])
            self.assertEqual(cookies, {})
            cookies = gob_util.GetCookies("foo.googlesource.com", "/", [f.name])
            self.assertEqual(cookies, {})


class ParseConfigFileTest(cros_test_lib.TestCase):
    """Unittest for ParseConfig()"""

    def testSimple(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w+") as f:
            secret = "Basic S0MEVERYL0NGSTR1NGHERETHATWENEEDT0GET="
            f.write(f"[http]\n\t\tExtraHeader = Authorization: {secret}\n")
            f.flush()
            headers = gob_util.ParseConfig(Path(f.name))
            self.assertEqual(headers, {"Authorization": secret})


@pytest.mark.network_test
class NetworkGobTest(cros_test_lib.TestCase):
    """Unittests that talk to real Gerrit."""

    def test200(self) -> None:
        """Test successful loading of change."""
        gob_util.FetchUrlJson(
            constants.EXTERNAL_GOB_HOST,
            "changes/227254/detail",
        )

    def test404(self) -> None:
        gob_util.FetchUrlJson(constants.EXTERNAL_GOB_HOST, "foo/bar/baz")

    def test404Exception(self) -> None:
        with self.assertRaises(gob_util.GOBError) as ex:
            gob_util.FetchUrlJson(
                constants.EXTERNAL_GOB_HOST,
                "foo/bar/baz",
                ignore_404=False,
            )
        self.assertEqual(ex.exception.http_status, 404)
