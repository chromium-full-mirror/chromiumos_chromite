# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utility for formatting Rust code."""

import functools
import itertools
import os
from pathlib import Path
import re
from typing import Optional, Union

from chromite.lib import cipd
from chromite.lib import cros_build_lib


# The latest edition the prebuilt rustfmt tool supports.
DEFAULT_EDITION = "2024"


@functools.lru_cache(maxsize=None)
def _find_rustfmt() -> str:
    """Find the `rustfmt` tool."""
    path = cipd.InstallPackage(
        cipd.GetCIPDFromCache(),
        "chromiumos/infra/tools/rustfmt",
        "kwdBZ5MSo7uVIU3EJG-JYRvXKk-VfcEgpXGUIgSZBdwC",
    )
    return os.path.join(path, "bin", "rustfmt")


def _find_edition(path: Path) -> str:
    """Find the Rust edition from Cargo.toml in path or parents."""
    for parent in itertools.chain([path], path.parents):
        cargo_toml = parent / "Cargo.toml"
        content = ""
        try:
            content = cargo_toml.read_text(encoding="utf-8")
        except FileNotFoundError:
            pass
        match = re.search(r'edition\s*=\s*"([^"]+)"', content)
        if match:
            return match.group(1)
    return DEFAULT_EDITION


def Data(
    data: str,
    path: Optional[Union[str, os.PathLike]] = None,
) -> str:
    """Clean up Rust format problems in |data|.

    Args:
        data: The file content to lint.
        path: The file name for diagnostics/configs/etc...

    Returns:
        Formatted data.
    """
    edition = DEFAULT_EDITION
    if path is not None:
        # The path may not exist since the file can be from git history. Look up
        # for existing directory.
        path = Path(path).resolve()
        while not path.is_dir():
            path = path.parent
        edition = _find_edition(path)
    result = cros_build_lib.run(
        [_find_rustfmt(), "--edition", edition],
        capture_output=True,
        cwd=path,
        input=data,
        encoding="utf-8",
    )
    return result.stdout
