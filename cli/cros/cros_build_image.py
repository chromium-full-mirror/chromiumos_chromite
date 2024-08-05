# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros build-image is used to build a ChromiumOS image.

ChromiumOS comes in many different forms. This script can be used to build
the following:

base - Pristine ChromiumOS image. As similar to ChromeOS as possible.
dev [default] - Developer image. Like base but with additional dev packages.
test - Like dev, but with additional test specific packages and can be easily
    used for automated testing using scripts like test_that, etc.
factory_install - Install shim for bootstrapping the factory test process.
    Cannot be built along with any other image.
flexor - Builds a standalone Flexor vmlinuz. Flexor is a ChromeOS Flex installer
    for more details, take a look at platform2/flexor or go/dd-flexor.

Examples:

cros build-image --board=<board> dev test - build developer and test images.
cros build-image --board=<board> factory_install - build a factory install shim.
cros build-image --board=<board> flexor - builds a Flexor vmlinuz.

Note if you want to build an image with custom size partitions, either consider
adding a new disk layout in build_library/legacy_disk_layout.json OR use
adjust-part. Here are a few examples:

adjust-part='STATE:+1G' -- add one GB to the size the stateful partition
adjust-part='ROOT-A:-1G' -- remove one GB from the primary rootfs partition
adjust-part='STATE:=1G' --  make the stateful partition 1 GB
"""

import argparse
import contextlib
import logging
import os
from pathlib import Path
import sys
from typing import Iterable, List, Optional, TYPE_CHECKING

from chromite.third_party.opentelemetry.trace import status

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import namespaces
from chromite.lib import path_util
from chromite.lib.telemetry import trace
from chromite.service import image
from chromite.utils import timer


if TYPE_CHECKING:
    from chromite.lib.parser import package_info


tracer = trace.get_tracer(__name__)


class Error(Exception):
    """Base error class for the module."""


class FailedPackageError(Error):
    """Failed packages error."""

    def __init__(
        self, msg: str, failed_packages: Iterable["package_info.PackageInfo"]
    ) -> None:
        super().__init__(msg)
        self.failed_packages = failed_packages


def build_shell_bool_style_args(
    parser: commandline.ArgumentParser,
    name: str,
    default_val: bool,
    help_str: str,
    deprecation_note: str,
    alternate_name: Optional[str] = None,
    additional_neg_options: Optional[List[str]] = None,
) -> None:
    """Build the shell boolean input argument equivalent.

    There are two cases which we will need to handle,
    case 1: A shell boolean arg, which doesn't need to be re-worded in python.
    case 2: A shell boolean arg, which needs to be re-worded in python.
    Example below.
    For Case 1, for a given input arg name 'argA', we create three python
    arguments.
    --argA, --noargA, --no-argA. The arguments --argA and --no-argA will be
    retained after deprecating --noargA.
    For Case 2, for a given input arg name 'arg_A' we need to use alternate
    argument name 'arg-A'. we create four python arguments in this case.
    --arg_A, --noarg_A, --arg-A, --no-arg-A. The first two arguments will be
    deprecated later.
    TODO(b/232566937): Remove the creation of --noargA in case 1 and --arg_A and
    --noarg_A in case 2.

    Args:
        parser: The parser to update.
        name: The input argument name. This will be used as 'dest' variable
            name.
        default_val: The default value to assign.
        help_str: The help string for the input argument.
        deprecation_note: A deprecation note to use.
        alternate_name: Alternate argument to be used after deprecation.
        additional_neg_options: Additional negative alias options to use.
    """
    arg = f"--{name}"
    shell_narg = f"--no{name}"
    py_narg = f"--no-{name}"
    alt_arg = f"--{alternate_name}" if alternate_name else None
    alt_py_narg = f"--no-{alternate_name}" if alternate_name else None
    default_val_str = f"{help_str} (Default: %(default)s)."

    if alternate_name:
        _alternate_narg_list = [alt_py_narg]
        if additional_neg_options:
            _alternate_narg_list.extend(additional_neg_options)

        parser.add_argument(
            alt_arg,
            action="store_true",
            default=default_val,
            dest=name,
            help=default_val_str,
        )
        parser.add_argument(
            *_alternate_narg_list,
            action="store_false",
            dest=name,
            help="Don't " + help_str.lower(),
        )

    parser.add_argument(
        arg,
        action="store_true",
        default=default_val,
        dest=name,
        deprecated=deprecation_note % alt_arg if alternate_name else None,
        help=default_val_str if not alternate_name else argparse.SUPPRESS,
    )
    parser.add_argument(
        shell_narg,
        action="store_false",
        dest=name,
        deprecated=deprecation_note
        % (alt_py_narg if alternate_name else py_narg),
        help=argparse.SUPPRESS,
    )

    if not alternate_name:
        _py_narg_list = [py_narg]
        if additional_neg_options:
            _py_narg_list.extend(additional_neg_options)

        parser.add_argument(
            *_py_narg_list,
            action="store_false",
            dest=name,
            help="Don't " + help_str.lower(),
        )


def build_shell_string_style_args(
    parser: commandline.ArgumentParser,
    name: str,
    default_val: Optional[str],
    help_str: str,
    deprecation_note: str,
    alternate_name: str,
) -> None:
    """Build the shell string input argument equivalent.

    Args:
        parser: The parser to update.
        name: The input argument name. This will be used as 'dest' variable
            name.
        default_val: The default value to assign.
        help_str: The help string for the input argument.
        deprecation_note: A deprecation note to use.
        alternate_name: Alternate argument to be used after deprecation.
    """
    default_val_str = (
        f"{help_str} (Default: %(default)s)." if default_val else help_str
    )

    parser.add_argument(
        f"--{alternate_name}",
        dest=f"{name}",
        default=default_val,
        help=default_val_str,
    )
    parser.add_argument(
        f"--{name}",
        deprecated=deprecation_note % f"--{alternate_name}",
        help=argparse.SUPPRESS,
    )


@command.command_decorator("build-image")
class BuildImageCommand(command.CliCommand):
    """Build a ChromiumOS image."""

    @classmethod
    def AddParser(cls, parser: commandline.ArgumentParser) -> None:
        """Build the parser.

        Args:
            parser: The parser.
        """
        super().AddParser(parser)
        parser.description = __doc__

        deprecation_note = (
            "Argument will be removed January 2023. Use %s instead."
        )

        parser.add_argument(
            "-b",
            "--board",
            "--build-target",
            dest="board",
            default=cros_build_lib.GetDefaultBoard(),
            help="The board to build images for.",
        )
        build_shell_string_style_args(
            parser,
            "adjust_part",
            None,
            "Adjustments to apply to partition table (LABEL:[+-=]SIZE) "
            "e.g. ROOT-A:+1G.",
            deprecation_note,
            "adjust-partition",
        )
        build_shell_string_style_args(
            parser,
            "output_root",
            constants.DEFAULT_BUILD_ROOT / "images",
            "Directory in which to place image result directories "
            "(named by version).",
            deprecation_note,
            "output-root",
        )
        build_shell_string_style_args(
            parser,
            "builder_path",
            None,
            "The build name to be installed on DUT during hwtest.",
            deprecation_note,
            "builder-path",
        )
        build_shell_string_style_args(
            parser,
            "disk_layout",
            "default",
            "The disk layout type to use for this image.",
            deprecation_note,
            "disk-layout",
        )

        # Kernel related options.
        group = parser.add_argument_group("Kernel Options")
        build_shell_string_style_args(
            group,
            "enable_serial",
            None,
            "Enable serial port for printks. Example values: ttyS0.",
            deprecation_note,
            "enable-serial",
        )
        group.add_argument(
            "--kernel-loglevel",
            type=int,
            default=7,
            help="The loglevel to add to the kernel command line. "
            "(Default: %(default)s).",
        )
        group.add_argument(
            "--loglevel",
            dest="kernel_loglevel",
            type=int,
            deprecated=deprecation_note % "kernel-loglevel",
            help=argparse.SUPPRESS,
        )

        # Bootloader related options.
        group = parser.add_argument_group("Bootloader Options")
        build_shell_string_style_args(
            group,
            "boot_args",
            "noinitrd",
            "Additional boot arguments to pass to the commandline.",
            deprecation_note,
            "boot-args",
        )
        build_shell_bool_style_args(
            group,
            "enable_rootfs_verification",
            True,
            "Make all bootloaders use kernel based rootfs integrity checking.",
            deprecation_note,
            "enable-rootfs-verification",
            ["-r"],
        )

        # Advanced options.
        group = parser.add_argument_group("Advanced Options")
        group.add_argument(
            "--build-attempt",
            type=int,
            default=1,
            help="Build attempt for this image build. (Default: %(default)s).",
        )
        group.add_argument(
            "--build_attempt",
            type=int,
            deprecated=deprecation_note % "build-attempt",
            help=argparse.SUPPRESS,
        )
        build_shell_string_style_args(
            group,
            "build_root",
            constants.DEFAULT_BUILD_ROOT / "images",
            "Directory in which to compose the image, before copying it to "
            "output_root.",
            deprecation_note,
            "build-root",
        )
        group.add_argument(
            "-j",
            "--jobs",
            dest="jobs",
            type=int,
            default=os.cpu_count(),
            help="Number of packages to build in parallel at maximum. "
            "(Default: %(default)s).",
        )
        build_shell_bool_style_args(
            group,
            "replace",
            False,
            "Overwrite existing output, if any.",
            deprecation_note,
        )
        group.add_argument(
            "--symlink",
            default="latest",
            help="Symlink name to use for this image. (Default: %(default)s).",
        )
        group.add_argument(
            "--version",
            default=None,
            help="Overrides version number in name to this version.",
        )
        build_shell_string_style_args(
            group,
            "output_suffix",
            None,
            "Add custom suffix to output directory.",
            deprecation_note,
            "output-suffix",
        )
        group.add_argument(
            "--eclean",
            action="store_true",
            default=True,
            dest="eclean",
            deprecated=(
                "eclean is being removed from `cros build-image`.  Argument "
                "will be removed January 2023."
            ),
            help=argparse.SUPPRESS,
        )
        group.add_argument(
            "--noeclean",
            action="store_false",
            dest="eclean",
            deprecated=(
                "eclean is being removed from `cros build-image`.  Argument "
                "will be removed January 2023."
            ),
            help=argparse.SUPPRESS,
        )
        group.add_argument(
            "--no-eclean",
            action="store_false",
            dest="eclean",
            deprecated=(
                "eclean is being removed from `cros build-image`.  Argument "
                "will be removed January 2023."
            ),
            help=argparse.SUPPRESS,
        )
        build_shell_bool_style_args(
            group,
            "use_network_namespace",
            True,
            "Disable/enable the network namespace.",
            deprecation_note,
            "use-network-namespace",
        )

        parser.add_argument(
            "images",
            nargs="*",
            default=["dev"],
            help="list of images to build. (Default: %(default)s).",
        )

    @classmethod
    def ProcessOptions(cls, parser, options) -> None:
        """Post-process options prior to freeze."""

        # If the opts.board is not set, then it means the user hasn't specified
        # a default board and didn't specify it as an input argument.
        if not options.board:
            parser.error("--board is required")

        invalid_image = [
            x for x in options.images if x not in constants.IMAGE_TYPE_TO_NAME
        ]
        if invalid_image:
            parser.error(f"Invalid image type argument(s) {invalid_image}")

        options.build_run_config = image.BuildConfig(
            adjust_partition=options.adjust_part,
            output_root=options.output_root,
            builder_path=options.builder_path,
            disk_layout=options.disk_layout,
            enable_serial=options.enable_serial,
            kernel_loglevel=options.kernel_loglevel,
            boot_args=options.boot_args,
            enable_rootfs_verification=options.enable_rootfs_verification,
            build_attempt=options.build_attempt,
            build_root=options.build_root,
            jobs=options.jobs,
            replace=options.replace,
            symlink=options.symlink,
            version=options.version,
            output_dir_suffix=options.output_suffix,
        )

    def Run(self):
        chroot_args = []
        try:
            chroot_args += ["--working-dir", path_util.ToChrootPath(Path.cwd())]
        except ValueError:
            logging.warning("Unable to translate CWD to a chroot path.")
        commandline.RunInsideChroot(self, chroot_args=chroot_args)
        commandline.RunAsRootUser(sys.argv, preserve_env=True)

        result = None

        with tracer.start_as_current_span("cli.cros.cros_build_image.Run") as s:
            s.set_attributes({"build_target": self.options.board})
            network_sandbox = namespaces.use_network_sandbox
            if not self.options.use_network_namespace:
                logging.info("Skipping network sandbox.")
                network_sandbox = contextlib.nullcontext()

            with network_sandbox():
                with timer.timer("Elapsed time (cros build-image)"):
                    result = image.Build(
                        self.options.board,
                        self.options.images,
                        self.options.build_run_config,
                    )

            if result and result.run_error:
                s.set_status(status.StatusCode.ERROR)
                if result.exception:
                    s.record_exception(result.exception)
                    logging.error(result.exception)
                else:
                    s.record_exception(
                        FailedPackageError(
                            "an exception occurred when running "
                            "chromite.service.image.Build.",
                            result.failed_packages,
                        )
                    )
                    logging.error(
                        "Error running build-image. Exit Code: %s",
                        {result.return_code},
                    )
                return result.return_code
