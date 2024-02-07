# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Signing controller."""

from chromite.api import faux
from chromite.api import validate


@faux.all_empty
@validate.require("build_target.name")
@validate.validation_complete
def CreatePreMPKeys(_request, _response, _config) -> None:
    """Generate PreMPKeys for the specified build target."""
    return
