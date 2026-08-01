# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the alerts.py module."""

import email
import smtplib
import socket

from chromite.lib import alerts
from chromite.lib import cros_test_lib


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


class SendEmailLogTest(cros_test_lib.MockTestCase):
    """Tests for SendEmailLog()."""

    def testSmtp(self) -> None:
        """Smtp check."""
        send_mock = self.PatchObject(alerts.SmtpServer, "Send")
        alerts.SendEmailLog("mail", "root@localhost")
        self.assertEqual(send_mock.call_count, 1)
