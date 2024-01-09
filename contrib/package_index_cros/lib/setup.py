# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
from pathlib import Path
from typing import List, Optional

from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import git
from chromite.lib import path_util
from chromite.lib import repo_util

from .constants import PACKAGE_ROOT_DIR


class Setup:
  """
  POD to keep all data related to a setup:
    * board
    * cros_dir: absolute path to chromeos checkout root dir
    * chroot_dir: absolute path to chroot dir
    * chroot_out_dir: absolute path to chroot output dir
    * src_dir: absolute path to src
    * manifest: manifest handler
  """

  def __init__(self,
               board: str,
               *,
               skip_packages: Optional[List[str]] = None,
               with_build: bool = False,
               with_tests: bool = False,
               chroot_dir: str = "",
               chroot_out_dir: str = ""):
    self.board = board

    checkout_info = path_util.DetermineCheckout(PACKAGE_ROOT_DIR)
    if checkout_info.type != path_util.CheckoutType.REPO:
      raise repo_util.NotInRepoError(
          'Script is executed outside of ChromeOS checkout')

    self.cros_dir = checkout_info.root
    if chroot_dir:
      self.chroot = chroot_lib.Chroot(
          path=Path(os.path.realpath(chroot_dir)),
          out_path=Path(os.path.realpath(chroot_out_dir)),
      )
      assert (
          not self.chroot.path.startswith(self.cros_dir) or
          self.chroot.path == constants.DEFAULT_CHROOT_DIR), (
              f"Custom chroot dir inside {self.cros_dir} is not supported, and "
              f"chromite resolves it to {constants.DEFAULT_CHROOT_DIR}.")
    else:
      self.chroot = chroot_lib.Chroot(
          path=Path(self.cros_dir) / constants.DEFAULT_CHROOT_DIR,
          out_path=Path(self.cros_dir) / constants.DEFAULT_OUT_DIR,
      )
    self.board_dir = self.chroot.full_path(os.path.join('/build', self.board))
    self.src_dir = os.path.join(self.cros_dir, 'src')
    self.platform2_dir = os.path.join(self.src_dir, 'platform2')

    # List of dirs that might not exist and can be ignored during path fix.
    self.ignorable_dirs = [
        os.path.join(self.board_dir, 'usr', 'include', 'chromeos', 'libica'),
        os.path.join(self.board_dir, 'usr', 'include', 'chromeos', 'libsoda'),
        os.path.join(self.board_dir, 'usr', 'include', 'u2f', 'client'),
        os.path.join(self.board_dir, 'usr', 'share', 'dbus-1'),
        os.path.join(self.board_dir, 'usr', 'share', 'proto'),
        self.chroot.full_path(os.path.join('/build', 'share')),
        self.chroot.full_path(os.path.join('/usr', 'include', 'android')),
        self.chroot.full_path(os.path.join('/usr', 'include', 'cros-camera')),
        self.chroot.full_path(os.path.join('/usr', 'lib64', 'shill')),
        self.chroot.full_path(os.path.join('/usr', 'libexec', 'ipsec')),
        self.chroot.full_path(os.path.join('/usr', 'libexec', 'l2tpipsec_vpn')),
        self.chroot.full_path(os.path.join('/usr', 'share', 'cros-camera')),
    ]

    self.skip_packages = skip_packages
    self.with_build = with_build
    self.with_tests = with_tests

  @property
  def manifest(self) -> git.ManifestCheckout:
    return git.ManifestCheckout.Cached(self.cros_dir)
