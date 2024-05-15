# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utility for formatting mojom files."""

import os
from typing import Optional, Union

from chromite.format import formatters
from chromite.lib import constants
from chromite.lib import cros_build_lib


def Data(
    data: str,
    # pylint: disable=unused-argument
    path: Optional[Union[str, os.PathLike]] = None,
) -> str:
    """Format mojom files.

    Args:
        data: The file content to format.
        path: The file name for diagnostics/configs/etc...

    Returns:
        Formatted data.
    """
    try:
        result = cros_build_lib.run(
            [
                constants.SOURCE_ROOT
                / "src/platform/libchrome"
                / "mojo/public/tools/mojom/mojom_format.py"
            ],
            capture_output=True,
            input=data,
            encoding="utf-8",
        )
        return result.stdout
    except cros_build_lib.RunCommandError as e:
        raise formatters.ParseError(path) from e
