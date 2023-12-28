# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the gs_urls_util.py module."""

from pathlib import Path
from typing import Optional, Type

import pytest

from chromite.lib import cros_test_lib
from chromite.utils import gs_urls_util


class CanonicalizeURLTest(cros_test_lib.TestCase):
    """Tests for the CanonicalizeURL function."""

    def _checkit(self, in_url: str, exp_url: str) -> None:
        self.assertEqual(gs_urls_util.CanonicalizeURL(in_url), exp_url)

    def testPublicUrl(self) -> None:
        """Test public https URLs."""
        self._checkit(
            "https://commondatastorage.googleapis.com/releases/some/file/t.gz",
            "gs://releases/some/file/t.gz",
        )

    def testPrivateUrl(self) -> None:
        """Test private https URLs."""
        self._checkit(
            "https://storage.cloud.google.com/releases/some/file/t.gz",
            "gs://releases/some/file/t.gz",
        )
        self._checkit(
            "https://pantheon.corp.google.com/storage/browser/releases/some/"
            "file/t.gz",
            "gs://releases/some/file/t.gz",
        )
        self._checkit(
            "https://stainless.corp.google.com/browse/releases/some/file/t.gz",
            "gs://releases/some/file/t.gz",
        )

    def testDuplicateBase(self) -> None:
        """Test multiple prefixes in a single URL."""
        self._checkit(
            (
                "https://storage.cloud.google.com/releases/some/"
                "https://storage.cloud.google.com/some/file/t.gz"
            ),
            (
                "gs://releases/some/"
                "https://storage.cloud.google.com/some/file/t.gz"
            ),
        )


class PathIsGsTests(cros_test_lib.TestCase):
    """Tests for the PathIsGs function."""

    def testString(self) -> None:
        """Test strings!"""
        self.assertTrue(gs_urls_util.PathIsGs("gs://foo"))
        self.assertFalse(gs_urls_util.PathIsGs("/tmp/f"))

    def testPath(self) -> None:
        """Test Path objects!"""
        self.assertFalse(gs_urls_util.PathIsGs(Path.cwd()))
        self.assertFalse(gs_urls_util.PathIsGs(Path("gs://foo")))


class GsUrlToHttpTest(cros_test_lib.TestCase):
    """Tests for the GsUrlToHttp function."""

    def setUp(self) -> None:
        self.testUrls = [
            "gs://releases",
            "gs://releases/",
            "gs://releases/path",
            "gs://releases/path/",
            "gs://releases/path/file",
        ]

    def testPublicUrls(self) -> None:
        """Test public https URLs."""
        expected = [
            "https://storage.googleapis.com/releases",
            "https://storage.googleapis.com/releases/",
            "https://storage.googleapis.com/releases/path",
            "https://storage.googleapis.com/releases/path/",
            "https://storage.googleapis.com/releases/path/file",
        ]

        for gs_url, http_url in zip(self.testUrls, expected):
            self.assertEqual(gs_urls_util.GsUrlToHttp(gs_url), http_url)
            self.assertEqual(
                gs_urls_util.GsUrlToHttp(gs_url, directory=True), http_url
            )

    def testPrivateUrls(self) -> None:
        """Test private https URLs."""
        expected = [
            "https://storage.cloud.google.com/releases",
            "https://stainless.corp.google.com/browse/releases/",
            "https://storage.cloud.google.com/releases/path",
            "https://stainless.corp.google.com/browse/releases/path/",
            "https://storage.cloud.google.com/releases/path/file",
        ]

        for gs_url, http_url in zip(self.testUrls, expected):
            self.assertEqual(
                gs_urls_util.GsUrlToHttp(gs_url, public=False), http_url
            )

    def testPrivateDirectoryUrls(self) -> None:
        """Test private https directory URLs."""
        expected = [
            "https://stainless.corp.google.com/browse/releases",
            "https://stainless.corp.google.com/browse/releases/",
            "https://stainless.corp.google.com/browse/releases/path",
            "https://stainless.corp.google.com/browse/releases/path/",
            "https://stainless.corp.google.com/browse/releases/path/file",
        ]

        for gs_url, http_url in zip(self.testUrls, expected):
            self.assertEqual(
                gs_urls_util.GsUrlToHttp(gs_url, public=False, directory=True),
                http_url,
            )


@pytest.mark.parametrize(
    "uri,expected_bucket,expected_exception",
    (
        ("gs://my_bucket", "my_bucket", None),
        ("gs://my_bucket/my_resource.txt", "my_bucket", None),
        ("my_bucket", "my_bucket", None),
        ("my_bucket/my_resource.text", "my_bucket", None),
        ("https://my_bucket", "", ValueError),
    ),
)
def test_extract_gs_bucket(
    uri: str,
    expected_bucket: str,
    expected_exception: Optional[Type[Exception]],
) -> None:
    """Test the behaviors of extract_gs_bucket().

    Args:
        uri: The URI to pass into extract_gs_bucket().
        expected_bucket: The return value we expect. Ignored if expect_raise is
            given.
        expected_exception: If given, the exception type that the function
            should raise.
    """
    if expected_exception:
        with pytest.raises(expected_exception):
            gs_urls_util.extract_gs_bucket(uri)
    else:
        bucket = gs_urls_util.extract_gs_bucket(uri)
        assert bucket == expected_bucket
