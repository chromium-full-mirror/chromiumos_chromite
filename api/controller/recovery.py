# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recovery controller."""

from typing import TYPE_CHECKING

from chromite.api import faux
from chromite.api import validate
from chromite.api.gen.chromite.api import recovery_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_target_lib
from chromite.lib import osutils
from chromite.service import kernel_image


if TYPE_CHECKING:
    from chromite.api import api_config


@faux.all_empty
@validate.require("build_target.name")
@validate.validation_complete
def CreateRecoveryKernel(
    request: recovery_pb2.CreateRecoveryKernelRequest,
    response: recovery_pb2.CreateRecoveryKernelResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Create a recovery kernel."""
    board = request.build_target.name

    # call out to script.
    install_root_path = build_target_lib.get_default_sysroot_path(
        build_target_name=board
    )

    work_dir_path = f"{install_root_path}/custom-packages"
    osutils.SafeMakedirs(work_dir_path, sudo=True)
    osutils.Chown(work_dir_path, user=True)

    path = kernel_image.BuildKernel(
        board,
        work_dir_path,
        install_root_path,
        request.flags.create_bootable_image,
    )
    response.recovery_kernel.path = str(path)
    response.recovery_kernel.location = common_pb2.Path.INSIDE
