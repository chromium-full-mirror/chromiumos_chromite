#!/usr/bin/env python3
# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import sys

from chromite.lib import cros_build_lib
from chromite.lib import depgraph

# Prints dependency tree dictionary to stdout as json-parsable.
# Dictionary structure: {
#   package_name_with_version: {
#     action: str
#     root: str
#     deps: {
#       deps_name: {
#         action: str
#         root: str
#         depttypes: List[str] (e.g. runtime, buildtime etc)
#       }
#     }
#   }
# }

cros_build_lib.AssertInsideChroot()

board = sys.argv[1]
packages = sys.argv[2:]

deps = depgraph.DepGraphGenerator()
deps.Initialize([f'--board={board}', '--quiet'] + packages)
deps_tree, _, _ = deps.GenDependencyTree()

print(json.dumps(deps_tree))
