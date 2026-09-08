# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module that contains unittests for auth module."""

import time

from chromite.lib import auth
from chromite.lib import cros_test_lib


class AuthTest(cros_test_lib.RunCommandTestCase):
    """Test cases for methods in auth."""

    def setUp(self) -> None:
        self.PatchObject(time, "sleep")
        self.PatchObject(auth, "GetLuciAuth", return_value="luci-auth")
        self.PatchObject(
            auth, "GetLuciGitCreds", return_value="git-credential-luci"
        )

    def testContextDefaultScopes(self) -> None:
        """Test Context with default scopes."""
        self.assertEqual(
            auth.Context(["gsutil", "ls"]),
            [
                "luci-auth",
                "context",
                "-scopes",
                "https://www.googleapis.com/auth/userinfo.email",
                "--",
                "gsutil",
                "ls",
            ],
        )

    def testContextSuppliedScopes(self) -> None:
        """Test Context with scopes supplied."""
        self.assertEqual(
            auth.Context(
                ["gsutil", "ls"], ["https://fake-scope", "https://fake-scope2"]
            ),
            [
                "luci-auth",
                "context",
                "-scopes",
                "https://fake-scope https://fake-scope2",
                "--",
                "gsutil",
                "ls",
            ],
        )

    def testLoginFailed(self) -> None:
        """Test Login failing."""
        self.rc.AddCmdResult(["luci-auth", "login"], stderr="", returncode=1)
        self.assertRaises(auth.AccessTokenError, auth.Login)

    def testLoginPassed(self) -> None:
        """Test Login working."""
        self.rc.AddCmdResult(["luci-auth", "login"], stdout="")
        self.assertIsNone(auth.Login())

    def testGitCredsFailed(self) -> None:
        """Test git-credential-luci failing."""
        self.rc.AddCmdResult(
            ["git-credential-luci", "get"], stderr="", returncode=1
        )
        self.assertRaises(auth.AccessTokenError, auth.GitCreds)

    def testGitCredsPassed(self) -> None:
        """Test git-credential-luci working."""
        stdout = "\n".join(
            [
                "user=some-luci-user",
                "password=some-git-password",
            ]
        )
        self.rc.AddCmdResult(["git-credential-luci", "get"], stdout=stdout)
        self.assertEqual(auth.GitCreds(), "some-git-password")

    def testGitCredsNoPassword(self) -> None:
        """Test git-credential-luci returning unknown output."""
        stdout = "\n".join(
            [
                "unknown stdout format, line #1",
                "unknown stdout format, line #2",
            ]
        )
        self.rc.AddCmdResult(["git-credential-luci", "get"], stdout=stdout)
        self.assertRaises(auth.AccessTokenError, auth.GitCreds)
