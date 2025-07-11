# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The chromeOS kernel build functionality."""

import logging
import os
from pathlib import Path
from typing import Optional

from chromite.lib import cros_build_lib
from chromite.lib import kernel_builder


def BuildKernel(
    board: str,
    work_dir: str | os.PathLike,
    install_root: str | os.PathLike,
    bootable_image: bool,
    jobs: Optional[int] = None,
    **kwargs,
) -> Path:
    """Build a ChromeOS kernel image.

    Args:
        board: Target board name (e.g., 'amd64-generic').
        work_dir: Directory for intermediate build artifacts.
        install_root: Path to the installed board root directory.
        bootable_image: Generate a bootable disk image.
        jobs: The number of parallel jobs.
        **kwargs: Additional kernel options.

    Returns:
        Path to the generated kernel image.
    """

    cros_build_lib.AssertInsideChroot()
    logging.info(
        "Starting kernel image generation for board: %s",
        board,
    )

    builder = kernel_builder.Builder(
        board=board,
        work_dir=work_dir,
        install_root=install_root,
        jobs=jobs,
    )

    kernel_image_path = builder.BuildCustomKernelImage(**kwargs)
    logging.info(
        "Successfully generated kernel image: %s",
        kernel_image_path,
    )

    if bootable_image:
        if not builder or not kernel_image_path:
            logging.error(
                "Cannot create bootable image: Kernel build state is "
                "invalid."
            )
            return None

        logging.info(
            "Attempting to generate bootable image (using placeholder "
            "function)..."
        )
        try:
            bootable_image_path = builder.generate_bootable_image(
                kernel_image_path=kernel_image_path,
            )
            logging.info(
                "Placeholder generated bootable image: %s",
                bootable_image_path,
            )
            logging.warning(
                "Bootable image generation function is currently a "
                "placeholder."
            )

        except NotImplementedError:
            logging.warning(
                "Bootable image generation step was called, but it is "
                "not yet implemented in the library."
            )
        except AttributeError:
            logging.warning(
                "The 'generate_bootable_image' method is not available on "
                "the Builder object. Bootable image generation skipped."
            )

    return kernel_image_path
