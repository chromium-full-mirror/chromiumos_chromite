# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the upstart module."""

from chromite.lib import cros_test_lib
from chromite.lint.linters import upstart
from chromite.utils.parser import upstart as upstart_parser


class CheckForRequiredLinesTest(cros_test_lib.TestCase):
    """Test the functionality of the required lines check."""

    def testOneNotPresent(self) -> None:
        """Check the case some are present and some are not."""
        job = upstart_parser.parse(
            """
            author ""
            description ""
            """
        )
        self.assertFalse(
            upstart.CheckForRequiredLines(
                job,
                "test-string",
            ),
        )

    def testNonePresent(self) -> None:
        """Check the case none are present."""
        job = upstart_parser.parse("")
        self.assertFalse(
            upstart.CheckForRequiredLines(
                job,
                "test-string",
            ),
        )

    def testAllPresent(self) -> None:
        """Check the case all are present."""
        job = upstart_parser.parse(
            """
            author ""
            description ""
            oom score 10
            """
        )

        self.assertTrue(
            upstart.CheckForRequiredLines(
                job,
                "test-string",
            ),
        )


class ExtractCommandsTest(cros_test_lib.TestCase):
    """Test the functionality of the command extractor."""

    def testEmpty(self) -> None:
        """Make sure an empty string doesn't break anything."""
        job = upstart_parser.parse("")
        self.assertEqual(list(upstart.ExtractCommands(job)), [])

    def testMultipleSingleLineCommands(self) -> None:
        """Check that single-line commands are handled as expected."""
        job = upstart_parser.parse(
            """
pre-start script
  mkdir -p /run/upstart-test; `chmod 0750 /run/upstart-test`
  echo test && $(chown test:test /run/upstart-test)
end script
"""
        )
        self.assertEqual(
            list(upstart.ExtractCommands(job)),
            [
                ["mkdir", "-p", "/run/upstart-test"],
                ["`chmod", "0750", "/run/upstart-test`"],
                ["$(chown", "test:test", "/run/upstart-test)"],
            ],
        )

    def testMultilineCommands(self) -> None:
        """Check that multi-line commands are handled as expected."""
        job = upstart_parser.parse(
            """
pre-start script
  mkdir \
    -p \
    /run/upstart-test
  `chmod \
    0750 \
    /run/upstart-test`
  $(chown \
    test:test \
    /run/upstart-test) && touch /run/upstart-test/done
end script
"""
        )
        self.assertEqual(
            list(upstart.ExtractCommands(job)),
            [
                ["mkdir", "-p", "/run/upstart-test"],
                ["`chmod", "0750", "/run/upstart-test`"],
                [
                    "$(chown",
                    "test:test",
                    "/run/upstart-test)",
                    "&&",
                    "touch",
                    "/run/upstart-test/done",
                ],
            ],
        )

    def testDisable(self) -> None:
        """Check that commands with '# croslint: disable' are ignored"""
        job = upstart_parser.parse(
            """
pre-start script
  mkdir \
    -p \
    /run/upstart-test
  chmod \
    0750 \
    /run/upstart-test  # croslint: disable because...
  chown \
    test:test \
    /run/upstart-test
end script
"""
        )
        self.assertEqual(
            list(upstart.ExtractCommands(job)),
            [
                ["mkdir", "-p", "/run/upstart-test"],
                ["chown", "test:test", "/run/upstart-test"],
            ],
        )
