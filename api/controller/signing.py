# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Signing controller."""

from chromite.api import faux
from chromite.api import validate
from chromite.service import image


@faux.all_empty
@validate.require("docker_image")
@validate.require("build_target.name")
@validate.exists("release_keys_checkout")
@validate.validation_complete
def CreatePreMPKeys(request, _response, _config) -> None:
    """Generate PreMPKeys for the specified build target."""
    entrypoint_args = []
    if request.dry_run:
        entrypoint_args.append("--dev")
    entrypoint_args.append(request.build_target.name)

    image.CallDocker(
        request.docker_image,
        docker_args=[
            # Mount the keyset checkout as a volume.
            "-v",
            f"{request.release_keys_checkout}:/keys",
            "--entrypoint",
            "./create_premp.sh",
        ],
        entrypoint_args=entrypoint_args,
    )
