# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helpers for handling the C library via ctypes."""

import ctypes
import ctypes.util
import functools


# TODO(python3.9): Change to functools.cache.
@functools.lru_cache(maxsize=None)
def GetLibc() -> ctypes.CDLL:
    """Retrieve the C library via ctypes.

    With caching, since the ctypes lookup can be slow.
    """
    return ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
