# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helpers for setting up a package_index_cros run."""

import os
from pathlib import Path
from typing import List, Optional

from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import git


class Setup:
    """Dataclass to hold setup-related info."""

    def __init__(
        self,
        board: str,
        *,
        skip_packages: Optional[List[str]] = None,
        with_tests: bool = False,
        chroot_dir: str = "",
        chroot_out_dir: str = "",
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

        if chroot_dir:
            if not chroot_out_dir:
                chroot_out_dir = str(constants.DEFAULT_OUT_PATH)
            self.chroot = chroot_lib.Chroot(
                path=os.path.realpath(chroot_dir),
                out_path=os.path.realpath(chroot_out_dir),
            )
            if (
                self.chroot.path.startswith(str(constants.SOURCE_ROOT))
                and self.chroot.path != constants.DEFAULT_CHROOT_PATH
            ):
                raise ValueError(
                    f"Custom chroot dir {self.chroot.path} inside source root "
                    f"is not supported, and chromite resolves it to "
                    f"{constants.DEFAULT_CHROOT_DIR}."
                )
        else:
            self.chroot = chroot_lib.Chroot()
        self.board_dir = self.chroot.full_path(Path("/") / "build" / self.board)

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

        self.skip_packages = skip_packages or []
        self.with_tests = with_tests

    @property
    def manifest(self) -> git.ManifestCheckout:
        """Return a manifest handler to work with the checked-out manifest."""
        return git.ManifestCheckout.Cached(constants.SOURCE_ROOT)
