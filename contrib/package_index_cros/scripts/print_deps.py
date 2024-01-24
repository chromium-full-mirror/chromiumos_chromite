# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script that prints a package's dependency tree to stdout as JSON.

The output dictionary is structured as follows:
{
    package_name_with_version: {
        action: str
        root: str
        deps: {
            deps_name: {
                action: str
                root: str
                deptypes: List[str] (e.g. runtime, buildtime, etc.)
            }
        }
    }
}
"""

import argparse
import json
from typing import List, Optional

from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import depgraph


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = commandline.ArgumentParser()
    parser.add_argument("board")
    parser.add_argument("packages", nargs="*")
    return parser.parse_args(argv)


def main(argv: List[str]) -> Optional[int]:
    cros_build_lib.AssertInsideChroot()
    opts = _parse_args(argv)

    deps = depgraph.DepGraphGenerator()
    deps.Initialize([f"--board={opts.board}", "--quiet", *opts.packages])
    deps_tree, _, _ = deps.GenDependencyTree()

    print(json.dumps(deps_tree))
    return 0
