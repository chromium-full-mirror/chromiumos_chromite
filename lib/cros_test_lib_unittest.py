# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittest for cros_test_lib (tests for tests? Who'd a thunk it)."""

import io
import logging
import subprocess
import time
import unittest
from unittest import mock

import pytest

from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock
from chromite.lib import timeout_util


# Convenience alias
Dir = cros_test_lib.Directory


class CrosTestCaseTest(cros_test_lib.TestCase):
    """Test the cros_test_lib.TestCase."""

    def testAssertStartsWith(self) -> None:
        s = "abcdef"
        prefix = "abc"
        self.assertStartsWith(s, prefix)
        prefix = "def"
        self.assertRaises(AssertionError, self.assertStartsWith, s, prefix)

    def testAssertEndsWith(self) -> None:
        s = "abcdef"
        suffix = "abc"
        self.assertRaises(AssertionError, self.assertEndsWith, s, suffix)
        suffix = "def"
        self.assertEndsWith(s, suffix)


class CreateOnDiskHierarchyTest(cros_test_lib.TempDirTestCase):
    """Test CreateOnDiskHierarchy."""

    def testBasic(self) -> None:
        """Basic testing."""
        D = cros_test_lib.Directory
        layout = (
            D(
                "dir",
                (D("subdir", ("subfile1", "subfile2")), D("empty"), "file1"),
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, layout)

        get_paths = lambda p: sorted(x.name for x in p.iterdir())
        assert get_paths(self.tempdir) == ["dir"]
        assert get_paths(self.tempdir / "dir") == ["empty", "file1", "subdir"]
        assert get_paths(self.tempdir / "dir" / "empty") == []
        assert get_paths(self.tempdir / "dir" / "subdir") == [
            "subfile1",
            "subfile2",
        ]

    def test_file_data(self) -> None:
        """Create files with contents."""
        D = cros_test_lib.Directory
        F = cros_test_lib.File
        layout = (
            D(
                "dir",
                (F("file", "data"),),
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, layout)

        f = self.tempdir / "dir" / "file"
        self.assertExists(f)
        assert f.read_text(encoding="utf-8") == "data"


class VerifyOnDiskHierarchyTest(cros_test_lib.TempDirTestCase):
    """Test VerifyOnDiskHierarchy."""

    def setUp(self) -> None:
        """Setup disk layout for testing.

        NB: Do not use CreateOnDiskHierarchy as it uses the same internal APIs
        as VerifyOnDiskHierarchy, so if one is broken, it's likely the other is
        too, so the test wouldn't catch anything.
        """
        d = self.tempdir / "dir"
        (d / "subdir").mkdir(parents=True)
        (d / "subdir" / "subfile1").touch()
        (d / "subdir" / "subfile2").touch()
        (d / "empty").mkdir()
        (d / "file1").touch()

        D = cros_test_lib.Directory
        self.layout = (
            D(
                "dir",
                (D("subdir", ("subfile1", "subfile2")), D("empty"), "file1"),
            ),
        )

    def testBasic(self) -> None:
        """Basic verify checks."""
        cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)

    def test_missing_file(self) -> None:
        """Fail due to missing files."""
        (self.tempdir / "dir" / "file1").unlink()
        with pytest.raises(AssertionError):
            cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)

    def test_missing_dir(self) -> None:
        """Fail due to missing dirs."""
        (self.tempdir / "dir" / "empty").rmdir()
        with pytest.raises(AssertionError):
            cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)

    def test_extra_file(self) -> None:
        """Fail due to extra files."""
        (self.tempdir / "dir" / "file3").touch()
        with pytest.raises(AssertionError):
            cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)

    def test_extra_dir(self) -> None:
        """Fail due to extra dirs."""
        (self.tempdir / "dir" / "dirdir").mkdir()
        with pytest.raises(AssertionError):
            cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)

    def test_extra_hidden_file(self) -> None:
        """Fail due to extra "hidden" files."""
        (self.tempdir / "dir" / ".file").touch()
        with pytest.raises(AssertionError):
            cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)

    def test_create_verify_roundtrip(self) -> None:
        """Create should match verify."""
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, self.layout)
        cros_test_lib.VerifyOnDiskHierarchy(self.tempdir, self.layout)


class VerifyTarballTest(cros_test_lib.MockTempDirTestCase):
    """Test tarball verification functionality."""

    def setUp(self) -> None:
        self.tarball = self.tempdir / "fake_tarball.tar"
        self.tarball.write_bytes(b"ustar\0")
        self.rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())

    def _MockTarList(self, files) -> None:
        """Mock out tarball content list call.

        Args:
            files: A list of contents to return.
        """
        self.rc_mock.AddCmdResult(
            partial_mock.ListRegex("tar .*-tf"), stdout="\n".join(files)
        )

    def testNormPath(self) -> None:
        """Test path normalization."""
        tar_contents = ["./", "./foo/", "./foo/./a", "./foo/./b"]
        dir_struct = [Dir("."), Dir("foo", ["a", "b"])]
        self._MockTarList(tar_contents)
        cros_test_lib.VerifyTarball(self.tarball, dir_struct)

    def testDuplicate(self) -> None:
        """Test duplicate detection."""
        tar_contents = ["a", "b", "a"]
        dir_struct = ["a", "b"]
        self._MockTarList(tar_contents)
        self.assertRaises(
            AssertionError,
            cros_test_lib.VerifyTarball,
            self.tarball,
            dir_struct,
        )


