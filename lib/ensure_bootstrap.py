# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Ensure tools have been bootstrapped from the network.

This allows bootstrapping tools that chromite utilizes before disabling network
access.
"""

import functools
from pathlib import Path

from chromite.api import compile_build_api_proto
from chromite.format import formatters
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import gs
from chromite.lib import parallel
from chromite.lib import qemu
from chromite.lint import linters
from chromite.scripts import clang_format


# pylint: disable=protected-access


def _vpython_bootstrap(spec: Path) -> None:
    """Bootstrap a vpython spec."""
    cros_build_lib.dbg_run(
        ["vpython3", "-vpython-tool", "install", spec], capture_output=True
    )


@functools.lru_cache(maxsize=None)
def for_format() -> None:
    """Ensure formatting tools have been bootstrapped from the network."""

    def _find_clang_format() -> None:
        with clang_format.ClangFormat():
            pass

    parallel.RunParallelSteps(
        [
            functools.partial(
                _vpython_bootstrap,
                constants.CHROMITE_SCRIPTS_DIR / "black",
            ),
            functools.partial(
                _vpython_bootstrap,
                constants.CHROMITE_SCRIPTS_DIR / "isort",
            ),
            formatters.gn._find_gn,
            formatters.rust._find_rustfmt,
            formatters.star._find_buildifier,
            formatters.textproto._find_txtpbfmt,
            _find_clang_format,
        ]
    )


@functools.lru_cache(maxsize=None)
def for_lint() -> None:
    """Ensure linting tools have been bootstrapped from the network."""
    formatters.gn._find_gn()
    linters.shell._find_shellcheck()


@functools.lru_cache(maxsize=None)
def for_everything() -> None:
    """Ensure tools have been bootstrapped from the network."""
    # pylint: disable=protected-access
    gs.GSContext.InitializeCache()

    # Ensure protoc is installed for api/compile_build_api_proto_unittest.
    compile_build_api_proto.InstallProtoc(
        compile_build_api_proto.ProtocVersion.CHROMITE
    )

    _vpython_bootstrap(constants.CHROMITE_SCRIPTS_DIR / "mypy")

    for_format()
    for_lint()

    qemu.InstallFromCipd()
