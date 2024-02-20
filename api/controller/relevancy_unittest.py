# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for relevancy controller."""

from pathlib import Path
from unittest import mock

import pytest

from chromite.api import api_config
from chromite.api.controller import relevancy
from chromite.api.gen.chromite.api import relevancy_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_target_lib
from chromite.service import relevancy as relevancy_service


_FAKE_request = relevancy_pb2.GetRelevantBuildTargetsRequest(
    build_targets=[
        common_pb2.BuildTarget(name="fake"),
        common_pb2.BuildTarget(name="foo"),
    ],
    affected_paths=[
        relevancy_pb2.Path(path="src/platform/fake/subdir/foo.c"),
        relevancy_pb2.Path(path="src/overlays/overlay-fake/toolchains.conf"),
    ],
)
_REASON_PATH_RULE = relevancy_service.ReasonPathRule(
    trigger=Path("chromite/bin/baz"),
    pattern="chromite/.*",
)
_RELEVANT_TARGET = relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget(
    build_target=common_pb2.BuildTarget(
        name="fake",
        profile=common_pb2.Profile(name="base"),
    ),
    reason=_REASON_PATH_RULE.to_proto(),
)


@pytest.mark.parametrize(
    ("mocked_results", "expected_response"),
    [
        (
            [(build_target_lib.BuildTarget("fake"), _REASON_PATH_RULE)],
            relevancy_pb2.GetRelevantBuildTargetsResponse(
                build_targets=[_RELEVANT_TARGET],
            ),
        ),
    ],
)
def test_get_relevant_build_targets(mocked_results, expected_response) -> None:
    with mock.patch(
        "chromite.service.relevancy.get_relevant_build_targets",
        return_value=mocked_results,
    ):
        response = relevancy_pb2.GetRelevantBuildTargetsResponse()
        relevancy.GetRelevantBuildTargets(
            _FAKE_request,
            response,
            api_config.ApiConfig(),
        )
        assert response == expected_response
