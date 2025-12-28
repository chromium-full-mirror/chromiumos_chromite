# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A script to generate MiniOS kernel images.

And inserting them into the Chromium OS images.
"""

import argparse
import logging
import os
from pathlib import Path
import shutil
import tempfile

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import minios


def validate_path(path_string, path_type, required_permission=None):
    """Validates a path string.

    Args:
        path_string: The path string to validate.
        path_type: 'file' or 'dir' to specify the expected type.
        required_permission: An integer representing the required permission
                             (e.g., os.R_OK, os.W_OK,
                             os.X_OK, os.R_OK | os.W_OK).

    Returns:
        A pathlib.Path object representing the validated path.

    Raises:
        argparse.ArgumentTypeError: If the path is invalid.
    """
    if not path_string or not path_string.strip():
        raise argparse.ArgumentTypeError("Path cannot be blank.")

    path_string = os.path.expanduser(path_string)
    path_obj = Path(path_string).resolve()

    if path_type == "dir":
        if not path_obj.is_dir():
            raise argparse.ArgumentTypeError(
                f"Not a valid directory: '{path_string}'"
            )
    elif path_type == "file":
        if not path_obj.is_file():
            raise argparse.ArgumentTypeError(
                f"Not a valid file: '{path_string}'"
            )
    else:
        raise argparse.ArgumentTypeError(
            f"Invalid path_type: '{path_type}' (must be 'file' or 'dir')"
        )
    type_str = "directory" if path_type == "dir" else "file"
    if required_permission and not os.access(path_string, required_permission):
        required_perms_str = ""
        if required_permission & os.R_OK:
            required_perms_str += "read"
        if required_permission & os.W_OK:
            if required_perms_str:
                required_perms_str += " and "
            required_perms_str += "write"
        if required_permission & os.X_OK:
            if required_perms_str:
                required_perms_str += " and "
            required_perms_str += "Execute"
        raise argparse.ArgumentTypeError(
            f"{type_str.capitalize()} does not have required"
            f" {required_perms_str} permission : '{path_string}'"
        )
    return path_obj


def GetParser():
    """Creates an argument parser and returns it."""
    parser = commandline.ArgumentParser(description=__doc__, jobs=True)
    parser.add_argument(
        "--board", "-b", "--build-target", required=True, help="The board name."
    )
    parser.add_argument(
        "--version", required=True, help="The chromeos version string."
    )
    parser.add_argument(
        "--image",
        type=lambda x: validate_path(x, "file", os.R_OK | os.W_OK),
        help="The path to the chromium os image.",
    )
    parser.add_argument(
        "--keys-dir",
        type="str_path",
        help="The path to keyset.",
        default=constants.VBOOT_DEVKEYS_DIR,
    )
    parser.add_argument(
        "--public-key",
        help="Filename to the public key whose private part "
        "signed the keyblock.",
        default=constants.RECOVERY_PUBLIC_KEY,
    )
    parser.add_argument(
        "--private-key",
        help="Filename to the private key whose public part is "
        "baked into the keyblock.",
        default=constants.MINIOS_DATA_PRIVATE_KEY,
    )
    parser.add_argument(
        "--keyblock",
        help="Filename to the kernel keyblock.",
        default=constants.MINIOS_KEYBLOCK,
    )
    parser.add_argument(
        "--serial",
        type=str,
        help="Serial port for the kernel console (e.g. printks)",
    )
    parser.add_argument(
        "--mod-for-dev",
        action="store_true",
        help="Repack the MiniOS image with debug flags.",
    )
    parser.add_argument(
        "--force-build",
        action="store_true",
        help="Force the kernel to be rebuilt when repacking with "
        "debug flags. Use with --mod-for-dev in case kernel is "
        "not already built or needs to be rebuilt.",
    )
    kernel_group = parser.add_argument_group(
        "Kernel Options", "Options related to MiniOS kernel build and copy."
    )
    kernel_group.add_argument(
        "--kernel-only",
        action="store_true",
        help="Build MiniOS standalone kernel image "
        "and store it at path given in "
        "--kernel-output.",
    )
    kernel_group.add_argument(
        "--kernel-output",
        type=lambda x: validate_path(x, "dir", os.W_OK | os.X_OK),
        help="MiniOS kernel image out path.",
    )
    return parser


def main(argv) -> None:
    parser = GetParser()
    opts = parser.parse_args(argv)
    opts.freeze()

    if opts.kernel_only:
        if not opts.kernel_output:
            parser.error(
                "--kernel-output is required when --kernel-only is specified."
            )
    else:
        if not opts.image:
            parser.error("--image=<path of chromium os image> required.")

    with tempfile.TemporaryDirectory() as work_dir:
        build_kernel = opts.force_build if opts.mod_for_dev else True
        kernel = minios.CreateMiniOsKernelImage(
            opts.board,
            opts.version,
            work_dir,
            opts.keys_dir,
            opts.public_key,
            opts.private_key,
            opts.keyblock,
            opts.serial,
            opts.jobs,
            build_kernel,
            opts.mod_for_dev,
        )

        if opts.kernel_output:
            shutil.copy(kernel, opts.kernel_output)
            logging.info("kernel image copied to: %s", opts.kernel_output)

        if not opts.kernel_only:
            minios.InsertMiniOsKernelImage(opts.image, kernel)
