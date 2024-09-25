# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for ChromeLkgm operations."""

from chromite.api import api_config
from chromite.api.controller import chrome_lkgm
from chromite.api.gen.chromite.api import chrome_lkgm_pb2
from chromite.lib import chrome_lkgm as chrome_lkgm_lib
from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib import gs_unittest
from chromite.lib import partial_mock


class FindLkgmTest(cros_test_lib.MockTestCase, api_config.ApiConfigMixin):
    """Unittests for FindLkgm with mocking chrome_lkgm_lib."""

    LKGM_VERSION = "123.0.0.4566"
    LKGM_SNAPSHOT_NUMBER = 123456
    LKGM_SNAPSHOT_VERSION = LKGM_VERSION + "-" + str(LKGM_SNAPSHOT_NUMBER)
    FALLBACK_VERSION = "123.0.0.4562"

    def setUp(self) -> None:
        self.request = chrome_lkgm_pb2.FindLkgmRequest()
        self.request.build_target.name = "newboard"
        self.request.chrome_src = "/home/user/chromium/src"
        self.request.fallback_versions = 10
        self.response = chrome_lkgm_pb2.FindLkgmResponse()
        self.finder_mock = self.PatchObject(
            chrome_lkgm_lib, "ChromeOSVersionFinder"
        )
        self.instance = self.finder_mock.return_value

        config_name = f"{self.request.build_target.name}/release"
        self.get_full_version_mock = self.PatchObject(
            self.instance,
            "GetLatestVersionInfo",
            return_value=self.FALLBACK_VERSION,
        )

        self.PatchObject(
            chrome_lkgm_lib, "GetGsConfigName", return_value=config_name
        )

    def testInvalidLkgm(self) -> None:
        """LKGM version file found, but not successfully parsed."""

        self.PatchObject(
            chrome_lkgm_lib, "GetChromeLkgm", return_value=(None, None)
        )

        chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertTrue(self.response.error)
        self.get_full_version_mock.assert_not_called()

    def testLkgmNotFound(self) -> None:
        """LKGM version file not found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            side_effect=chrome_lkgm_lib.MissingLkgmFile(
                "CHROMEOS_LKGM not found"
            ),
        )

        chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertTrue(self.response.error)
        self.get_full_version_mock.assert_not_called()

    def testLkgmInvalid(self) -> None:
        """LKGM version file not found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            side_effect=RuntimeError("invalid LKGM file"),
        )

        chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertTrue(self.response.error)
        self.get_full_version_mock.assert_not_called()

    def testLkgmFound(self) -> None:
        """LKGM version found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, None),
        )

        chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(self.FALLBACK_VERSION, self.response.full_version)
        self.assertEqual("newboard/release", self.response.config_name)
        self.assertEqual(self.LKGM_VERSION, self.response.chromeos_lkgm)
        self.get_full_version_mock.assert_called_with(self.LKGM_VERSION, None)

    def testLkgmSnapshotFound(self) -> None:
        """LKGM version found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, self.LKGM_SNAPSHOT_NUMBER),
        )

        chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(self.FALLBACK_VERSION, self.response.full_version)
        self.assertEqual("newboard/release", self.response.config_name)
        self.assertEqual(
            self.LKGM_SNAPSHOT_VERSION, self.response.chromeos_lkgm
        )
        self.get_full_version_mock.assert_called_with(
            self.LKGM_VERSION, self.LKGM_SNAPSHOT_NUMBER
        )

    def testFailToGetFullVersion(self) -> None:
        """LKGM version found, but fallbacked full version wasn't found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, None),
        )
        self.PatchObject(
            self.instance,
            "GetLatestVersionInfo",
            return_value=None,
        )

        chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertTrue(self.response.error)


class FindLkgmGSTest(cros_test_lib.MockTestCase, api_config.ApiConfigMixin):
    """Unittests for FindLkgm with mocking GS access."""

    LKGM_VERSION = "12345.0.0"
    LKGM_SNAPSHOT_NUMBER = 123456
    LKGM_SNAPSHOT_VERSION = LKGM_VERSION + "-" + str(LKGM_SNAPSHOT_NUMBER)
    FULL_VERSION = "R123-12345.0.0"
    FULL_VERSION_FALLBACK = "R123-12344.0.0"
    FULL_VERSION_WITH_SNAPSHOT = (
        f"{FULL_VERSION}-{str(LKGM_SNAPSHOT_NUMBER)}-8888888888"
    )
    FULL_VERSION_FALLBACK_WITH_SNAPSHOT = (
        f"{FULL_VERSION}-{str(LKGM_SNAPSHOT_NUMBER - 1)}-8888888888"
    )

    def setUp(self) -> None:
        self.request = chrome_lkgm_pb2.FindLkgmRequest()
        self.request.build_target.name = "newboard"
        self.request.chrome_src = "/home/user/chromium/src"
        self.request.fallback_versions = 10
        self.response = chrome_lkgm_pb2.FindLkgmResponse()
        self.gs_mock = gs_unittest.GSContextMock()

    def testGSQuery(self) -> None:
        """LKGM version found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, None),
        )
        self.gs_mock.SetDefaultCmdResult()
        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % self.LKGM_VERSION),
            stdout=self.FULL_VERSION,
        )

        with self.gs_mock:
            chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(self.FULL_VERSION, self.response.full_version)
        self.assertEqual("newboard-release", self.response.config_name)
        self.assertEqual(self.LKGM_VERSION, self.response.chromeos_lkgm)

    def testGSQueryPublic(self) -> None:
        """LKGM version found (public board)."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, None),
        )

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % self.LKGM_VERSION),
            stdout=self.FULL_VERSION,
        )

        self.request.use_external_config = True
        with self.gs_mock:
            chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(self.FULL_VERSION, self.response.full_version)
        self.assertEqual("newboard-public", self.response.config_name)
        self.assertEqual(self.LKGM_VERSION, self.response.chromeos_lkgm)

    def testGSQueryFallback(self) -> None:
        """LKGM version not found, but fallbacked previous version found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, None),
        )

        def _RaiseException(*_args, **_kwargs) -> None:
            raise gs.GSNoSuchKey("file does not exist")

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-%s" % self.LKGM_VERSION),
            side_effect=_RaiseException,
        )

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex("cat .*/LATEST-12344.0.0"),
            stdout=self.FULL_VERSION_FALLBACK,
        )

        with self.gs_mock:
            chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(self.FULL_VERSION_FALLBACK, self.response.full_version)
        self.assertEqual("newboard-release", self.response.config_name)
        self.assertEqual(self.LKGM_VERSION, self.response.chromeos_lkgm)

    def testGSQuerySnapshot(self) -> None:
        """LKGM version (with snapshot number) found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, self.LKGM_SNAPSHOT_NUMBER),
        )

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-SNAPSHOT-%s" % self.LKGM_SNAPSHOT_NUMBER
            ),
            stdout=self.FULL_VERSION_WITH_SNAPSHOT,
        )

        with self.gs_mock:
            chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(
            self.FULL_VERSION_WITH_SNAPSHOT, self.response.full_version
        )
        self.assertEqual("newboard-snapshot", self.response.config_name)
        self.assertEqual(
            self.LKGM_SNAPSHOT_VERSION, self.response.chromeos_lkgm
        )

    def testGSQueryPublicSnapshot(self) -> None:
        """LKGM version found (public board)."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, self.LKGM_SNAPSHOT_NUMBER),
        )

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-SNAPSHOT-%s" % self.LKGM_SNAPSHOT_NUMBER
            ),
            stdout=self.FULL_VERSION_WITH_SNAPSHOT,
        )

        self.request.use_external_config = True
        with self.gs_mock:
            chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(
            self.FULL_VERSION_WITH_SNAPSHOT, self.response.full_version
        )
        self.assertEqual("newboard-public-snapshot", self.response.config_name)
        self.assertEqual(
            self.LKGM_SNAPSHOT_VERSION, self.response.chromeos_lkgm
        )

    def testGSQueryFallbackSnapshot(self) -> None:
        """LKGM version not found, but fallbacked previous version found."""

        self.PatchObject(
            chrome_lkgm_lib,
            "GetChromeLkgm",
            return_value=(self.LKGM_VERSION, self.LKGM_SNAPSHOT_NUMBER),
        )

        def _RaiseException(*_args, **_kwargs) -> None:
            raise gs.GSNoSuchKey("file does not exist")

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-SNAPSHOT-%s" % self.LKGM_SNAPSHOT_NUMBER
            ),
            side_effect=_RaiseException,
        )

        self.gs_mock.AddCmdResult(
            partial_mock.ListRegex(
                "cat .*/LATEST-SNAPSHOT-%s" % (self.LKGM_SNAPSHOT_NUMBER - 1)
            ),
            stdout=self.FULL_VERSION_FALLBACK_WITH_SNAPSHOT,
        )

        with self.gs_mock:
            chrome_lkgm.FindLkgm(self.request, self.response, self.api_config)
        self.assertFalse(self.response.error)
        self.assertEqual(
            self.FULL_VERSION_FALLBACK_WITH_SNAPSHOT, self.response.full_version
        )
        self.assertEqual("newboard-snapshot", self.response.config_name)
        self.assertEqual(
            self.LKGM_SNAPSHOT_VERSION, self.response.chromeos_lkgm
        )
