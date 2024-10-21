# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Shell (e.g. bash) linter."""

import functools
import os

from chromite.lib import cipd


@functools.lru_cache(maxsize=None)
def _find_shellcheck() -> str:
    """Find the `shellcheck` tool."""
    path = cipd.InstallPackage(
        cipd.GetCIPDFromCache(),
        "chromiumos/infra/tools/shellcheck",
        # Version: dev-util/shellcheck-0.8.0-r71. This should match the pin in
        # https://crsrc.org/i/go/src/infra/tricium/functions/shellcheck/shellcheck_ensure
        "EnJJFRar24HNIJJg9fhqin6jiIfS1Mi7XQc9jLLfe_QC",
    )
    return os.path.join(path, "bin", "shellcheck")
