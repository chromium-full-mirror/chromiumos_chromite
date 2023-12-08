# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the alerts.py module."""

import email
import json
import os
import smtplib
import socket

from chromite.lib import alerts
from chromite.lib import cros_test_lib
from chromite.lib import osutils


pytestmark = cros_test_lib.pytestmark_inside_only


# No need to make unittests sleep.
alerts.SmtpServer.SMTP_RETRY_DELAY = 0


class SmtpServerTest(cros_test_lib.MockTestCase):
    """Tests for Smtp server."""

    # pylint: disable=protected-access

    def setUp(self) -> None:
        self.smtp_mock = self.PatchObject(smtplib, "SMTP")

    def testBasic(self) -> None:
        """Basic spot check."""
        msg = alerts.CreateEmail(
            "fake subject", "fake@localhost", "fake message"
        )
        server = alerts.SmtpServer(("localhost", 1))
        ret = server.Send(msg)
        self.assertTrue(ret)
        self.assertEqual(self.smtp_mock.call_count, 1)

    def testRetryException(self) -> None:
        """Verify we try sending multiple times & don't abort socket.error."""
        self.smtp_mock.side_effect = socket.error("test fail")
        msg = alerts.CreateEmail(
            "fake subject", "fake@localhost", "fake message"
        )
        server = alerts.SmtpServer(("localhost", 1))
        ret = server.Send(msg)
        self.assertFalse(ret)
        self.assertEqual(self.smtp_mock.call_count, 4)


