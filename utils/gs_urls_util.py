# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Library to make common google storage operations more reliable."""

from typing import TYPE_CHECKING, Union
import urllib.parse


if TYPE_CHECKING:
    import os

# Public path, only really works for files.
PUBLIC_BASE_HTTPS_URL = "https://storage.googleapis.com/"

# Private path for files.
PRIVATE_BASE_HTTPS_URL = "https://storage.cloud.google.com/"

# Private path for directories.
# TODO(akeshet): this is a workaround for b/27653354. If that is ultimately
# fixed, revisit this workaround.
PRIVATE_BASE_HTTPS_DOWNLOAD_URL = "https://stainless.corp.google.com/browse/"
BASE_GS_URL = "gs://"


def PathIsGs(path: Union[str, "os.PathLike[str]"]) -> bool:
    """Determine if |path| is a Google Storage URI.

    We accept pathlib objects because our GS APIs handle local filesystem paths.
    """
    return isinstance(path, str) and path.startswith(BASE_GS_URL)


def CanonicalizeURL(url: str, strict: bool = False) -> str:
    """Convert provided URL to gs:// URL, if it follows a known format.

    Args:
        url: URL to canonicalize.
        strict: Raises exception if URL cannot be canonicalized.
    """
    for prefix in (
        PUBLIC_BASE_HTTPS_URL,
        PRIVATE_BASE_HTTPS_URL,
        PRIVATE_BASE_HTTPS_DOWNLOAD_URL,
        "https://pantheon.corp.google.com/storage/browser/",
        "https://commondatastorage.googleapis.com/",
    ):
        if url.startswith(prefix):
            return url.replace(prefix, BASE_GS_URL, 1)

    if not PathIsGs(url) and strict:
        raise ValueError("Url %r cannot be canonicalized." % url)

    return url


def GetGsURL(
    bucket: str, for_gsutil: bool = False, public: bool = True, suburl: str = ""
) -> str:
    """Construct a Google Storage URL

    Args:
        bucket: The Google Storage bucket to use
        for_gsutil: Do you want a URL for passing to `gsutil`?
        public: Do we want the public or private url
        suburl: A url fragment to tack onto the end

    Returns:
        The fully constructed URL
    """
    url = "gs://%s/%s" % (bucket, suburl)

    if for_gsutil:
        return url
    else:
        return GsUrlToHttp(url, public=public)


def GsUrlToHttp(path: str, public: bool = True, directory: bool = False) -> str:
    """Convert a GS URL to a HTTP URL for the same resource.

    Because the HTTP Urls are not fixed (and may not always be simple prefix
    replacements), use this method to centralize the conversion.

    Directories need to have different URLs from files, because the Web UIs for
    GS are weird and really inconsistent. Also, public directories probably
    don't work, and probably never will (permissions as well as UI).

    e.g. 'gs://chromeos-image-archive/path/file' ->
         'https://pantheon/path/file'

    Args:
        path: GS URL to convert.
        public: Is this URL for Googler access, or publicly visible?
        directory: Force this URL to be treated as a directory?
            We try to autodetect on False.

    Returns:
        https URL as a string.
    """
    assert PathIsGs(path)
    directory = directory or path.endswith("/")

    # Public HTTP URls for directories don't work'
    # assert not public or not directory,

    if public:
        return path.replace(BASE_GS_URL, PUBLIC_BASE_HTTPS_URL, 1)
    else:
        if directory:
            return path.replace(BASE_GS_URL, PRIVATE_BASE_HTTPS_DOWNLOAD_URL, 1)
        else:
            return path.replace(BASE_GS_URL, PRIVATE_BASE_HTTPS_URL, 1)


def extract_gs_bucket(uri: str) -> str:
    """Extract the Google Storage bucket from an ambiguously formatted URI.

    All of the following inputs should return the same output (my_bucket):
        gs://my_bucket
        gs://my_bucket
        gs://my_bucket/my_resource.txt
        my_bucket
        my_bucket/my_resource.txt

    Raises:
        ValueError: The URI uses a scheme other than gs://, such as https://.
    """
    parsed_uri = urllib.parse.urlparse(uri)
    if parsed_uri.scheme == "gs":
        return parsed_uri.netloc
    if not parsed_uri.scheme:
        return uri.split("/")[0]
    raise ValueError(f"Unexpected scheme {parsed_uri.scheme} in URI {uri}.")
