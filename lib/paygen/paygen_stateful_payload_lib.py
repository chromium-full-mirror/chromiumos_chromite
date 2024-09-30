# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities to handle/generate CrOS stateful payloads."""

import logging
import os
from pathlib import Path
from typing import List, Optional, Union

from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import image_lib
from chromite.lib import metrics_lib
from chromite.lib import osutils


def _generate_stateful_payload(
    image_path: Union[Path, str],
    output: Union[Path, int, str],
    compression: compression_lib.CompressionType,
    compressor: Optional[List[str]] = None,
) -> None:
    """Generates a stateful update payload given a path/fd and compression.

    Args:
        image_path: Path to the image.
        output: Path or fd to the output target.
        compression: The compression to use.
        compressor: Explicitly specify the compressor to use.
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
            compression_lib.create_tarball(
                output,
                ".",
                sudo=True,
                compression=compression,
                compressor=compressor,
                inputs=inputs,
                extra_args=[
                    "--selinux",
                    "--directory=%s" % stateful_dir,
                    "--transform=s,^dev_image,dev_image_new,",
                    "--transform=s,^var_overlay,var_new,",
                ],
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


@metrics_lib.timed("paygen_stateful_payload_lib.GenerateStatefulPayload")
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
        output_gz = os.path.join(
            output, constants.QUICK_PROVISION_PAYLOAD_STATEFUL
        )

    _generate_stateful_payload(
        image_path, output_gz, compression_lib.CompressionType.GZIP
    )

    return output_gz


@metrics_lib.timed("paygen_stateful_payload_lib.GenerateZstdStatefulPayload")
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
        compression_lib.CompressionType.ZSTD,
        compressor=["zstdmt", "-19"],
    )

    return output_zstd
