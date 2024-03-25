# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module provides functionality to work with the CrOS SDK."""

import logging
from typing import Dict, List, Optional, Union

from chromite.contrib.package_index_cros.lib import constants
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import cros_build_lib


class CrosSdk:
    """Handler for requests to the ChromiumOS SDK."""

    def _exec(
        self,
        cmd: Union[List[str], str],
        *,
        extra_env: Optional[Dict[str, str]] = None,
        with_sudo: bool = False,
    ) -> cros_build_lib.CompletedProcess:
        """Execute a command inside the chroot."""
        run_func = (
            self.setup.chroot.sudo_run if with_sudo else self.setup.chroot.run
        )
        return run_func(
            cmd,
            extra_env=extra_env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data

    def generate_compile_commands(self, chroot_build_dir: str) -> str:
        """Call ninja and return compile commands as a string.

        Args:
            chroot_build_dir: A package's build dir, inside the chroot.

        Raises:
            cros_build_lib.CalledProcessError: Command failed.
        """
        ninja_cmd = [
            "ninja",
            "-C",
            chroot_build_dir,
            "-t",
            "compdb",
            "cc",
            "cxx",
        ]
        return self._exec(ninja_cmd).stdout

    def generate_dependency_tree(self, package_names: List[str]):
        """Generate the dependency tree for the given packages.

        Utilizes chromite.lib.depgraph to fetch dependency tree. Depgraph has to
        be called from inside chroot, so it lives in separate script file which
        is called via cros_sdk wrapper.

        Returns:
            A dictionary with dependencies. See script/print_deps.py for the
            detailed format.

        Raises:
            cros_build_lib.CalledProcessError: Command failed.
        """

        extra_env = {}
        if self.setup.with_tests:
            extra_env["FEATURES"] = "test"
        log_level = logging.getLevelName(logging.getLogger().level).lower()
        cmd = [
            path_handler.PathHandler(self.setup).to_chroot(
                constants.PRINT_DEPS_SCRIPT_PATH
            ),
            self.setup.board,
            *package_names,
            f"--log-level={log_level}",
        ]
        logging.info(cmd)
        return self._exec(cmd, extra_env=extra_env, with_sudo=True).stdout
