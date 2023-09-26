# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for prctl.py module."""

import ctypes
import signal

from chromite.utils import prctl


def test_pdeathsig():
    """Check basic functionality with PDEATHSIG option."""
    # This should be safe to play with as we should exit before the parent.
    assert prctl.prctl(prctl.Option.SET_PDEATHSIG, signal.SIGQUIT) == 0
    arg2 = ctypes.c_int(0)
    assert prctl.prctl(prctl.Option.GET_PDEATHSIG, ctypes.byref(arg2)) == 0
    assert arg2.value == signal.SIGQUIT
