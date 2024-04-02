# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build target class and related functionality."""

from __future__ import annotations

import functools
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Iterator, Optional

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_query
from chromite.lib import constants
from chromite.lib import portage_util


class Error(Exception):
    """Base module error class."""


class InvalidSerializedBuildTarget(Error):
    """Given an invalid serialization of a build target."""


class BuildTarget:
    """Class to handle the build target information."""

    def __init__(
        self,
        name: Optional[str],
        profile: str = "base",
        build_root: Optional[str] = None,
        public: Optional[bool] = None,
    ) -> None:
        """Build Target init.

        Args:
            name: The full name of the target.
            profile: The profile name.
            build_root: The path to the buildroot.
            public: If true, simulate a public checkout.  By default, enable
                for boards without a private overlay.
        """
        self._name = name or constants.CHROOT_BUILDER_BOARD
        self.profile = profile
        self._public = public

        if build_root:
            self.root = os.path.normpath(build_root)
        else:
            self.root = get_default_sysroot_path(self.name)

        self.broot = Path(self.root) / "build" / "broot"

    def __eq__(self, other: Any) -> bool:
        if self.__class__ is other.__class__:
            return (
                self.name == other.name
                and self.profile == other.profile
                and self.root == other.root
                and self._public == other._public
            )

        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.name, self.profile, self._public, self.root))

    def __str__(self) -> str:
        return f"{self.name or 'amd64-host'}:{self.profile}"

    @property
    def name(self) -> Optional[str]:
        """Build target name, a.k.a. board."""
        return self._name

    @functools.cached_property
    def board(self) -> build_query.Board:
        """The build_query.Board corresponding to this target."""
        return build_query.Board.get(self.name, profile=self.profile)

    @property
    def public(self) -> bool:
        """True if this build should be done from public sources only."""
        if self._public is not None:
            return self._public

        return not self.board.private_overlay

    def full_path(self, *args):
        """Turn a sysroot-relative path into an absolute path."""
        return os.path.join(self.root, *[part.lstrip(os.sep) for part in args])

    def get_command(self, base_command: str) -> str:
        """Get the build target's variant of the given base command.

        We create wrappers for many scripts that handle the build target's
        arguments. Build the target-specific variant for such a command.
        e.g. emerge -> emerge-eve.

        TODO: Add optional validation the command exists.

        Args:
            base_command: The wrapped command.

        Returns:
            The build target's command wrapper.
        """
        if self.is_host():
            return base_command

        return "%s-%s" % (base_command, self.name)

    def find_overlays(
        self, source_root: Path = constants.SOURCE_ROOT
    ) -> Iterator[Path]:
        """Find the overlays for this build target.

        Args:
            source_root: If provided, use an alternative SOURCE_ROOT (useful for
                testing).

        Yields:
            Paths to the overlays.
        """
        overlay_type = (
            constants.PUBLIC_OVERLAYS
            if self.public
            else constants.BOTH_OVERLAYS
        )
        for overlay in portage_util.FindOverlays(
            overlay_type, self.name, buildroot=source_root
        ):
            yield Path(overlay)

    def is_host(self) -> bool:
        """Check if the build target refers to the host."""
        return self.name.endswith("-host")

    def to_proto(self) -> common_pb2.BuildTarget:
        """Convert to a common_pb2.BuildTarget."""
        return common_pb2.BuildTarget(
            name=self.name,
            profile=common_pb2.Profile(name=self.profile),
        )

    def to_json(self) -> str:
        """Convert to a json dict."""
        return json.dumps(
            {
                "name": self.name,
                "profile": self.profile,
                "root": str(self.root),
                "public": self._public,
            }
        )

    @classmethod
    def from_json(cls, serialized: str) -> BuildTarget:
        """Create an instance from a json string."""
        try:
            data = json.loads(serialized)
        except json.JSONDecodeError as e:
            logging.exception("Unable to parse the build target.")
            raise InvalidSerializedBuildTarget(
                "Unable to parse the build target."
            ) from e

        try:
            return cls(
                name=data["name"],
                profile=data.get("profile", "base"),
                build_root=data.get("root"),
                public=data.get("public"),
            )
        except TypeError as e:
            msg = (
                "Unable to create a build target from the given "
                f"serialization: {serialized}"
            )
            logging.exception(msg)
            raise InvalidSerializedBuildTarget(msg) from e


def get_default_sysroot_path(build_target_name: Optional[str] = None) -> str:
    """Get the default sysroot location or / if |build_target_name| is None."""
    if build_target_name is None:
        return "/"
    return os.path.join("/build", build_target_name)


def get_sdk_sysroot_path() -> str:
    """Get the SDK's sysroot path.

    Convenience/clarification wrapper for get_default_sysroot_path for use when
    explicitly fetching the SDK's sysroot path.
    """
    return get_default_sysroot_path()


def is_valid_name(build_target_name):
    """Validate |build_target_name| is a valid name."""
    return bool(re.match(r"^[a-zA-Z0-9-_]+$", build_target_name))
