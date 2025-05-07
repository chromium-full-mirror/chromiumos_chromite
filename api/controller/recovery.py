# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recovery controller."""

from typing import TYPE_CHECKING

from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import recovery_pb2


if TYPE_CHECKING:
    from chromite.api import api_config


@faux.all_empty
@validate.require("build_target.name")
@validate.validation_complete
def CreateRecoveryKernel(
    request: recovery_pb2.CreateRecoveryKernelRequest,
    _response: recovery_pb2.CreateRecoveryKernelResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Create a recovery kernel."""
    _chroot = controller_util.ParseChroot(request.chroot)
    board = request.build_target.name

    # call out to script.
    # TODO(b/371247934): replace with real script when it's stable and merged.
    cmd = ["path/to/your/actual_script.sh", "--board", board]
    if request.flags.CREATE_BOOTABLE_IMAGE_FIELD_NUMBER:
        cmd += ["--create-bootable-image"]
    # We'll need to rename the vars without the underscores once we're ready to
    # use, but the linter is angry at that.
    # path = chroot.run(cmd)
    # response.recovery_kernel = path
