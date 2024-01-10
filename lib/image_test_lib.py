# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Functions related to image tests."""

import enum
import unittest


# Symlinks to mounted partitions.
ROOT_A = "dir-ROOT-A"
STATEFUL = "dir-STATE"


class ImageType(enum.Enum):
    """The image we are testing."""

    # A chromeos image file to test
    BIN_FILE = enum.auto()
    # A path in the filesystem to test.
    BIND_MOUNT = enum.auto()


class _ImageTestMixin:
    """A mixin to hold image test's specific info."""

    _board = None
    _image_type: ImageType = None
    _result_dir = None

    def SetBoard(self, board) -> None:
        self._board = board

    def SetImageType(self, image_type: ImageType) -> None:
        self._image_type = image_type

    def SetResultDir(self, result_dir) -> None:
        self._result_dir = result_dir


class ImageTestCase(unittest.TestCase, _ImageTestMixin):
    """Subclass unittest.TestCase to provide utility methods for image tests.

    Tests MUST use prefix "Test" (e.g.: TestLinkage, TestDiskSpace), not "test"
    prefix, in order to be picked up by the test runner.

    Tests are run inside chroot. Tests are run as root. DO NOT modify any
    mounted partitions.

    The current working directory is set up so that "ROOT_A", and "STATEFUL"
    constants refer to the mounted partitions. The partitions are mounted
    readonly.

        current working directory
            + ROOT_A
                + /
                    + bin
                    + etc
                    + usr
                    ...
            + STATEFUL
                + var_overlay
                ...
    """


class ImageTestSuite(unittest.TestSuite, _ImageTestMixin):
    """Wrap around unittest.TestSuite to pass more info to the actual tests."""

    def run(self, result, debug=False):
        for t in self._tests:
            t.SetResultDir(self._result_dir)
            t.SetImageType(self._image_type)
            t.SetBoard(self._board)
        return super().run(result)


class ImageTestRunner(unittest.TextTestRunner, _ImageTestMixin):
    """Wrap around unittest.TextTestRunner to pass more info down the chain."""

    def run(self, test):
        test.SetResultDir(self._result_dir)
        test.SetBoard(self._board)
        test.SetImageType(self._image_type)
        return super().run(test)
