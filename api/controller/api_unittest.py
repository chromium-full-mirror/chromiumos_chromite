# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API controller tests."""

from chromite.api import api_config
from chromite.api import router
from chromite.api.controller import api as api_controller
from chromite.api.gen.chromite.api import api_pb2
from chromite.lib import constants
from chromite.lib import cros_test_lib


class CompileProtoTest(
    cros_test_lib.RunCommandTestCase, api_config.ApiConfigMixin
):
    """CompileProto tests."""

    def setUp(self) -> None:
        # MyPy has been configured to ignore generated files, including proto
        # bindings, so silence the error for proto constructs.
        self.request = (
            api_pb2.CompileProtoRequest()  # type: ignore[attr-defined]
        )
        self.response = (
            api_pb2.CompileProtoResponse()  # type: ignore[attr-defined]
        )

    def testCompileProto(self) -> None:
        """Quick CompileProto functional check."""
        self.rc.SetDefaultCmdResult(stdout=" M foo/bar.py")
        expected = [str(constants.CHROMITE_DIR / "foo" / "bar.py")]

        api_controller.CompileProto(
            self.request, self.response, self.api_config
        )
        returned = [f.path for f in self.response.modified_files]

        self.assertCountEqual(expected, returned)
        self.assertTrue(all(f in returned for f in expected))
        self.assertTrue(all(f in expected for f in returned))

    def testValidateOnly(self) -> None:
        """Verify validate only calls do not execute logic."""
        api_controller.CompileProto(
            self.request, self.response, self.validate_only_config
        )

        self.assertFalse(self.rc.call_count)

    def testMockSuccess(self) -> None:
        """Verify mock success calls do not execute logic."""
        api_controller.CompileProto(
            self.request, self.response, self.mock_call_config
        )
        self.assertTrue(len(self.response.modified_files))
        self.assertFalse(self.rc.call_count)


class GetMethodsTest(cros_test_lib.MockTestCase, api_config.ApiConfigMixin):
    """GetMethods tests."""

    def setUp(self) -> None:
        # MyPy has been configured to ignore generated files, including proto
        # bindings, so silence the error for proto constructs.
        self.request = api_pb2.MethodGetRequest()  # type: ignore[attr-defined]
        self.response = (
            api_pb2.MethodGetResponse()  # type: ignore[attr-defined]
        )

    def testGetMethods(self) -> None:
        """Simple GetMethods check."""
        methods = ["foo", "bar"]
        self.PatchObject(router.Router, "ListMethods", return_value=methods)

        api_controller.GetMethods(self.request, self.response, self.api_config)

        self.assertCountEqual(
            methods, [m.method for m in self.response.methods]
        )

    def testValidateOnly(self) -> None:
        """Check validate_only_config calls only validate."""
        patch = self.PatchObject(router.Router, "ListMethods")

        api_controller.GetMethods(
            self.request, self.response, self.validate_only_config
        )

        patch.assert_not_called()


class GetVersionTest(cros_test_lib.MockTestCase, api_config.ApiConfigMixin):
    """GetVersion tests."""

    def setUp(self) -> None:
        self.PatchObject(api_controller, "VERSION_MAJOR", new=1)
        self.PatchObject(api_controller, "VERSION_MINOR", new=2)
        self.PatchObject(api_controller, "VERSION_BUG", new=3)

        # MyPy has been configured to ignore generated files, including proto
        # bindings, so silence the error for proto constructs.
        self.request = api_pb2.VersionGetRequest()  # type: ignore[attr-defined]
        self.response = (
            api_pb2.VersionGetResponse()  # type: ignore[attr-defined]
        )

    def testGetVersion(self) -> None:
        """Simple GetVersion check."""
        api_controller.GetVersion(self.request, self.response, self.api_config)

        self.assertEqual(self.response.version.major, 1)
        self.assertEqual(self.response.version.minor, 2)
        self.assertEqual(self.response.version.bug, 3)

    def testValidateOnly(self) -> None:
        """Check validate_only_config calls only validate."""
        api_controller.GetVersion(
            self.request, self.response, self.validate_only_config
        )

        self.assertFalse(self.response.version.major)
        self.assertFalse(self.response.version.minor)
        self.assertFalse(self.response.version.bug)