class MockTestCaseTest(cros_test_lib.TestCase):
    """Tests MockTestCase functionality."""

    class MyMockTestCase(cros_test_lib.MockTestCase):
        """Helper class for testing MockTestCase."""

        def testIt(self) -> None:
            pass

    class Mockable:
        """Helper test class intended for having values mocked out."""

        TO_BE_MOCKED = 0
        TO_BE_MOCKED2 = 10
        TO_BE_MOCKED3 = 20

    def GetPatcher(self, attr, val):
        return mock.patch(
            "%s.MockTestCaseTest.Mockable.%s" % (__name__, attr), new=val
        )

    def testPatchRemovalError(self) -> None:
        """Verify that patch removal during tearDown is robust to Exceptions."""
        tc = self.MyMockTestCase("testIt")
        patcher = self.GetPatcher("TO_BE_MOCKED", -100)
        patcher2 = self.GetPatcher("TO_BE_MOCKED2", -200)
        patcher3 = self.GetPatcher("TO_BE_MOCKED3", -300)
        patcher3.start()
        tc.setUp()
        tc.StartPatcher(patcher)
        tc.StartPatcher(patcher2)
        patcher.stop()
        self.assertEqual(self.Mockable.TO_BE_MOCKED2, -200)
        self.assertEqual(self.Mockable.TO_BE_MOCKED3, -300)

        def abort() -> None:
            raise RuntimeError()

        patcher.stop = abort
        self.assertRaises(RuntimeError, tc.tearDown)
        # Make sure that even though exception is raised for stopping 'patcher',
        # we continue to stop 'patcher2', and run patcher.stopall().
        self.assertEqual(self.Mockable.TO_BE_MOCKED2, 10)
        self.assertEqual(self.Mockable.TO_BE_MOCKED3, 20)


class TestCaseTest(unittest.TestCase):
    """Tests TestCase functionality."""

    def testTimeout(self) -> None:
        """Test that test cases are interrupted when they are hanging."""

        class TimeoutTestCase(cros_test_lib.TestCase):
            """Raises a TimeoutError because it takes too long."""

            TEST_CASE_TIMEOUT = 1

            def testSleeping(self) -> None:
                """Sleep for 2 minutes. This should raise a TimeoutError."""
                time.sleep(2 * 60)
                raise AssertionError("Test case should have timed out.")

        # Run the test case, verifying it raises a TimeoutError.
        test = TimeoutTestCase(methodName="testSleeping")
        self.assertRaises(timeout_util.TimeoutError, test.testSleeping)


class RunCommandTestCase(cros_test_lib.RunCommandTestCase):
    """Verify the test case behavior."""

    def testPopenMockEncodingEmptyStrings(self) -> None:
        """Verify automatic encoding in PopenMock works with default output."""
        self.rc.AddCmdResult(["/x"])
        result = cros_build_lib.run(["/x"], capture_output=True)
        self.assertEqual(b"", result.stdout)
        self.assertEqual(b"", result.stderr)
        result = cros_build_lib.run(
            ["/x"], capture_output=True, encoding="utf-8"
        )
        self.assertEqual("", result.stdout)
        self.assertEqual("", result.stderr)

    def testPopenMockBinaryData(self) -> None:
        """Verify our automatic encoding in PopenMock works with bytes."""
        self.rc.AddCmdResult(["/x"], stderr=b"\xff")
        result = cros_build_lib.run(["/x"], capture_output=True)
        self.assertEqual(b"", result.stdout)
        self.assertEqual(b"\xff", result.stderr)
        with self.assertRaises(UnicodeDecodeError):
            cros_build_lib.run(["/x"], capture_output=True, encoding="utf-8")

    def testPopenMockMixedData(self) -> None:
        """Verify our automatic encoding in PopenMock works with mixed data."""
        self.rc.AddCmdResult(["/x"], stderr=b"abc\x00", stdout="Yes\u20a0")
        result = cros_build_lib.run(["/x"], capture_output=True)
        self.assertEqual(b"Yes\xe2\x82\xa0", result.stdout)
        self.assertEqual(b"abc\x00", result.stderr)
        result = cros_build_lib.run(
            ["/x"], capture_output=True, encoding="utf-8"
        )
        self.assertEqual("Yes\u20a0", result.stdout)
        self.assertEqual("abc\x00", result.stderr)

    def testPopenMockCombiningStderr(self) -> None:
        """Verify combining stderr into stdout works."""
        self.rc.AddCmdResult(["/x"], stderr="err", stdout="out")
        result = cros_build_lib.run(["/x"], stdout=True, stderr=True)
        self.assertEqual(b"err", result.stderr)
        self.assertEqual(b"out", result.stdout)
        result = cros_build_lib.run(
            ["/x"], stdout=True, stderr=subprocess.STDOUT
        )
        self.assertEqual(None, result.stderr)
        self.assertEqual(b"outerr", result.stdout)

    def testExecutable(self) -> None:
        """Verify executable arg is handled."""
        self.rc.AddCmdResult(["/x"], stderr="err", stdout="out")
        result = cros_build_lib.run(
            ["/x"], executable="/exe", stdout=True, stderr=True
        )
        self.assertEqual(b"err", result.stderr)
        self.assertEqual(b"out", result.stdout)


def test_logging_notice() -> None:
    """Test logging.notice works and is between INFO and WARNING.

    This is testing chromite/__init__.py, but we don't have a great place to
    hold those tests, so here it lives.
    """
    logger = logging.getLogger()
    stream = io.StringIO()
    logger.addHandler(logging.StreamHandler(stream))

    logger.setLevel(logging.INFO)
    logging.notice("info level")
    logger.setLevel(logging.NOTICE)
    logging.notice("notice level")
    logger.setLevel(logging.WARNING)
    logging.notice("warning level")
    output = stream.getvalue()
    assert "info level" in output
    assert "notice level" in output
    assert "warning level" not in output
