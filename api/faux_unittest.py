# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the faux module."""

from chromite.api import api_config
from chromite.api import faux
from chromite.api.gen.chromite.api import build_api_test_pb2
from chromite.lib import cros_test_lib


class MockResponsesTest(cros_test_lib.TestCase, api_config.ApiConfigMixin):
    """Tests for faux's mock response functionality."""

    _IMPL_RESULT = "result"
    _SUCCESS_RESULT = "success"
    _ERROR_RESULT = "error"
    _ALL_RESULT = "all"

    def setUp(self) -> None:
        self.request = build_api_test_pb2.TestRequestMessage()
        self.response = build_api_test_pb2.TestResultMessage()

    def _faux_success(self, _request, response, _config) -> None:
        """Faux success method."""
        response.result = self._SUCCESS_RESULT

    def _faux_error(self, _request, response, _config) -> None:
        """Faux error method."""
        response.result = self._ERROR_RESULT

    def _faux_all(self, _request, response, config) -> None:
        """All responses method."""
        self.assertIn(config, [self.mock_call_config, self.mock_error_config])
        response.result = self._ALL_RESULT

    def test_call_called(self) -> None:
        """Test a faux call."""

        @faux.error(self._faux_error)
        @faux.success(self._faux_success)
        def impl(_request, _response, _config) -> None:
            self.fail("Implementation was called.")

        impl(self.request, self.response, self.mock_call_config)

        self.assertEqual(self.response.result, self._SUCCESS_RESULT)

    def test_error_called(self) -> None:
        """Test the faux error intercepts the call."""

        @faux.success(self._faux_success)
        @faux.error(self._faux_error)
        def impl(_request, _response, _config) -> None:
            self.fail("Implementation was called.")

        impl(self.request, self.response, self.mock_error_config)

        self.assertEqual(self.response.result, self._ERROR_RESULT)

    def test_impl_called(self) -> None:
        """Test the call is not mocked when not requested."""

        @faux.error(self._faux_error)
        @faux.success(self._faux_success)
        def impl(_request, response, _config) -> None:
            response.result = self._IMPL_RESULT

        impl(self.request, self.response, self.api_config)

        self.assertEqual(self.response.result, self._IMPL_RESULT)

    def test_all_responses_success(self) -> None:
        """Test the call is intercepted by the all responses decorator."""

        @faux.all_responses(self._faux_all)
        def impl(_request, _response, _config) -> None:
            self.fail("Implementation was called.")

        impl(self.request, self.response, self.mock_call_config)
        self.assertEqual(self.response.result, self._ALL_RESULT)

    def test_all_responses_error(self) -> None:
        """Test the call is intercepted by the all responses decorator."""

        @faux.all_responses(self._faux_all)
        def impl(_request, _response, _config) -> None:
            self.fail("Implementation was called.")

        impl(self.request, self.response, self.mock_error_config)
        self.assertEqual(self.response.result, self._ALL_RESULT)

    def test_all_responses_impl(self) -> None:
        """Test the call is intercepted by the all responses decorator."""

        @faux.all_responses(self._faux_all)
        def impl(_request, response, _config) -> None:
            response.result = self._IMPL_RESULT

        impl(self.request, self.response, self.api_config)
        self.assertEqual(self.response.result, self._IMPL_RESULT)
