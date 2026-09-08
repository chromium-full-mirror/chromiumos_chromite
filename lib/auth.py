# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions for authenticating HTTP requests with OAuth2 tokens."""

import logging
import os
from typing import List

from chromite.lib import cipd
from chromite.lib import cros_build_lib


REFRESH_STATUS_CODES = [401]

# Retry times on get_access_token
RETRY_GET_ACCESS_TOKEN = 3


class AccessTokenError(Exception):
    """Error accessing the token."""


def _GetCipdBinary(pkg_name, bin_name, instance_id):
    """Returns a local path to the given binary fetched from cipd."""
    path = cipd.InstallPackage(cipd.GetCIPDFromCache(), pkg_name, instance_id)

    return os.path.join(path, bin_name)


# crbug:871831 default to last sha1 version.
def GetLuciAuth(
    instance_id="git_revision:25cc6bb6f8d2417353f7fe9fbc9492d70ff381f1",
):
    """Returns a path to the luci-auth binary.

    This will download and install the luci-auth package if it is not already
    deployed.

    Args:
        instance_id: The instance-id of the package to install.

    Returns:
        the path to the luci-auth binary.
    """
    return _GetCipdBinary(
        "infra/tools/luci-auth/linux-amd64", "luci-auth", instance_id
    )


# crbug:871831 default to last sha1 version.
def GetLuciGitCreds(
    instance_id="git_revision:a589aeb19f0e17cb5f5cf9821ab1cce655ae85f8",
):
    """Returns a path to the git-credential-luci binary.

    This will download and install the git-credential-luci package if it is not
    already deployed.

    Args:
        instance_id: The instance-id of the package to install.

    Returns:
        the path to the git-credential-luci binary.
    """
    return _GetCipdBinary(
        "infra/tools/luci/git-credential-luci/linux-amd64",
        "git-credential-luci",
        instance_id,
    )


def Context(cmd: List[str], scopes: List[str] = None) -> List[str]:
    """Helper to wrap cmd with `luci-auth context --scopes=... -- [cmd]`."""
    wrapped = [GetLuciAuth(), "context"]

    # By default use basic userinfo.email scope only, the caller should provide
    # specific scopes as required.
    use_scopes = ["https://www.googleapis.com/auth/userinfo.email"]
    if scopes:
        use_scopes = scopes

    return wrapped + ["-scopes", " ".join(use_scopes), "--"] + cmd


def Login(service_account_json=None) -> None:
    """Logs a user into chrome-infra-auth using luci-auth.

    Runs 'luci-auth login' to get a OAuth2 refresh token.

    Args:
        service_account_json: A optional path to a service account.

    Raises:
        AccessTokenError if login command failed.
    """
    logging.info(
        "Logging into chrome-infra-auth with service_account %s",
        service_account_json,
    )

    cmd = [GetLuciAuth(), "login"]
    if service_account_json and os.path.isfile(service_account_json):
        cmd += ["-service-account-json=%s" % service_account_json]

    result = cros_build_lib.run(cmd, print_cmd=True, check=False)

    if result.returncode:
        raise AccessTokenError(
            "Failed at logging in to chrome-infra-auth: %s, may retry."
        )


def GitCreds(service_account_json=None):
    """Get the git credential using git-credential-luci.

    Args:
        service_account_json: A optional path to a service account.

    Returns:
        The git credential if the command succeeded;

    Raises:
        AccessTokenError if token command failed.
    """
    cmd = [GetLuciGitCreds(), "get"]
    if service_account_json and os.path.isfile(service_account_json):
        cmd += ["-service-account-json=%s" % service_account_json]

    result = cros_build_lib.run(
        cmd, print_cmd=False, capture_output=True, check=False, encoding="utf-8"
    )

    if result.returncode:
        raise AccessTokenError("Unable to fetch git credential.")

    for line in result.stdout.splitlines():
        if line.startswith("password="):
            return line.split("password=")[1].strip()

    raise AccessTokenError("Unable to fetch git credential.")
