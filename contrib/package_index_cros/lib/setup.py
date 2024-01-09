# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helpers for setting up a package_index_cros run."""

import os
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
        with_build: bool = False,
        with_tests: bool = False,
        chroot_dir: str = "",
        chroot_out_dir: str = "",
    ):
        """Initialize the instance.

        Args:
            board: The build target being worked on.
            skip_packages: A list of fully-named packages to ignore.
            with_build: Whether to build packages before generating the index.
            with_tests: Whether to build tests alongside packages. (Irrelevant
                if with_build is False.)
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

        self.cros_dir = checkout_info.root
        if chroot_dir:
            self.chroot = chroot_lib.Chroot(
                path=Path(os.path.realpath(chroot_dir)),
                out_path=Path(os.path.realpath(chroot_out_dir)),
            )
            assert (
                not self.chroot.path.startswith(self.cros_dir)
                or self.chroot.path == constants.DEFAULT_CHROOT_DIR
            ), (
                f"Custom chroot dir inside {self.cros_dir} is not supported, "
                f"and chromite resolves it to {constants.DEFAULT_CHROOT_DIR}."
            )
        else:
            self.chroot = chroot_lib.Chroot(
                path=Path(self.cros_dir) / constants.DEFAULT_CHROOT_DIR,
                out_path=Path(self.cros_dir) / constants.DEFAULT_OUT_DIR,
            )
        self.board_dir = self.chroot.full_path(
            os.path.join("/build", self.board)
        )
        self.src_dir = os.path.join(self.cros_dir, "src")
        self.platform2_dir = os.path.join(self.src_dir, "platform2")

        # List of dirs that might not exist and can be ignored during path fix.
        self.ignorable_dirs = [
            os.path.join(
                self.board_dir, "usr", "include", "chromeos", "libica"
            ),
            os.path.join(
                self.board_dir, "usr", "include", "chromeos", "libsoda"
            ),
            os.path.join(self.board_dir, "usr", "include", "u2f", "client"),
            os.path.join(self.board_dir, "usr", "share", "dbus-1"),
            os.path.join(self.board_dir, "usr", "share", "proto"),
            self.chroot.full_path(os.path.join("/build", "share")),
            self.chroot.full_path(os.path.join("/usr", "include", "android")),
            self.chroot.full_path(
                os.path.join("/usr", "include", "cros-camera")
            ),
            self.chroot.full_path(os.path.join("/usr", "lib64", "shill")),
            self.chroot.full_path(os.path.join("/usr", "libexec", "ipsec")),
            self.chroot.full_path(
                os.path.join("/usr", "libexec", "l2tpipsec_vpn")
            ),
            self.chroot.full_path(os.path.join("/usr", "share", "cros-camera")),
        ]

        self.skip_packages = skip_packages
        self.with_build = with_build
        self.with_tests = with_tests

    @property
    def manifest(self) -> git.ManifestCheckout:
        """Return a manifest handler to work with the checked-out manifest."""
        return git.ManifestCheckout.Cached(self.cros_dir)
