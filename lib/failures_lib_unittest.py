# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the failures_lib module."""

from chromite.lib import cros_test_lib
from chromite.lib import failures_lib


class CompoundFailureTest(cros_test_lib.TestCase):
    """Test the CompoundFailure class."""

    def _CreateExceptInfos(self, cls, message="", traceback="", num=1):
        """A helper function to create a list of ExceptInfo objects."""
        exc_infos = []
        for _ in range(num):
            exc_infos.extend(
                failures_lib.CreateExceptInfo(cls(message), traceback)
            )

        return exc_infos

    def testMessageContainsAllInfo(self) -> None:
        """Tests that by default, all information is included in the message."""
        exc_infos = self._CreateExceptInfos(
            KeyError, message="bar1", traceback="foo1"
        )
        exc_infos.extend(
            self._CreateExceptInfos(
                ValueError, message="bar2", traceback="foo2"
            )
        )
        exc = failures_lib.CompoundFailure(exc_infos=exc_infos)
        self.assertIn("bar1", str(exc))
        self.assertIn("bar2", str(exc))
        self.assertIn("KeyError", str(exc))
        self.assertIn("ValueError", str(exc))
        self.assertIn("foo1", str(exc))
        self.assertIn("foo2", str(exc))


class ExceptInfoTest(cros_test_lib.TestCase):
    """Tests the namedtuple class ExceptInfo."""

    def testConvertToExceptInfo(self) -> None:
        """Tests converting an exception to an ExceptInfo object."""
        traceback = "Stub traceback"
        message = "Taco is not a valid option!"
        except_infos = failures_lib.CreateExceptInfo(
            ValueError(message), traceback
        )

        self.assertEqual(except_infos[0].type, ValueError)
        self.assertEqual(except_infos[0].str, message)
        self.assertEqual(except_infos[0].traceback, traceback)
