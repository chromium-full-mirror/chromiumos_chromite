# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helpers for setting up a package_index_cros run."""

from pathlib import Path
from typing import List, Optional

from chromite.contrib.package_index_cros.lib import (
    constants as package_index_constants,
)
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import git
from chromite.lib import path_util
from chromite.lib import repo_util


class Setup:
    """Dataclass to hold setup-related info."""

    def __init__(
        self,
        board: str,
        *,
        skip_packages: Optional[List[str]] = None,
        with_tests: bool = False,
        chroot_dir: Optional[Path] = None,
        chroot_out_dir: Optional[Path] = None,
    ):
        """Initialize the instance.

        Args:
            board: The build target being worked on.
            skip_packages: A list of fully-named packages to ignore.
            with_tests: Whether to build tests alongside packages.
            chroot_dir: Absolute path to the local chroot directory.
            chroot_out_dir: Absolute path to the local chroot's out dir.
        """
        self.board = board

        checkout_info = path_util.DetermineCheckout(
            package_index_constants.PACKAGE_ROOT_DIR
        )
        if checkout_info.type != path_util.CheckoutType.REPO:
            raise repo_util.NotInRepoError(
                "Script is executed outside of ChromeOS checkout"
            )

        self.cros_dir = Path(checkout_info.root)
        if chroot_dir:
            self.chroot = chroot_lib.Chroot(
                path=chroot_dir.resolve(),
                out_path=chroot_out_dir.resolve() if chroot_out_dir else None,
            )
            chroot_path = Path(self.chroot.path).resolve()
            if self.cros_dir in [
                chroot_path,
                *chroot_path.parents,
            ] and not chroot_path.samefile(constants.DEFAULT_CHROOT_PATH):
                raise ValueError(
                    f"Custom chroot dir {chroot_path} inside {self.cros_dir} "
                    "is not supported, and chromite resolves it to "
                    f"{constants.DEFAULT_CHROOT_DIR}."
                )
        else:
            self.chroot = chroot_lib.Chroot(
                path=Path(self.cros_dir) / constants.DEFAULT_CHROOT_DIR,
                out_path=Path(self.cros_dir) / constants.DEFAULT_OUT_DIR,
            )
        self.board_dir = Path(
            self.chroot.full_path(Path("/") / "build" / self.board)
        )
        self.src_dir = self.cros_dir / "src"
        self.platform2_dir = self.src_dir / "platform2"

        # List of dirs that might not exist and can be ignored during path fix.
        self.ignorable_dirs: List[Path] = [
            self.board_dir / "usr" / "include" / "chromeos" / "libica",
            self.board_dir / "usr" / "include" / "chromeos" / "libsoda",
            self.board_dir / "usr" / "include" / "u2f" / "client",
            self.board_dir / "usr" / "share" / "dbus-1",
            self.board_dir / "usr" / "share" / "proto",
            self.chroot.full_path(Path("/") / "build" / "share"),
            self.chroot.full_path(Path("/") / "usr" / "include" / "android"),
            self.chroot.full_path(
                Path("/") / "usr" / "include" / "cros-camera"
            ),
            self.chroot.full_path(Path("/") / "usr" / "lib64" / "shill"),
            self.chroot.full_path(Path("/") / "usr" / "libexec" / "ipsec"),
            self.chroot.full_path(
                Path("/") / "usr" / "libexec" / "l2tpipsec_vpn"
            ),
            self.chroot.full_path(Path("/") / "usr" / "share" / "cros-camera"),
        ]

        self.skip_packages: List[str] = skip_packages or []
        self.with_tests = with_tests

    @property
    def manifest(self) -> git.ManifestCheckout:
        """Return a manifest handler to work with the checked-out manifest."""
        return git.ManifestCheckout.Cached(self.cros_dir)
