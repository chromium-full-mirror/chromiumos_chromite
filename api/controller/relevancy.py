# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Relevancy Controller.

Handles the Build API endpoint for running the relevancy service.
"""

from pathlib import Path

from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import relevancy_pb2
from chromite.service import relevancy


def _MockSuccess(_request, _response, _config) -> None:
    """Mock success output for the GetRelevantBuildTargets endpoint."""

    # Default protobuf happens to indicate no relevant targets, which is an
    # example of a successful response.  Nothing to fill in here.


@faux.success(_MockSuccess)
@faux.empty_error
@validate.validation_complete
def GetRelevantBuildTargets(request, response, _config) -> None:
    """Get relevant build targets for a build using the relevancy service."""

    build_targets = controller_util.ParseBuildTargets(request.build_targets)
    paths = (Path(x.path) for x in request.affected_paths)

    for build_target, reason in relevancy.get_relevant_build_targets(
        build_targets, paths
    ):
        response.build_targets.append(
            relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget(
                build_target=build_target.to_proto(),
                reason=reason.to_proto(),
            ),
        )
