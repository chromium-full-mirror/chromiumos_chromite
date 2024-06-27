# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for builder.py."""

from chromite.lib import build_target_lib
from chromite.lib import cros_test_lib
from chromite.lib import gmerge_binhost


# pylint: disable=protected-access


class GmergeBinhostTest(cros_test_lib.TestCase):
    """Tests for gmerge_binhost."""

    def testUpdateGmergeBinhost(self):
        # Use the SDK sysroot, since we can't rely on having already built
        # packages for a particular board.
        sysroot = build_target_lib.get_default_sysroot_path()
        assert gmerge_binhost.update_gmerge_binhost(
            sysroot, ["sys-libs/glibc"], False
        )
