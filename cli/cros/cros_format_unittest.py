# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module tests the cros format command."""

from pathlib import Path

from chromite.cli.cros import cros_format
from chromite.format import formatters
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.scripts import cros


# pylint: disable=protected-access


class FormatCommandTestCase(cros_test_lib.TestCase):
    """Utils for testing the format subcommand."""

    def setUp(self):
        # Set up default options for tests to play with for running cros format.
        self._parser = cros.GetOptions("format")
        self.options = self.parse_args([])

    def parse_args(self, args, **kwargs):
        return self._parser.parse_args(["format"] + args, **kwargs)


class FormatCommandTest(FormatCommandTestCase):
    """Tests that don't involve real files."""

    def testBreakoutFilesByTool(self):
        """Check extension<->tool mapping."""
        self.assertEqual({}, cros_format._BreakoutFilesByTool([]))
        self.assertEqual(
            {},
            cros_format._BreakoutFilesByTool([Path("foo"), Path("blah.xxx")]),
        )

        tool_map = cros_format._BreakoutFilesByTool([Path("foo.md")])
        # It's not easy to test the tool_map as the keys are functools partials
        # which do not support equality tests.
        items = list(tool_map.items())
        self.assertEqual(len(items), 1)
        key, value = items[0]
        self.assertEqual(key.func, formatters.whitespace.Data.func)
        self.assertEqual(value, [Path("foo.md")])

    def testCliNoFiles(self):
        """Check cros format handling with no files."""
        cmd = cros_format.FormatCommand(self.options)
        self.assertEqual(0, cmd.Run())

    def testCliNoMatchedFiles(self):
        """Check cros format handling with no matched files."""
        self.options.files = [Path("foo")]
        cmd = cros_format.FormatCommand(self.options)
        self.assertEqual(0, cmd.Run())


class FormatCommandTempDirTests(
    FormatCommandTestCase, cros_test_lib.TempDirTestCase
):
    """Tests that use real files."""

    def testCliOneFile(self):
        """Check behavior with one file."""
        file = self.tempdir / "foo.txt"
        osutils.Touch(file)
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(0, cmd.Run())

    def testCliDir(self):
        """Test the CLI expands directories when given one."""
        files = [self.tempdir / "foo.txt", self.tempdir / "bar.txt"]
        for file in files:
            osutils.Touch(file)
        opts = self.parse_args([str(self.tempdir)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(0, cmd.Run())

    def testCliManyFile(self):
        """Check behavior with many files."""
        files = []
        for n in range(0, 10):
            file = self.tempdir / f"foo.{n}.txt"
            osutils.Touch(file)
            files.append(str(file))
        opts = self.parse_args(files)
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(0, cmd.Run())

    def testDiffFile(self):
        """Check behavior with --diff file."""
        file = self.tempdir / "foo.txt"
        file.write_text(" ", encoding="utf-8")
        opts = self.parse_args(["--diff", str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())
        self.assertEqual(" ", file.read_text(encoding="utf-8"))

    def testCheckFile(self):
        """Check behavior with --check file."""
        file = self.tempdir / "foo.txt"
        file.write_text(" ", encoding="utf-8")
        for arg in ("-n", "--dry-run", "--check"):
            opts = self.parse_args([arg, str(file)])
            cmd = cros_format.FormatCommand(opts)
            self.assertEqual(1, cmd.Run())
            self.assertEqual(" ", file.read_text(encoding="utf-8"))

    def checkMultipleFiles(self, contents, expected_ret):
        """Helper to check behavior with --check with multiple files."""
        files = []
        for i, content in enumerate(contents):
            file = self.tempdir / f"foo.{i}.txt"
            files.append(str(file))
            file.write_text(content, encoding="utf-8")
        for arg in ("-n", "--dry-run", "--check"):
            opts = self.parse_args([arg, *files])
            cmd = cros_format.FormatCommand(opts)
            self.assertEqual(cmd.Run(), expected_ret)

    def testCheckMultipleFilesWithFirstBroken(self):
        """Check --check fails when the first supplied file is broken."""
        self.checkMultipleFiles([" ", ""], 1)

    def testCheckMultipleFilesWithLastBroken(self):
        """Check --check fails when the last supplied file is broken."""
        self.checkMultipleFiles(["", " "], 1)

    def testStdoutFile(self):
        """Check behavior with --stdout file."""
        file = self.tempdir / "foo.txt"
        file.write_text(" ", encoding="utf-8")
        opts = self.parse_args(["--stdout", str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())
        self.assertEqual(" ", file.read_text(encoding="utf-8"))

    def testInplaceFile(self):
        """Check behavior with --inplace file."""
        file = self.tempdir / "foo.txt"
        file.write_text(" ", encoding="utf-8")
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(0, cmd.Run())
        self.assertEqual("", file.read_text(encoding="utf-8"))

    def testMissingFile(self):
        """Check behavior with missing files."""
        file = self.tempdir / "foo.py"
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())

    def testUnicodeError(self):
        """Check binary files don't crash."""
        file = self.tempdir / "foo.txt"
        file.write_bytes(b"\xff")
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())

    def testParseErrorJson(self):
        """Check JSON parsing errors don't crash."""
        file = self.tempdir / "foo.json"
        file.write_bytes(b"{")
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())

    def testParseErrorPython(self):
        """Check Python parsing errors don't crash."""
        file = self.tempdir / "foo.py"
        file.write_bytes(b"'")
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())

    def testParseErrorXml(self):
        """Check XML parsing errors don't crash."""
        file = self.tempdir / "foo.xml"
        file.write_bytes(b"<")
        opts = self.parse_args([str(file)])
        cmd = cros_format.FormatCommand(opts)
        self.assertEqual(1, cmd.Run())