class GmailServerTest(cros_test_lib.MockTempDirTestCase):
    """Tests for Gmail server."""

    FAKE_TOKEN_JSON = {
        "client_id": "fake_client_id",
        "client_secret": "fake_client_secret",
        "email": "fake_email@fake.com",
        "refresh_token": "fake_token",
        "scope": "https://fake_scope/auth/fake.modify",
    }
    FAKE_CACHE = {
        "_module": "oauth2client.client",
        "token_expiry": "2014-04-28T19:30:42Z",
        "access_token": "fake_access_token",
        "token_uri": "https://accounts.google.com/o/oauth2/token",
        "invalid": False,
        "token_response": {
            "access_token": "fake_access_token_2",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
        "client_id": "fake_client_id",
        "id_token": None,
        "client_secret": "fake_client_secret",
        "revoke_uri": None,
        "_class": "OAuth2Credentials",
        "refresh_token": "fake_refresh_token",
        "user_agent": None,
    }

    def setUp(self) -> None:
        self.PatchObject(alerts, "apiclient_build")
        self.token_cache_file = os.path.join(self.tempdir, "fake_cache")
        self.token_json_file = os.path.join(self.tempdir, "fake_json")

    def testValidCache(self) -> None:
        """Test valid cache."""
        osutils.WriteFile(self.token_cache_file, json.dumps(self.FAKE_CACHE))
        msg = alerts.CreateEmail("fake subject", "fake@localhost", "fake msg")
        server = alerts.GmailServer(token_cache_file=self.token_cache_file)
        ret = server.Send(msg)
        self.assertTrue(ret)

    def testCacheNotExistsTokenExists(self) -> None:
        """Test cache not exists, token exists"""
        osutils.WriteFile(
            self.token_json_file, json.dumps(self.FAKE_TOKEN_JSON)
        )
        msg = alerts.CreateEmail("fake subject", "fake@localhost", "fake msg")
        server = alerts.GmailServer(
            token_cache_file=self.token_cache_file,
            token_json_file=self.token_json_file,
        )
        ret = server.Send(msg)
        self.assertTrue(ret)
        # Cache file should be auto-generated.
        self.assertExists(self.token_cache_file)

    def testCacheNotExistsTokenNotExists(self) -> None:
        """Test cache not exists, token not exists."""
        msg = alerts.CreateEmail("fake subject", "fake@localhost", "fake msg")
        server = alerts.GmailServer(
            token_cache_file=self.token_cache_file,
            token_json_file=self.token_json_file,
        )
        ret = server.Send(msg)
        self.assertFalse(ret)

    def testCacheInvalidTokenExists(self) -> None:
        """Test cache exists but invalid, token exists."""
        invalid_cache = self.FAKE_CACHE.copy()
        invalid_cache["invalid"] = True
        osutils.WriteFile(self.token_cache_file, json.dumps(invalid_cache))
        osutils.WriteFile(
            self.token_json_file, json.dumps(self.FAKE_TOKEN_JSON)
        )
        msg = alerts.CreateEmail("fake subject", "fake@localhost", "fake msg")
        server = alerts.GmailServer(
            token_cache_file=self.token_cache_file,
            token_json_file=self.token_json_file,
        )
        ret = server.Send(msg)
        self.assertTrue(ret)
        valid_cache = json.loads(osutils.ReadFile(self.token_cache_file))
        self.assertFalse(valid_cache["invalid"])

    def testCacheInvalidTokenNotExists(self) -> None:
        """Test cache exists but invalid, token not exists."""
        invalid_cache = self.FAKE_CACHE.copy()
        invalid_cache["invalid"] = True
        osutils.WriteFile(self.token_cache_file, json.dumps(invalid_cache))
        msg = alerts.CreateEmail("fake subject", "fake@localhost", "fake msg")
        server = alerts.GmailServer(
            token_cache_file=self.token_cache_file,
            token_json_file=self.token_json_file,
        )
        ret = server.Send(msg)
        self.assertFalse(ret)
        invalid_cache = json.loads(osutils.ReadFile(self.token_cache_file))
        self.assertTrue(invalid_cache["invalid"])


class CreateEmailTest(cros_test_lib.TestCase):
    """Tests for CreateEmail."""

    def testBasic(self) -> None:
        """Check default basic call."""
        msg = alerts.CreateEmail("subj", ["fake@localhost"])
        self.assertIsNotNone(msg)
        self.assertNotEqual("", msg["From"])
        self.assertEqual("subj", msg["Subject"])
        self.assertEqual("fake@localhost", msg["To"])

    def testNoRecipients(self) -> None:
        """Check empty recipients behavior."""
        msg = alerts.CreateEmail("subj", [])
        self.assertIsNone(msg)

    def testMultipleRecipients(self) -> None:
        """Check multiple recipients behavior."""
        msg = alerts.CreateEmail("subj", ["fake1@localhost", "fake2@localhost"])
        self.assertEqual("fake1@localhost, fake2@localhost", msg["To"])

    def testExtraFields(self) -> None:
        """Check extra fields are added correctly."""
        msg = alerts.CreateEmail(
            "subj",
            ["fake@localhost"],
            extra_fields={"X-Hi": "bye", "field": "data"},
        )
        self.assertEqual("subj", msg["Subject"])
        self.assertEqual("bye", msg["X-Hi"])
        self.assertEqual("data", msg["field"])

    def testAttachment(self) -> None:
        """Check attachment behavior."""
        msg = alerts.CreateEmail("subj", ["fake@localhost"], attachment="blah")
        # Make sure there's a payload in there somewhere.
        self.assertTrue(
            any(
                isinstance(x, email.mime.application.MIMEApplication)
                for x in msg.get_payload()
            )
        )


class SendEmailTest(cros_test_lib.MockTestCase):
    """Tests for SendEmail."""

    def testSmtp(self) -> None:
        """Smtp check."""
        send_mock = self.PatchObject(alerts.SmtpServer, "Send")
        alerts.SendEmail("mail", "root@localhost")
        self.assertEqual(send_mock.call_count, 1)

    def testGmail(self) -> None:
        """Gmail check."""
        send_mock = self.PatchObject(alerts.GmailServer, "Send")
        alerts.SendEmail(
            "mail",
            "root@localhost",
            server=alerts.GmailServer(token_cache_file="fakefile"),
        )
        self.assertEqual(send_mock.call_count, 1)


class SendEmailLogTest(cros_test_lib.MockTestCase):
    """Tests for SendEmailLog()."""

    def testSmtp(self) -> None:
        """Smtp check."""
        send_mock = self.PatchObject(alerts.SmtpServer, "Send")
        alerts.SendEmailLog("mail", "root@localhost")
        self.assertEqual(send_mock.call_count, 1)

    def testGmail(self) -> None:
        """Gmail check."""
        send_mock = self.PatchObject(alerts.GmailServer, "Send")
        alerts.SendEmailLog(
            "mail",
            "root@localhost",
            server=alerts.GmailServer(token_cache_file="fakefile"),
        )
        self.assertEqual(send_mock.call_count, 1)
