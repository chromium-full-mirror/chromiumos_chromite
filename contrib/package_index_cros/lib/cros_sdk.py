# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import List

from chromite.lib import cros_build_lib

from .constants import PRINT_DEPS_SCRIPT_PATH
from .logger import g_logger
from .path_handler import PathHandler
from .setup import Setup


class CrosSdk:
  """Handles requests to cros_sdk."""

  def _Exec(self,
            cmd: List[str],
            *,
            capture_output: bool = False,
            with_sudo: bool = False) -> cros_build_lib.CompletedProcess:
    shell = True
    if isinstance(cmd, List):
      shell = False

    encoding = 'utf-8' if capture_output else None

    g_logger.debug("Executing: '%s'", cmd)
    run_func = (
        self.setup.chroot.sudo_run if with_sudo else self.setup.chroot.run)
    res = run_func(
        cmd,
        shell=shell,
        capture_output=capture_output,
        encoding=encoding,
        check=True,
        print_cmd=False)
    return res

  def __init__(self, setup: Setup):
    self.setup = setup

  def BuildPackages(self, package_names: List[str]) -> None:
    """
    Builds given packages and preserves build artifcats.

    Raises:
      * cros_build_lib.CompletedProcess if command failed.
    """
    features = ['noclean']
    if self.setup.with_tests:
      features.append('test')
    cmd = ' '.join([
        f'FEATURES="{" ".join(features)}"', 'parallel_emerge', '--board',
        self.setup.board
    ] + package_names)
    self._Exec(cmd, with_sudo=True)

  def GenerateCompileCommands(self, chroot_build_dir: str) -> str:
    """
    Calls ninja and returns compile commands as a string.

    |chroot_build_dir|  is package's build dir inside chroot.

    Raises:
      * cros_build_lib.CompletedProcess if command failed.
    """
    ninja_cmd = ['ninja', '-C', chroot_build_dir, '-t', 'compdb', 'cc', 'cxx']

    return self._Exec(ninja_cmd, capture_output=True).stdout

  def GenerateGnTargets(self, chroot_root_dir: str,
                        chroot_build_dir: str) -> str:
    """
    Calls gn desc and returns gn targets as a string.

    |chroot_root_dir| is a package's dir containing upper most .gn file inside
    chroot.
    |chroot_build_dir| is a package's build dir inside chroot.

    Raises:
      * cros_build_lib.CompletedProcess if command failed.
    """
    gn_desc_cmd = [
        'gn',
        'desc',
        f"--root={chroot_root_dir}",
        chroot_build_dir,
        '*',
        '--format=json',
    ]

    return self._Exec(gn_desc_cmd, capture_output=True).stdout

  def GenerateDependencyTree(self, package_names: List[str]):
    """
    Generates dependency tree for given packages.

    Returns a dictionary with dependencies (see script/print_deps.py for
    detailed format).

    Utilizes chromite.lib.depgraph to fetch dependency tree. Depgraph has to be
    called from inside chroot so it lives in separate script file which is
    called via cros_sdk wrapper.

    Raises:
      * cros_build_lib.CompletedProcess if command failed.
    """

    features = []
    if self.setup.with_tests:
      features.append('test')
    cmd = ' '.join([
        f'FEATURES="{" ".join(features)}"',
        PathHandler(self.setup).ToChroot(PRINT_DEPS_SCRIPT_PATH),
        self.setup.board
    ] + package_names)
    return self._Exec(cmd, capture_output=True, with_sudo=True).stdout
