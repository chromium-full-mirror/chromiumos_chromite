# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chroot class.

This is currently a very sparse class, but there's a significant amount of
functionality that can eventually be centralized here.
"""

import os
from typing import Dict, List, Optional, TYPE_CHECKING

from chromite.lib import constants
from chromite.lib import osutils
from chromite.lib import path_util

if TYPE_CHECKING:
  from chromite.cbuildbot import goma_util
  from chromite.lib import remoteexec_util


class Error(Exception):
  """Base chroot_lib error class."""


class ChrootError(Error):
  """An exception raised when something went wrong with a chroot object."""


class Chroot(object):
  """Chroot class."""

  def __init__(self,
               path: Optional[str] = None,
               cache_dir: Optional[str] = None,
               chrome_root: Optional[str] = None,
               env: Optional[Dict[str, str]] = None,
               goma: Optional['goma_util.Goma'] = None,
               remoteexec: Optional['remoteexec_util.Remoteexec'] = None):
    """Initialize.

    Args:
      path: Path to the chroot.
      cache_dir: Path to a directory that will be used for caching files.
      chrome_root: Root of the Chrome browser source checkout.
      env: Extra environment settings to use.
      goma: Interface for utilizing goma.
      remoteexec: Interface for utilizing remoteexec client.
    """
    # Strip trailing / if present for consistency.
    self._path = (path or constants.DEFAULT_CHROOT_PATH).rstrip('/')
    self._is_default_path = not bool(path)
    self._env = env
    self.goma = goma
    self.remoteexec = remoteexec
    # String in proto are '' when not set, but testing and comparing is much
    # easier when the "unset" value is consistent, so do an explicit "or None".
    self.cache_dir = cache_dir or None
    self.chrome_root = chrome_root or None

  def __eq__(self, other):
    if self.__class__ is other.__class__:
      return (self.path == other.path and self.cache_dir == other.cache_dir
              and self.chrome_root == other.chrome_root
              and self.env == other.env)

    return NotImplemented

  def __hash__(self) -> int:
    return hash(self.path)

  @property
  def path(self) -> str:
    return self._path

  def exists(self) -> bool:
    """Checks if the chroot exists."""
    return os.path.exists(self.path)

  @property
  def tmp(self) -> str:
    """Get the chroot's tmp dir."""
    return os.path.join(self.path, 'tmp')

  def tempdir(self) -> str:
    """Get a TempDir in the chroot's tmp dir."""
    return osutils.TempDir(base_dir=self.tmp)

  def chroot_path(self, path: str) -> str:
    """Turn an absolute path into a chroot relative path."""
    return path_util.ToChrootPath(path=path, chroot_path=self._path)

  def full_path(self, *args: List[str]) -> str:
    """Turn a fully expanded chrootpath into an host-absolute path."""
    path = os.path.join(os.path.sep, *args)
    return path_util.FromChrootPath(path=path, chroot_path=self._path)

  def has_path(self, *args: List[str]) -> bool:
    """Check if a chroot-relative path exists inside the chroot."""
    return os.path.exists(self.full_path(*args))

  def get_enter_args(self) -> List[str]:
    """Build the arguments to enter this chroot."""
    args = []

    # This check isn't strictly necessary, always passing the --chroot argument
    # is valid, but it's nice for cleaning up commands in logs.
    if not self._is_default_path:
      args.extend(['--chroot', self.path])
    if self.cache_dir:
      args.extend(['--cache-dir', self.cache_dir])
    if self.chrome_root:
      args.extend(['--chrome-root', self.chrome_root])
    if self.goma:
      args.extend([
          '--goma_dir', self.goma.linux_goma_dir,
      ])
      if self.goma.goma_client_json:
        args.extend([
          '--goma_client_json', self.goma.goma_client_json,
        ])
    if self.remoteexec:
      args.extend([
          '--reclient-dir', self.remoteexec.reclient_dir,
          '--reproxy-cfg-file', self.remoteexec.reproxy_cfg_file,
      ])

    return args

  @property
  def env(self) -> Dict[str, str]:
    env = self._env.copy() if self._env else {}
    if self.goma:
      env.update(self.goma.GetChrootExtraEnv())
    if self.remoteexec:
      env.update(self.remoteexec.GetChrootExtraEnv())

    return env
