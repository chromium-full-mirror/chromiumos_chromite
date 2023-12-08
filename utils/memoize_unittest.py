# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the memoize module."""

import functools

from chromite.lib import cros_test_lib
from chromite.utils import memoize


class SafeRunTest(cros_test_lib.TestCase):
    """Tests SafeRun functionality."""

    def _raise_exception(self, e) -> None:
        raise e

    def testRunsSafely(self) -> None:
        """Verify that we are robust to exceptions."""

        def append_val(value) -> None:
            call_list.append(value)

        call_list = []
        f_list = [
            functools.partial(append_val, 1),
            functools.partial(
                self._raise_exception, Exception("testRunsSafely exception.")
            ),
            functools.partial(append_val, 2),
        ]
        self.assertRaises(Exception, memoize.SafeRun, f_list)
        self.assertEqual(call_list, [1, 2])

    def testRaisesFirstException(self) -> None:
        """Verify we raise the first exception when multiple are encountered."""

        class E1(Exception):
            """Simple exception class."""

        class E2(Exception):
            """Simple exception class."""

        f_list = [functools.partial(self._raise_exception, e) for e in [E1, E2]]
        self.assertRaises(E1, memoize.SafeRun, f_list)

    def testCombinedRaise(self) -> None:
        """Raises a RuntimeError with exceptions combined."""
        f_list = [functools.partial(self._raise_exception, Exception())] * 3
        self.assertRaises(
            RuntimeError,
            memoize.SafeRun,
            f_list,
            combine_exceptions=True,
        )
