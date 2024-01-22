# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chroot class.

This is currently a very sparse class, but there's a significant amount of
functionality that can eventually be centralized here.
"""

import functools
import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Union

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import locking
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import timeout_util
from chromite.utils import key_value_store


if TYPE_CHECKING:
    from chromite.lib import goma_lib


class Error(Exception):
    """Base chroot_lib error class."""


class ChrootError(Error):
    """An exception raised when something went wrong with a chroot object."""


class Chroot:
    """Chroot class."""

    def __init__(
        self,
        path: Optional[Union[str, os.PathLike]] = None,
        out_path: Optional[Path] = None,
        cache_dir: Optional[str] = None,
        chrome_root: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        goma: Optional["goma_lib.Goma"] = None,
    ) -> None:
        """Initialize.

        Args:
            path: Path to the chroot.
            out_path: Path to the out directory.
            cache_dir: Path to a directory that will be used for caching files.
            chrome_root: Root of the Chrome browser source checkout.
            env: Extra environment settings to use.
            goma: Interface for utilizing goma.
        """
        # Strip trailing / if present for consistency.
        # TODO(vapier): Switch this to Path instead of str.
        self._path = (
            str(path) if path else constants.DEFAULT_CHROOT_PATH
        ).rstrip("/")
        self._out_path = out_path if out_path else constants.DEFAULT_OUT_PATH
        self._is_default_path = not bool(path)
        self._is_default_out_path = not out_path
        self._env = env
        self.goma = goma
        # String in proto are '' when not set, but testing and comparing is much
        # easier when the "unset" value is consistent, so do an explicit "or
        # None".
        self.cache_dir = cache_dir or None
        self.chrome_root = chrome_root or None

    def __eq__(self, other: Any) -> bool:
        if self.__class__ is other.__class__:
            return (
                self.path == other.path
                and self.out_path == other.out_path
                and self.cache_dir == other.cache_dir
                and self.chrome_root == other.chrome_root
                and self.env == other.env
            )

        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.path)

    @property
    def path(self) -> str:
        return self._path

    @property
    def out_path(self) -> Path:
        return self._out_path

    def exists(self) -> bool:
        """Checks if the chroot exists."""
        return os.path.exists(self.path) and self.out_path.exists()

    @property
    def tmp(self) -> str:
        """Get the chroot's tmp dir."""
        return self.full_path("/tmp")

    def tempdir(self, delete=True) -> osutils.TempDir:
        """Get a TempDir in the chroot's tmp dir."""
        return osutils.TempDir(base_dir=self.tmp, delete=delete)

    def chroot_path(self, path: Union[str, os.PathLike]) -> str:
        """Turn an absolute path into a chroot relative path."""
        return path_util.ToChrootPath(
            path=path, chroot_path=self._path, out_path=self._out_path
        )

    def full_path(self, *args: Union[str, os.PathLike]) -> str:
        """Turn a fully expanded chrootpath into an host-absolute path."""
        path = os.path.join(os.path.sep, *args)
        return path_util.FromChrootPath(
            path=path, chroot_path=self._path, out_path=self._out_path
        )

    def has_path(self, *args: str) -> bool:
        """Check if a chroot-relative path exists inside the chroot."""
        return os.path.exists(self.full_path(*args))

    def lock(self, blocking_timeout: Optional[int] = None) -> locking.FileLock:
        """Get a locking.FileLock corresponding to this chroot.

        Args:
            blocking_timeout: If specified, the number of seconds blocking
                operations on this lock should wait before timing out.

        Returns:
            A locking.FileLock.
        """
        chroot_path = Path(self.path)
        lock_path = chroot_path.with_name(
            f".{chroot_path.name.lstrip('.')}_lock"
        )
        return locking.FileLock(
            lock_path,
            description="chroot lock",
            blocking_timeout=blocking_timeout,
        )

    def delete(
        self,
        delete_out_dir: bool = True,
        blocking_timeout: int = 300,
        force: bool = False,
    ) -> None:
        """Delete the chroot.

        Args:
            delete_out_dir: If true, delete the out directory in addition to the
                chroot.
            blocking_timeout: Number of seconds to wait for lock.
            force: If true, delete the chroot anyway after lock timeout.
        """
        # Delayed import to avoid circular imports :(
        # TODO(build): Once cbuildbot is deleted, we won't have any more
        # calls to CleanupChroot besides this one.  At that point, we can
        # inline the deletion functionality here and drop this import.
        # pylint: disable-next=wrong-import-position
        from chromite.lib import cros_sdk_lib

        with self.lock(blocking_timeout=blocking_timeout) as lock:
            try:
                lock.write_lock()
            except timeout_util.TimeoutError as e:
                logging.error(
                    "Acquiring write_lock on %s failed: %s", lock.path, e
                )
                if not force:
                    raise
                else:
                    logging.warning("Chroot deletion is forced, continuing.")
            logging.notice("Deleting chroot: %s", self.path)
            logging.notice(
                "%s output dir: %s",
                "Deleting" if delete_out_dir else "Keeping",
                self.out_path,
            )
            cros_sdk_lib.CleanupChroot(self, delete_out=delete_out_dir)

    @functools.cached_property
    def _os_release_props(self) -> Dict[str, str]:
        """The variables contained within /etc/os-release."""
        return key_value_store.LoadFile(
            self.full_path("/etc/os-release"),
            ignore_missing=True,
        )

    @property
    def tarball_version(self) -> Optional[str]:
        """The tarball version the chroot was created from."""
        return self._os_release_props.get("BUILD_ID")

    def get_enter_args(self, for_shell: bool = False) -> List[str]:
        """Build the arguments to enter this chroot.

        Args:
            for_shell: Whether the return value will be used when using the old
                src/scripts/ shell code or with newer `cros_sdk` interface.

        Returns:
            The command line arguments to pass to the enter chroot program.
        """
        args = []

        # The old shell/sdk_lib/enter_chroot.sh uses shflags which only
        # accepts _ in option names.  Our Python code uses - instead.
        # TODO(build): Delete this once sdk_lib/enter_chroot.sh is gone.
        sep = "_" if for_shell else "-"

        # This check isn't strictly necessary, always passing the --chroot
        # argument is valid, but it's nice for cleaning up commands in logs.
        if not self._is_default_path:
            args.extend(["--chroot", self.path])
        if not self._is_default_out_path:
            args.extend([f"--out{sep}dir", str(self.out_path)])
        if self.cache_dir:
            args.extend([f"--cache{sep}dir", self.cache_dir])
        if self.chrome_root:
            args.extend([f"--chrome{sep}root", self.chrome_root])
        if self.goma:
            args.extend(
                [
                    f"--goma{sep}dir",
                    str(self.goma.linux_goma_dir),
                ]
            )

        return args

    @property
    def env(self) -> Dict[str, str]:
        env = self._env.copy() if self._env else {}
        if self.goma:
            env.update(self.goma.GetChrootExtraEnv())

        return env

    def _runner(
        self,
        func: Callable[..., cros_build_lib.CompletedProcess],
        cmd: Union[List[str], str],
        **kwargs,
    ) -> cros_build_lib.CompletedProcess:
        # Merge provided |extra_env| with self.env.
        extra_env = {**self.env, **(kwargs.pop("extra_env", None) or {})}
        chroot_args = self.get_enter_args() + kwargs.pop("chroot_args", [])
        return func(
            cmd,
            enter_chroot=True,
            chroot_args=chroot_args,
            extra_env=extra_env,
            **kwargs,
        )

    def run(
        self, cmd: Union[List[str], str], **kwargs
    ) -> cros_build_lib.CompletedProcess:
        """Run a command inside this chroot.

        A convenience wrapper around cros_build_lib.run().
        """
        return self._runner(cros_build_lib.run, cmd, **kwargs)

    def sudo_run(
        self, cmd: Union[List[str], str], **kwargs
    ) -> cros_build_lib.CompletedProcess:
        """Run a sudo command inside this chroot.

        A convenience wrapper around cros_build_lib.sudo_run().
        """
        return self._runner(cros_build_lib.sudo_run, cmd, **kwargs)
