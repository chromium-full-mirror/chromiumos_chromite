#!/usr/bin/env vpython3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Wrapper to run libcst.tool.

See the libcst docs for help:
https://libcst.readthedocs.io/en/latest/index.html
"""

# [VPYTHON:BEGIN]
# python_version: "3.11"
#
# wheel: <
#   name: "infra/python/wheels/libcst/linux-amd64_cp311_cp311"
#   version: "version:1.1.0"
# >
# wheel: <
#   name: "infra/python/wheels/typing-extensions-py3"
#   version: "version:4.0.1"
# >
# wheel: <
#   name: "infra/python/wheels/typing-inspect-py3"
#   version: "version:0.7.1"
# >
# wheel: <
#   name: "infra/python/wheels/pyyaml-py3"
#   version: "version:5.3.1"
# >
# wheel: <
#   name: "infra/python/wheels/mypy-py3"
#   version: "version:1.2.0"
# >
# wheel: <
#   name: "infra/python/wheels/mypy-extensions-py3"
#   version: "version:1.0.0"
# >
# [VPYTHON:END]

import importlib.util
from pathlib import Path
import sys
from typing import List, Optional

import libcst.tool


CHROMITE_DIR = Path(__file__).resolve().parent.parent


def main(argv: Optional[List[str]]) -> Optional[int]:
    """Entry point to call libcst.tool."""
    return libcst.tool.main(sys.argv[0], argv)


if __name__ == "__main__":
    wrapper3_spec = importlib.util.spec_from_file_location(
        "wrapper3", CHROMITE_DIR / "scripts" / "wrapper3.py"
    )
    wrapper3 = importlib.util.module_from_spec(wrapper3_spec)
    wrapper3_spec.loader.exec_module(wrapper3)
    wrapper3.DoMain()
