# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities to handle/generate CrOS stateful payloads."""

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Union

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import image_lib
from chromite.lib import osutils


STATEFUL_FILE = "stateful.tgz"


def _generate_stateful_payload(
    image_path: Union[Path, str],
    output: Union[Path, int, str],
    compression: cros_build_lib.CompressionType,
    extra_env: Optional[Dict[str, str]] = None,
) -> None:
    """Generates a stateful update payload given a path/fd and compression.

    Args:
        image_path: Path to the image.
        output: Path or fd to the output target.
        compression: The compression to use.
        extra_env: Dictionary containing the extra environment variable(s).
    """
    logging.info("Generating stateful update payload.")

    # Mount the image to pull out the important directories.
    with osutils.TempDir() as stateful_mnt, image_lib.LoopbackPartitions(
        image_path, stateful_mnt
    ) as image:
        stateful_dir = image.Mount((constants.PART_STATE,))[0]

        try:
            logging.info("Tarring up /usr/local and /var!")
            inputs = ["dev_image", "var_overlay"]
            if os.path.exists(os.path.join(stateful_dir, "unencrypted")):
                inputs += ["unencrypted"]
            cros_build_lib.CreateTarball(
                output,
                ".",
                sudo=True,
                compression=compression,
                inputs=inputs,
                extra_args=[
                    "--selinux",
                    "--directory=%s" % stateful_dir,
                    "--transform=s,^dev_image,dev_image_new,",
                    "--transform=s,^var_overlay,var_new,",
                ],
                extra_env=extra_env,
            )
        except:
            logging.error("Failed to create stateful update file")
            raise

    if isinstance(output, int):
        logging.info("Successfully generated stateful update payload.")
    else:
        logging.info(
            "Successfully generated stateful update payload %s.", output
        )


def GenerateStatefulPayload(
    image_path: Union[Path, str], output: Union[Path, int, str]
) -> Union[Path, int, str]:
    """Generates a stateful update payload given a full path to an image.

    Args:
        image_path: Full path to the image.
        output: Can be either the path to the directory to leave the resulting
            payload or a file descriptor to write the payload into.

    Returns:
        Union[Path, int, str]: The path or fd to the generated stateful update
            payload.
    """
    if isinstance(output, int):
        output_gz = output
    else:
        output_gz = os.path.join(output, STATEFUL_FILE)

    _generate_stateful_payload(
        image_path, output_gz, cros_build_lib.CompressionType.GZIP
    )

    return output_gz


def GenerateZstdStatefulPayload(
    image_path: Union[Path, str], output: Union[Path, int, str]
) -> Union[Path, int, str]:
    """Generates a zstd stateful update payload given a full path to an image.

    Args:
        image_path: Full path to the image.
        output: Can be either the path to the directory to leave the resulting
            payload or a file descriptor to write the payload into.

    Returns:
        Union[Path, int, str]: The path or fd to the generated stateful update
            payload.
    """
    if isinstance(output, int):
        output_zstd = output
    else:
        output_zstd = os.path.join(output, constants.STATEFUL_PAYLOAD)

    _generate_stateful_payload(
        image_path,
        output_zstd,
        cros_build_lib.CompressionType.ZSTD,
        extra_env={"ZSTD_CLEVEL": "19"},
    )

    return output_zstd
