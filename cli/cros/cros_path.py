# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""CLI to generate various CrOS paths.

For dev scripting, not official tooling.
"""

import enum
from pathlib import Path

from chromite.cli import command
from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import image_lib
from chromite.lib import path_util
from chromite.utils import os_util


class Target(enum.Enum):
    """Target types."""

    LATEST_IMAGE = enum.auto()
    SOURCE_ROOT = enum.auto()
    SYSROOT = enum.auto()

    @classmethod
    def from_str(cls, name: str):
        """Construct from an option string."""
        return cls[name.upper().replace("-", "_")]

    def __str__(self):
        return self.name.lower().replace("_", "-")

    def is_build_target_required(self):
        """Check if the build target argument is required."""
        return self in (self.LATEST_IMAGE, self.SYSROOT)

    def find(self, options: commandline.ArgumentNamespace) -> Path:
        """Find the target path."""
        if self is self.SOURCE_ROOT:
            return (
                constants.CHROOT_SOURCE_ROOT
                if options.inside
                else constants.SOURCE_ROOT
            )
        elif self is self.LATEST_IMAGE:
            return _latest_image(options)
        elif self is self.SYSROOT:
            return _sysroot(options)


def _latest_image(options: commandline.ArgumentNamespace) -> Path:
    """Latest image path implementation"""
    latest = Path(
        image_lib.GetLatestImageLink(
            options.build_target.name, force_chroot=options.inside
        )
    )
    if options.resolve:
        latest = latest.resolve()

    if options.image_type:
        latest /= constants.IMAGE_TYPE_TO_NAME[options.image_type]

    return latest


def _sysroot(options: commandline.ArgumentNamespace) -> Path:
    """Sysroot path implementation."""
    sysroot = options.build_target.root

    if not options.inside:
        sysroot = path_util.FromChrootPath(sysroot)

    return Path(sysroot)


@command.command_decorator("path")
class PathCommand(command.CliCommand):
    """Utility command to get the latest image."""

    EPILOG = """
Get the path to various important locations.

Targets:
  * latest-image: The "latest" image directory, or the latest image itself.
  * source-root: The root of the checkout.
  * sysroot: The path to a board's sysroot.

Allows easily scripting paths rather than manually building them. Paths are not
guaranteed to exist unless using --exists.

Note: Not all combination of options are guaranteed to work, e.g. it may not
always be possible to resolve a path inside the chroot from outside when using
--inside and --resolve.

Some examples follow, run both outside the chroot ($) and inside ((chroot) $).

Get eve's sysroot:
    $ cros path sysroot -b eve
    %(user_home)s/chromiumos/out/build/eve

    (chroot) $ cros path sysroot -b eve
    /build/eve

Get the latest image build directory for eve:
    $ cros path latest-image -b eve
    %(user_home)s/chromiumos/src/build/images/eve/latest

    (chroot) $ cros path latest-image -b eve
    /mnt/host/source/src/build/images/eve/latest

Get the latest build directory for eve, and resolve symlinks:
    $ cros path latest-image -b eve --resolve
    %(user_home)s/chromiumos/src/build/images/eve/R108-15159.0.0-d2022_10_04_163354-a1

    (chroot) $ cros path latest-image -b eve --resolve
    /mnt/host/source/src/build/images/eve/R108-15159.0.0-d2022_10_04_163354-a1

Get the latest build directory for eve inside the SDK:
    $ cros path latest-image -b eve --inside
    /mnt/host/source/src/build/images/eve/latest

    (chroot) $ cros path latest-image -b eve --inside
    /mnt/host/source/src/build/images/eve/latest

Get the latest eve base image path:
    $ cros path latest-image -b eve -i base
    %(user_home)s/chromiumos/src/build/images/eve/latest/chromiumos_base_image.bin

    (chroot) $ cros path latest-image -b eve -i base
    /mnt/host/source/src/build/images/eve/latest/chromiumos_base_image.bin
""" % {
        "user_home": os_util.non_root_home()
    }

    @classmethod
    def AddParser(cls, parser):
        """Add to the parser."""
        super().AddParser(parser)

        parser.add_argument(
            "target",
            choices=list(Target),
            type=Target.from_str,
            help="The type of path to fetch.",
        )

        parser.add_argument(
            "-b",
            "--board",
            "--build-target",
            type=build_target_lib.BuildTarget,
            dest="build_target",
            help="Build target name.",
        )
        parser.add_argument(
            "-i",
            "--image-type",
            choices=(
                constants.IMAGE_TYPE_BASE,
                constants.IMAGE_TYPE_DEV,
                constants.IMAGE_TYPE_TEST,
            ),
            help="The image type to point to. If unspecified, the image "
            "directory is the target instead.",
        )
        parser.add_argument(
            "--inside",
            default=False,
            action="store_true",
            help="If outside the chroot, force the path to be generated as if "
            "inside the chroot.",
        )
        parser.add_argument(
            "--resolve",
            default=False,
            action="store_true",
            help="Resolve symlinks to their targets.",
        )
        parser.add_argument(
            "--exists",
            default=False,
            action="store_true",
            help="Verify the path exists, and fail if it doesn't.",
        )

    @classmethod
    def ProcessOptions(
        cls,
        parser: commandline.ArgumentParser,
        options: commandline.ArgumentNamespace,
    ) -> None:
        """Command specific option processing."""
        super().ProcessOptions(parser, options)

        if (
            options.target.is_build_target_required()
            and not options.build_target
        ):
            parser.error(f"--build-target is required for {options.target}")

    def Run(self):
        """Run the command."""
        path = self.options.target.find(self.options)
        if self.options.exists:
            check_path = (
                Path(path_util.FromChrootPath(path))
                if self.options.inside
                else path
            )
            if not check_path.exists():
                return 1

        print(str(path))
