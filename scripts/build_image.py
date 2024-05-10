# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Deprecated entry point for "cros build-image".

This script will be deleted soon.
"""

import sys
from typing import List, Optional

from chromite.lib import cros_build_lib
from chromite.utils import shell_util


def main(argv: Optional[List[str]]) -> Optional[int]:
    """Wrapper main to call "cros build-image"."""
    argv = argv or sys.argv[1:]
    new_argv = ["build-image", *argv]
    new_command_str = shell_util.cmd_to_str(["cros", *new_argv])
    cros_build_lib.Die(
        "build_image has been renamed to `cros build-image`.  Please call"
        f" as `{new_command_str}`."
    )
