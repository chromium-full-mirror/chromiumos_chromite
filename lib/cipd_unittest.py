# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for cipd."""

import hashlib
import json
import logging
from pathlib import Path
import time
from unittest import mock

from chromite.third_party import httplib2
import pytest

from chromite.lib import cipd
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import path_util


class CIPDTest(cros_test_lib.MockTestCase):
    """Tests for chromite.lib.cipd"""

    def testChromeInfraRequest(self) -> None:
        MockHttp = self.PatchObject(httplib2, "Http")
        body = b")]}'\n" + json.dumps(
            {
                "clientBinary": {
                    "signedUrl": "http://example.com",
                },
                "clientRefAliases": [
                    {
                        "hashAlgo": "SKIP",
                        "hexDigest": "aaaa",
                    },
                    {
                        "hashAlgo": "SHA256",
                        "hexDigest": "bogus-sha256",
                    },
                ],
            }
        ).encode("utf-8")

        # Mock CIPD server errors.
        response500 = mock.Mock()
        response500.status = 500
        response200 = mock.Mock()
        response200.status = 200
        MockHttp.return_value.request.side_effect = [
            (
                response500,
                "<title>500 Server Error</title><p>Try again later</p>",
            ),
            (
                response500,
                "<title>500 Server Error</title><p>Try again later</p>",
            ),
            (
                response500,
                "<title>500 Server Error</title><p>Try again later</p>",
            ),
            (response200, body),
        ]

        # Also mock time.sleep so we don't slow down the tests during
        # exponential backoff.
        MockSleep = self.PatchObject(time, "sleep")

        # pylint: disable=protected-access
        actual_response = cipd._ChromeInfraRequest(
            "DescribeClient",
            {
                "package": "infra/tools/cipd/linux-amd64",
                "instance": {
                    "hashAlgo": "SHA256",
                    "hexDigest": "fake-sha256",
                },
            },
        )

        self.assertEqual(
            actual_response,
            {
                "clientBinary": {
                    "signedUrl": "http://example.com",
                },
                "clientRefAliases": [
                    {
                        "hashAlgo": "SKIP",
                        "hexDigest": "aaaa",
                    },
                    {
                        "hashAlgo": "SHA256",
                        "hexDigest": "bogus-sha256",
                    },
                ],
            },
        )

        # Assert that we waited the expected number of seconds between retries.
        self.assertEqual(
            MockSleep.mock_calls,
            [mock.call(2), mock.call(4), mock.call(8)],
        )

    def testDownloadCIPD(self) -> None:
        MockHttp = self.PatchObject(httplib2, "Http")
        cipd_response_body = b")]}'\n" + json.dumps(
            {
                "clientBinary": {
                    "signedUrl": "http://example.com",
                },
                "clientRefAliases": [
                    {
                        "hashAlgo": "SKIP",
                        "hexDigest": "aaaa",
                    },
                    {
                        "hashAlgo": "SHA256",
                        "hexDigest": "bogus-sha256",
                    },
                ],
            }
        ).encode("utf-8")

        # Mock GCS errors.
        response500 = mock.Mock()
        response500.status = 500
        response200 = mock.Mock()
        response200.status = 200
        MockHttp.return_value.request.side_effect = [
            (response200, cipd_response_body),
            (response500, "<title>500 Server Error</title><p>GCS is down.</p>"),
            (response500, "<title>500 Server Error</title><p>GCS is down.</p>"),
            (response500, "<title>500 Server Error</title><p>GCS is down.</p>"),
            (response200, b"bogus binary file"),
        ]

        # Also mock time.sleep so we don't slow down the tests during
        # exponential backoff.
        MockSleep = self.PatchObject(time, "sleep")

        sha1 = self.PatchObject(hashlib, "sha256")
        sha1.return_value.hexdigest.return_value = "bogus-sha256"

        # pylint: disable=protected-access
        self.assertEqual(
            b"bogus binary file", cipd._DownloadCIPD("bogus-instance-sha256")
        )

        # Assert that we waited the expected number of seconds between retries.
        self.assertEqual(
            MockSleep.mock_calls,
            [mock.call(2), mock.call(4), mock.call(8)],
        )


class CipdCacheTest(cros_test_lib.MockTempDirTestCase):
    """Tests for CipdCache helper."""

    def setUp(self) -> None:
        self.download_mock = self.PatchObject(
            cipd, "_DownloadCIPD", return_value=b"data"
        )

    def testFetch(self) -> None:
        """Check CipdCache._Fetch behavior."""
        cache = cipd.CipdCache(self.tempdir)
        ref = cache.Lookup(("1234",))
        ref.SetDefault("cipd://1234")
        self.assertEqual("data", osutils.ReadFile(ref.path))

    def testGetCIPDFromCache(self) -> None:
        """Check GetCIPDFromCache behavior."""
        self.PatchObject(path_util, "GetCacheDir", return_value=self.tempdir)
        path = cipd.GetCIPDFromCache()
        # This is more about making sure the func doesn't crash than inspecting
        # the internal caching logic (which is handled by lib.cache_unittest
        # already).
        self.assertTrue(path.startswith(str(self.tempdir)))

    def testGetCIPDFromAltCacheDir(self) -> None:
        """Check GetCIPDFromCache behavior."""
        cache_dir = self.tempdir / "cache"
        cache_dir.mkdir()
        alt_cache_dir = self.tempdir / "alt"
        alt_cache_dir.mkdir()
        self.PatchObject(path_util, "GetCacheDir", return_value=cache_dir)
        path = cipd.GetCIPDFromCache(cache_dir=alt_cache_dir)
        # This is more about making sure the func doesn't crash than inspecting
        # the internal caching logic (which is handled by lib.cache_unittest
        # already).
        self.assertStartsWith(path, str(alt_cache_dir))


