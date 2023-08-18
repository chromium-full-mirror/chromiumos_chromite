# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the sdk_subtools api layer."""

import os
from typing import Dict, Iterator, Optional, Union
from unittest import mock

import pytest

from chromite.api import api_config
from chromite.api.controller import sdk_subtools
from chromite.api.gen.chromite.api import sdk_subtools_pb2
from chromite.lib import cros_build_lib
from chromite.lib import sysroot_lib
from chromite.lib.parser import package_info


def make_request(
    chroot_path: Union[str, os.PathLike, None] = "fake_chroot_path"
) -> sdk_subtools_pb2.BuildSdkSubtoolsRequest:
    """Helper to build a request message."""
    request = sdk_subtools_pb2.BuildSdkSubtoolsRequest()
    if chroot_path is not None:
        request.chroot.path = os.fspath(chroot_path)
    return request


def build_sdk_subtools(
    request: sdk_subtools_pb2.BuildSdkSubtoolsRequest,
    call_type: Optional[int] = api_config.ApiConfig.CALL_TYPE_EXECUTE,
) -> sdk_subtools_pb2.BuildSdkSubtoolsResponse:
    """Invokes sdk_subtools.BuildSdkSubtools and return the response proto."""
    config = api_config.ApiConfig(call_type)
    response = sdk_subtools_pb2.BuildSdkSubtoolsResponse()
    sdk_subtools.BuildSdkSubtools(request, response, config)
    return response


MockService = Dict[str, mock.MagicMock]


@pytest.fixture(name="mock_service")
def mock_service_fixture() -> Iterator[MockService]:
    """Mocks the sdk_subtools service layer with mocks."""
    with mock.patch.multiple(
        "chromite.service.sdk_subtools",
        setup_base_sdk=mock.DEFAULT,
        update_packages=mock.DEFAULT,
        bundle_and_export=mock.DEFAULT,
    ) as dict_of_mocks:
        yield dict_of_mocks


def test_validate_only(mock_service: MockService) -> None:
    """Verify a validate-only call does not execute any logic."""
    build_sdk_subtools(
        make_request(), api_config.ApiConfig.CALL_TYPE_VALIDATE_ONLY
    )
    for f in mock_service.values():
        f.assert_not_called()


def test_mock_call(mock_service: MockService) -> None:
    """Consistency check that a mock call does not execute any logic."""
    build_sdk_subtools(
        make_request(), api_config.ApiConfig.CALL_TYPE_MOCK_SUCCESS
    )
    for f in mock_service.values():
        f.assert_not_called()


def test_success(mock_service: MockService) -> None:
    """Test the successful call output handling."""
    response = build_sdk_subtools(make_request())
    mock_service["setup_base_sdk"].assert_called_once()
    mock_service["update_packages"].assert_called_once()
    mock_service["bundle_and_export"].assert_called_once()
    assert not response.failed_package_data


def test_package_update_failure(mock_service: MockService) -> None:
    """Test output handling when package update fails."""
    mock_service[
        "update_packages"
    ].side_effect = sysroot_lib.PackageInstallError(
        "mock failure",
        cros_build_lib.CompletedProcess(),
        packages=[package_info.parse("some-category/some-package-0.42-r43")],
    )
    response = build_sdk_subtools(make_request())
    mock_service["setup_base_sdk"].assert_called_once()
    mock_service["update_packages"].assert_called_once()
    mock_service["bundle_and_export"].assert_not_called()
    assert len(response.failed_package_data) == 1
    assert response.failed_package_data[0].name.package_name == "some-package"
    assert response.failed_package_data[0].name.category == "some-category"
    assert response.failed_package_data[0].name.version == "0.42-r43"
