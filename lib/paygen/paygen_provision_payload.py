# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities to handle/generate payloads for provisioning."""

import os
from pathlib import Path
from typing import List, Mapping, Optional, Union

from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import osutils
from chromite.lib.paygen import partition_lib


def GenerateProvisionPayloads(
    target_image_path: Union[Path, str], archive_dir: Union[Path, str]
) -> List[Union[Path, str]]:
    """Generates payloads needed for provisioning.

    Args:
        target_image_path: The path to the image to extract the partitions.
        archive_dir: Where to store partitions when generated.

    Returns:
        List[Union[Path, str]]: The artifacts that were produced.
    """
    payloads = []
    with osutils.TempDir() as temp_dir:
        kernel_part = "kernel.bin"
        rootfs_part = "rootfs.bin"
        partition_lib.ExtractKernel(
            target_image_path, os.path.join(temp_dir, kernel_part)
        )
        partition_lib.ExtractRoot(
            target_image_path,
            os.path.join(temp_dir, rootfs_part),
            truncate=False,
        )

        # Partition to payload mapping.
        mapping = {
            kernel_part: constants.QUICK_PROVISION_PAYLOAD_KERNEL,
            rootfs_part: constants.QUICK_PROVISION_PAYLOAD_ROOTFS,
        }
        zstd_mapping = {
            kernel_part: constants.FULL_PAYLOAD_KERN,
            rootfs_part: constants.FULL_PAYLOAD_ROOT,
        }

        if partition_lib.HasMiniOSPartitions(target_image_path):
            minios_part = "minios.bin"
            partition_lib.ExtractMiniOS(
                target_image_path, os.path.join(temp_dir, minios_part)
            )
            mapping[minios_part] = constants.QUICK_PROVISION_PAYLOAD_MINIOS
            zstd_mapping[minios_part] = constants.FULL_PAYLOAD_MINIOS

        def CompressMappings(
            mapping: Mapping[Union[Path, str], Union[Path, str]],
            compression_level: Optional[int] = None,
        ) -> List[Union[Path, str]]:
            """Compresses a mapping of payloads.

            Args:
                mapping: The mapping to process.
                compression_level: Optional compression level.

            Returns:
                A list of compressed payload paths.
            """
            compressed_payloads = []
            for partition, payload in mapping.items():
                source = os.path.join(temp_dir, partition)
                dest = os.path.join(archive_dir, payload)
                compression_lib.compress_file(
                    source, dest, compression_level=compression_level
                )
                compressed_payloads.append(dest)
            return compressed_payloads

        payloads.extend(CompressMappings(mapping))
        payloads.extend(CompressMappings(zstd_mapping, compression_level=19))

    return payloads