def test_get_instance_id(run_mock: cros_test_lib.RunCommandMock) -> None:
    """Validate the command creation and processing of GetInstanceID."""
    run_mock.SetDefaultCmdResult(
        stdout="""\
Packages:
  some/package:-V4koaHp92NryA4-caFteRpED8nsWY8z7PyZq5a7CXQC
"""
    )
    expected = ["/cipd.fake", "resolve", "some/package", "-version", "version"]
    kwargs = {
        "capture_output": True,
        "encoding": "utf-8",
        "debug_level": logging.DEBUG,
    }

    assert (
        cipd.GetInstanceID("/cipd.fake", "some/package", "version")
        == "-V4koaHp92NryA4-caFteRpED8nsWY8z7PyZq5a7CXQC"
    )
    run_mock.assertCommandCalled(expected, **kwargs)

    cipd.GetInstanceID(
        "/cipd.fake",
        "some/package",
        "version",
        service_account_json="/creds.json",
    )
    run_mock.assertCommandCalled(
        expected + ["-service-account-json", "/creds.json"], **kwargs
    )


def test_search_instances(run_mock: cros_test_lib.RunCommandMock) -> None:
    """Validate the command creation and processing of search_instances."""
    run_mock.SetDefaultCmdResult(
        stdout="""\
Instances:
  some/package:nn9mIcZ_6_OymZEJylQtv0OlH0hhR_1BCrt4egbjiasC
  some/package:-V4koaHp92NryA4-caFteRpED8nsWY8z7PyZq5a7CXQC
"""
    )
    assert cipd.search_instances(
        "/cipd.fake", "some/package", {"tag1": "value1"}
    ) == [
        "nn9mIcZ_6_OymZEJylQtv0OlH0hhR_1BCrt4egbjiasC",
        "-V4koaHp92NryA4-caFteRpED8nsWY8z7PyZq5a7CXQC",
    ]
    run_mock.assertCommandCalled(
        ["/cipd.fake", "search", "some/package", "-tag", "tag1:value1"],
        capture_output=True,
        encoding="utf-8",
        check=False,
        debug_level=mock.ANY,
    )


def test_search_instances_no_matches(
    run_mock: cros_test_lib.RunCommandMock,
) -> None:
    """Validate search_instances when package exists, no instances are found."""
    run_mock.SetDefaultCmdResult(stdout="No matching instances.\n")
    assert cipd.search_instances("/cipd.fake", "some/package", {}) == []


def test_search_instances_no_prefix(
    run_mock: cros_test_lib.RunCommandMock,
) -> None:
    """Validate search_instances when no package exists (or no permission)."""
    run_mock.SetDefaultCmdResult(
        returncode=1,
        stderr="""\
Error: prefix "some/package" doesn't exist or "user:foo@bar.com" is not allowed\
 to see it, run `cipd auth-login` to login or relogin.
""",
    )
    assert cipd.search_instances("/cipd.fake", "some/package", {}) == []


def test_search_instances_other_error(
    run_mock: cros_test_lib.RunCommandMock,
) -> None:
    """Validate search_instances when an unanticipated cipd error occurs."""
    test_error = "Error: (cipd test) something bad."
    run_mock.SetDefaultCmdResult(returncode=1, stderr=test_error)
    with pytest.raises(cros_build_lib.CalledProcessError) as error_info:
        cipd.search_instances("/cipd.fake", "some/package", {})
    assert test_error in str(error_info.value)


def test_install_package(run_mock: cros_test_lib.RunCommandMock) -> None:
    """Validate the command created by InstallPackage"""
    cipd.InstallPackage(
        "/cipd.fake", "some/package", "version-ref", destination="/destination"
    )
    run_mock.assertCommandContains(
        [
            "/cipd.fake",
            "ensure",
            "-root",
            Path("/destination/some/package/version-ref"),
            "-ensure-file",
            "-",
        ],
        input="some/package version-ref",
    )


def test_install_package_cache_dir(
    run_mock: cros_test_lib.RunCommandMock,
) -> None:
    """Validate the command created by InstallPackage"""
    cipd.InstallPackage(
        "/cipd.fake", "some/package", "version-ref", cache_dir="/cache"
    )
    run_mock.assertCommandContains(
        [
            "/cipd.fake",
            "ensure",
            "-root",
            Path("/cache/cipd/packages/some/package/version-ref"),
            "-ensure-file",
            "-",
        ],
        input="some/package version-ref",
    )


def test_create_package(run_mock: cros_test_lib.RunCommandMock) -> None:
    """Validate the command created by CreatePackage."""
    cipd.CreatePackage(
        "/cipd.fake",
        "some/package",
        "input/bundle",
        tags={"tag1": "value1", "tag2": "value2"},
        refs=["latest"],
        cred_path="/creds.json",
        service_url=cipd.STAGING_SERVICE_URL,
    )
    run_mock.assertCommandContains(
        [
            "/cipd.fake",
            "create",
            "-name",
            "some/package",
            "-in",
            "input/bundle",
            "-tag",
            "tag1:value1",
            "-tag",
            "tag2:value2",
            "-ref",
            "latest",
            "-service-account-json",
            "/creds.json",
            "-service-url",
            "https://chrome-infra-packages-dev.appspot.com",
        ]
    )


def test_build_package(run_mock: cros_test_lib.RunCommandMock) -> None:
    """Validate the command created by build_package."""
    cipd.build_package(
        "/cipd.fake", "some/package", Path("input/bundle"), Path("/out.zip")
    )
    run_mock.assertCommandContains(
        [
            "/cipd.fake",
            "pkg-build",
            "-name",
            "some/package",
            "-in",
            Path("input/bundle"),
            "-out",
            Path("/out.zip"),
        ]
    )
