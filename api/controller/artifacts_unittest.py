# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for Artifacts operations."""

import os
import pathlib
from typing import Optional
from unittest import mock

from chromite.api import api_config
from chromite.api.controller import artifacts
from chromite.api.controller import controller_util
from chromite.api.controller import image as image_controller
from chromite.api.controller import sysroot as sysroot_controller
from chromite.api.controller import test as test_controller
from chromite.api.gen.chromite.api import artifacts_pb2
from chromite.api.gen.chromite.api import sysroot_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.cbuildbot import commands
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import sysroot_lib
from chromite.service import artifacts as artifacts_svc


class BundleRequestMixin:
    """Mixin to provide bundle request methods."""

    def EmptyRequest(self):
        return artifacts_pb2.BundleRequest()

    def BuildTargetRequest(
        self, build_target=None, output_dir=None, chroot=None
    ):
        """Get a build target format request instance."""
        request = self.EmptyRequest()
        if build_target:
            request.build_target.name = build_target
        if output_dir:
            request.result_path.path.path = str(output_dir)
            request.result_path.path.location = common_pb2.Path.Location.OUTSIDE
        if chroot:
            request.chroot.path = chroot

        return request

    def SysrootRequest(
        self,
        sysroot=None,
        build_target=None,
        output_dir=None,
        chroot=None,
        chroot_out=None,
    ):
        """Get a sysroot format request instance."""
        request = self.EmptyRequest()
        if sysroot:
            request.sysroot.path = sysroot
        if build_target:
            request.sysroot.build_target.name = build_target
        if output_dir:
            request.result_path.path.path = output_dir
            request.result_path.path.location = common_pb2.Path.Location.OUTSIDE
        if chroot:
            request.chroot.path = str(chroot)
        if chroot_out:
            request.chroot.out_path = str(chroot_out)

        return request


class BundleTestCase(
    cros_test_lib.MockTempDirTestCase,
    api_config.ApiConfigMixin,
    BundleRequestMixin,
):
    """Basic setup for all artifacts unittests."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        self.output_dir = os.path.join(self.tempdir, "artifacts")
        osutils.SafeMakedirs(self.output_dir)
        self.sysroot_path = "/build/target"
        self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)
        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        full_sysroot_path = self.chroot.full_path(self.sysroot_path)
        osutils.SafeMakedirs(full_sysroot_path)
        osutils.SafeMakedirs(self.chroot.path)
        osutils.SafeMakedirs(self.chroot.out_path)

        # All requests use same response type.
        self.response = artifacts_pb2.BundleResponse()

        # Build target request.
        self.target_request = self.BuildTargetRequest(
            build_target="target",
            output_dir=self.output_dir,
            chroot=self.chroot.path,
        )

        # Sysroot request.
        self.sysroot_request = self.SysrootRequest(
            sysroot=self.sysroot_path,
            build_target="target",
            output_dir=self.output_dir,
            chroot=self.chroot.path,
            chroot_out=self.chroot.out_path,
        )

        self.source_root = self.tempdir
        self.PatchObject(constants, "SOURCE_ROOT", new=self.tempdir)


class BundleImageArchivesTest(BundleTestCase):
    """BundleImageArchives tests."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "ArchiveImages")
        artifacts.BundleImageArchives(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "ArchiveImages")
        artifacts.BundleImageArchives(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 2)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "path0.tar.xz"),
        )
        self.assertEqual(
            self.response.artifacts[1].artifact_path.path,
            os.path.join(self.output_dir, "path1.tar.xz"),
        )

    def testNoBuildTarget(self) -> None:
        """Test that no build target fails."""
        request = self.BuildTargetRequest(output_dir=str(self.tempdir))
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleImageArchives(
                request, self.response, self.api_config
            )

    def testNoOutputDir(self) -> None:
        """Test no output dir fails."""
        request = self.BuildTargetRequest(build_target="board")
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleImageArchives(
                request, self.response, self.api_config
            )

    def testInvalidOutputDir(self) -> None:
        """Test invalid output dir fails."""
        request = self.BuildTargetRequest(
            build_target="board", output_dir=os.path.join(self.tempdir, "DNE")
        )
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleImageArchives(
                request, self.response, self.api_config
            )

    def testOutputHandling(self) -> None:
        """Test the artifact output handling."""
        expected = [os.path.join(self.output_dir, f) for f in ("a", "b", "c")]
        self.PatchObject(artifacts_svc, "ArchiveImages", return_value=expected)
        self.PatchObject(os.path, "exists", return_value=True)

        artifacts.BundleImageArchives(
            self.sysroot_request, self.response, self.api_config
        )

        self.assertCountEqual(
            expected, [a.artifact_path.path for a in self.response.artifacts]
        )


class BundleImageZipTest(BundleTestCase):
    """Unittests for BundleImageZip."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(commands, "BuildImageZip")
        artifacts.BundleImageZip(
            self.target_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(commands, "BuildImageZip")
        artifacts.BundleImageZip(
            self.target_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "image.zip"),
        )

    def testBundleImageZip(self) -> None:
        """BundleImageZip calls cbuildbot/commands with correct args."""
        bundle_image_zip = self.PatchObject(
            artifacts_svc, "BundleImageZip", return_value="image.zip"
        )
        self.PatchObject(os.path, "exists", return_value=True)
        artifacts.BundleImageZip(
            self.target_request, self.response, self.api_config
        )
        self.assertEqual(
            [
                artifact.artifact_path.path
                for artifact in self.response.artifacts
            ],
            [os.path.join(self.output_dir, "image.zip")],
        )

        latest = os.path.join(
            self.source_root, "src/build/images/target/latest"
        )
        self.assertEqual(
            bundle_image_zip.call_args_list,
            [mock.call(self.output_dir, latest)],
        )

    def testBundleImageZipNoImageDir(self) -> None:
        """BundleImageZip dies when image dir does not exist."""
        self.PatchObject(os.path, "exists", return_value=False)
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleImageZip(
                self.target_request, self.response, self.api_config
            )


class BundleAutotestFilesTest(BundleTestCase):
    """Unittests for BundleAutotestFiles."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleAutotestFiles")
        artifacts.BundleAutotestFiles(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleAutotestFiles")
        artifacts.BundleAutotestFiles(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "autotest-a.tar.gz"),
        )

    def testBundleAutotestFiles(self) -> None:
        """BundleAutotestFiles calls service correctly."""

        files = {
            artifacts_svc.ARCHIVE_CONTROL_FILES: (
                "/tmp/artifacts/autotest-a.tar.gz"
            ),
            artifacts_svc.ARCHIVE_PACKAGES: "/tmp/artifacts/autotest-b.tar.gz",
        }
        patch = self.PatchObject(
            artifacts_svc, "BundleAutotestFiles", return_value=files
        )

        artifacts.BundleAutotestFiles(
            self.sysroot_request, self.response, self.api_config
        )

        # Verify the arguments are being passed through.
        patch.assert_called_with(mock.ANY, self.sysroot, self.output_dir)

        # Verify the output proto is being populated correctly.
        self.assertTrue(self.response.artifacts)
        paths = [
            artifact.artifact_path.path for artifact in self.response.artifacts
        ]
        self.assertCountEqual(list(files.values()), paths)

    def testInvalidOutputDir(self) -> None:
        """Test invalid output directory argument."""
        request = self.SysrootRequest(
            chroot=self.chroot.path, sysroot=self.sysroot_path
        )

        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleAutotestFiles(
                request, self.response, self.api_config
            )

    def testInvalidSysroot(self) -> None:
        """Test no sysroot directory."""
        request = self.SysrootRequest(
            chroot=self.chroot.path, output_dir=self.output_dir
        )

        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleAutotestFiles(
                request, self.response, self.api_config
            )

    def testSysrootDoesNotExist(self) -> None:
        """Test dies when no sysroot does not exist."""
        request = self.SysrootRequest(
            chroot=self.chroot.path,
            sysroot="/does/not/exist",
            output_dir=self.output_dir,
        )

        artifacts.BundleAutotestFiles(request, self.response, self.api_config)
        self.assertFalse(self.response.artifacts)


class BundleTastFilesTest(BundleTestCase):
    """Unittests for BundleTastFiles."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleTastFiles")
        artifacts.BundleTastFiles(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleTastFiles")
        artifacts.BundleTastFiles(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 2)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "tast_bundles.tar.gz"),
        )

    def testBundleTastFilesNoLogs(self) -> None:
        """BundleTasteFiles succeeds when no tast files found."""
        self.PatchObject(commands, "BuildTastBundleTarball", return_value=None)
        artifacts.BundleTastFiles(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertFalse(self.response.artifacts)

    def testBundleTastFiles(self) -> None:
        """BundleTastFiles calls service correctly."""
        expected_archive = os.path.join(
            self.output_dir, artifacts_svc.TAST_BUNDLE_NAME
        )
        # Patch the service being called.
        bundle_patch = self.PatchObject(
            artifacts_svc, "BundleTastFiles", return_value=expected_archive
        )

        artifacts.BundleTastFiles(
            self.sysroot_request, self.response, self.api_config
        )

        # Make sure the artifact got recorded successfully.
        self.assertTrue(self.response.artifacts)
        self.assertEqual(
            expected_archive, self.response.artifacts[0].artifact_path.path
        )
        # Make sure the service got called correctly.
        bundle_patch.assert_called_once_with(
            self.chroot, self.sysroot, self.output_dir
        )


class BundleFirmwareTest(BundleTestCase):
    """Unittests for BundleFirmware."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleTastFiles")
        artifacts.BundleFirmware(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleTastFiles")
        artifacts.BundleFirmware(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "firmware.tar.gz"),
        )

    def testBundleFirmware(self) -> None:
        """BundleFirmware calls cbuildbot/commands with correct args."""
        self.PatchObject(
            artifacts_svc,
            "BuildFirmwareArchive",
            return_value=os.path.join(
                self.output_dir, constants.FIRMWARE_ARCHIVE_NAME
            ),
        )
        self.PatchObject(
            artifacts_svc,
            "BuildPinnedFirmwareArchive",
            return_value=os.path.join(
                self.output_dir, constants.FIRMWARE_PINNED_ARCHIVE_NAME
            ),
        )

        artifacts.BundleFirmware(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertEqual(
            [
                artifact.artifact_path.path
                for artifact in self.response.artifacts
            ],
            [
                os.path.join(self.output_dir, "firmware_from_source.tar.bz2"),
                os.path.join(self.output_dir, "pinned_firmware.tar.bz2"),
            ],
        )

    def testBundleFirmwareNoLogs(self) -> None:
        """BundleFirmware dies when no firmware found."""
        self.PatchObject(commands, "BuildFirmwareArchive", return_value=None)
        artifacts.BundleFirmware(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertEqual(len(self.response.artifacts), 0)


class BundleFpmcuUnittestsTest(BundleTestCase):
    """Unittests for BundleFpmcuUnittests."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleFpmcuUnittests")
        artifacts.BundleFpmcuUnittests(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleFpmcuUnittests")
        artifacts.BundleFpmcuUnittests(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "fpmcu_unittests.tar.gz"),
        )

    def testBundleFpmcuUnittests(self) -> None:
        """BundleFpmcuUnittests calls cbuildbot/commands with correct args."""
        self.PatchObject(
            artifacts_svc,
            "BundleFpmcuUnittests",
            return_value=os.path.join(
                self.output_dir, "fpmcu_unittests.tar.gz"
            ),
        )
        artifacts.BundleFpmcuUnittests(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertEqual(
            [
                artifact.artifact_path.path
                for artifact in self.response.artifacts
            ],
            [os.path.join(self.output_dir, "fpmcu_unittests.tar.gz")],
        )

    def testBundleFpmcuUnittestsNoLogs(self) -> None:
        """BundleFpmcuUnittests does not die when no fpmcu unittests found."""
        self.PatchObject(
            artifacts_svc, "BundleFpmcuUnittests", return_value=None
        )
        artifacts.BundleFpmcuUnittests(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertFalse(self.response.artifacts)


class BundleEbuildLogsTest(BundleTestCase):
    """Unittests for BundleEbuildLogs."""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(commands, "BuildEbuildLogsTarball")
        artifacts.BundleEbuildLogs(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(commands, "BuildEbuildLogsTarball")
        artifacts.BundleEbuildLogs(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "ebuild-logs.tar.gz"),
        )

    def testBundleEbuildLogs(self) -> None:
        """BundleEbuildLogs calls cbuildbot/commands with correct args."""
        bundle_ebuild_logs_tarball = self.PatchObject(
            artifacts_svc,
            "BundleEBuildLogsTarball",
            return_value="ebuild-logs.tar.gz",
        )
        artifacts.BundleEbuildLogs(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertEqual(
            [
                artifact.artifact_path.path
                for artifact in self.response.artifacts
            ],
            [os.path.join(self.output_dir, "ebuild-logs.tar.gz")],
        )
        self.assertEqual(
            bundle_ebuild_logs_tarball.call_args_list,
            [mock.call(mock.ANY, self.sysroot, self.output_dir)],
        )

    def testBundleEbuildLogsNoLogs(self) -> None:
        """BundleEbuildLogs dies when no logs found."""
        self.PatchObject(commands, "BuildEbuildLogsTarball", return_value=None)
        artifacts.BundleEbuildLogs(
            self.sysroot_request, self.response, self.api_config
        )

        self.assertFalse(self.response.artifacts)


class BundleChromeOSConfigTest(BundleTestCase):
    """Unittests for BundleChromeOSConfig"""

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleChromeOSConfig")
        artifacts.BundleChromeOSConfig(
            self.sysroot_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleChromeOSConfig")
        artifacts.BundleChromeOSConfig(
            self.sysroot_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "config.yaml"),
        )

    def testBundleChromeOSConfigSuccess(self) -> None:
        """Test standard success case."""
        bundle_chromeos_config = self.PatchObject(
            artifacts_svc, "BundleChromeOSConfig", return_value="config.yaml"
        )
        artifacts.BundleChromeOSConfig(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertEqual(
            [
                artifact.artifact_path.path
                for artifact in self.response.artifacts
            ],
            [os.path.join(self.output_dir, "config.yaml")],
        )

        self.assertEqual(
            bundle_chromeos_config.call_args_list,
            [mock.call(mock.ANY, self.sysroot, self.output_dir)],
        )

    def testBundleChromeOSConfigNoConfigFound(self) -> None:
        """Empty results when the config payload isn't found."""
        self.PatchObject(
            artifacts_svc, "BundleChromeOSConfig", return_value=None
        )

        artifacts.BundleChromeOSConfig(
            self.sysroot_request, self.response, self.api_config
        )
        self.assertFalse(self.response.artifacts)


class BundleTestUpdatePayloadsTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Unittests for BundleTestUpdatePayloads."""

    def setUp(self) -> None:
        self.source_root = os.path.join(self.tempdir, "cros")
        osutils.SafeMakedirs(self.source_root)

        self.archive_root = os.path.join(self.tempdir, "output")
        osutils.SafeMakedirs(self.archive_root)

        self.target = "target"
        self.image_root = os.path.join(
            self.source_root, "src/build/images/target/latest"
        )

        self.request = artifacts_pb2.BundleRequest()
        self.request.build_target.name = self.target
        self.request.output_dir = self.archive_root
        self.request.result_path.path.path = self.archive_root
        self.request.result_path.path.location = (
            common_pb2.Path.Location.OUTSIDE
        )

        self.response = artifacts_pb2.BundleResponse()

        self.PatchObject(constants, "SOURCE_ROOT", new=self.source_root)

        def MockPayloads(_, image_path, archive_dir):
            osutils.WriteFile(
                os.path.join(archive_dir, "payload1.bin"), image_path
            )
            osutils.WriteFile(
                os.path.join(archive_dir, "payload2.bin"), image_path
            )
            return [
                os.path.join(archive_dir, "payload1.bin"),
                os.path.join(archive_dir, "payload2.bin"),
            ]

        self.bundle_patch = self.PatchObject(
            artifacts_svc, "BundleTestUpdatePayloads", side_effect=MockPayloads
        )

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleTestUpdatePayloads")
        artifacts.BundleTestUpdatePayloads(
            self.request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleTestUpdatePayloads")
        artifacts.BundleTestUpdatePayloads(
            self.request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 3)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.archive_root, "payload1.bin"),
        )
        self.assertEqual(
            self.response.artifacts[1].artifact_path.path,
            os.path.join(self.archive_root, "payload1.json"),
        )
        self.assertEqual(
            self.response.artifacts[2].artifact_path.path,
            os.path.join(self.archive_root, "payload1.log"),
        )

    def testBundleTestUpdatePayloads(self) -> None:
        """BundleTestUpdatePayloads calls cbuildbot/commands correctly."""
        image_path = os.path.join(self.image_root, constants.BASE_IMAGE_BIN)
        osutils.WriteFile(image_path, "image!", makedirs=True)

        artifacts.BundleTestUpdatePayloads(
            self.request, self.response, self.api_config
        )

        actual = [
            os.path.basename(artifact.artifact_path.path)
            for artifact in self.response.artifacts
        ]
        expected = ["payload1.bin", "payload2.bin"]
        self.assertCountEqual(actual, expected)

        actual = [
            os.path.basename(path)
            for path in osutils.DirectoryIterator(
                os.path.dirname(self.response.artifacts[0].artifact_path.path)
            )
        ]
        self.assertCountEqual(actual, expected)

    def testBundleTestUpdatePayloadsNoImageDir(self) -> None:
        """BundleTestUpdatePayloads dies if no image dir is found."""
        # Intentionally do not write image directory.
        artifacts.BundleTestUpdatePayloads(
            self.request, self.response, self.api_config
        )
        self.assertFalse(self.response.artifacts)

    def testBundleTestUpdatePayloadsNoImage(self) -> None:
        """BundleTestUpdatePayloads dies if no usable image found for target."""
        # Intentionally do not write image, but create the directory.
        osutils.SafeMakedirs(self.image_root)
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleTestUpdatePayloads(
                self.request, self.response, self.api_config
            )


class BundleSimpleChromeArtifactsTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """BundleSimpleChromeArtifacts tests."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        self.sysroot_path = "/sysroot"
        self.sysroot_dir = self.chroot.full_path(self.sysroot_path)
        osutils.SafeMakedirs(self.sysroot_dir)
        self.output_dir = os.path.join(self.tempdir, "output_dir")
        osutils.SafeMakedirs(self.output_dir)

        self.does_not_exist = os.path.join(self.tempdir, "does_not_exist")

        self.response = artifacts_pb2.BundleResponse()

    def _GetRequest(
        self,
        chroot: Optional[chroot_lib.Chroot] = None,
        sysroot: Optional[str] = None,
        build_target: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> artifacts_pb2.BundleRequest:
        """Helper to create a request message instance.

        Args:
            chroot: The chroot path.
            sysroot: The sysroot path.
            build_target: The build target name.
            output_dir: The output directory.
        """
        return artifacts_pb2.BundleRequest(
            sysroot={"path": sysroot, "build_target": {"name": build_target}},
            chroot={
                "path": chroot.path if chroot else None,
                "out_path": str(chroot.out_path) if chroot else None,
            },
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(
                    path=output_dir,
                    location=common_pb2.Path.OUTSIDE,
                )
            ),
        )

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleSimpleChromeArtifacts")
        request = self._GetRequest(
            chroot=self.chroot,
            sysroot=self.sysroot_path,
            build_target="board",
            output_dir=self.output_dir,
        )
        artifacts.BundleSimpleChromeArtifacts(
            request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleSimpleChromeArtifacts")
        request = self._GetRequest(
            chroot=self.chroot,
            sysroot=self.sysroot_path,
            build_target="board",
            output_dir=self.output_dir,
        )
        artifacts.BundleSimpleChromeArtifacts(
            request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, "simple_chrome.txt"),
        )

    def testNoBuildTarget(self) -> None:
        """Test no build target fails."""
        request = self._GetRequest(
            chroot=self.chroot,
            sysroot=self.sysroot_path,
            output_dir=self.output_dir,
        )
        response = self.response
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleSimpleChromeArtifacts(
                request, response, self.api_config
            )

    def testNoSysroot(self) -> None:
        """Test no sysroot fails."""
        request = self._GetRequest(
            build_target="board", output_dir=self.output_dir
        )
        response = self.response
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleSimpleChromeArtifacts(
                request, response, self.api_config
            )

    def testSysrootDoesNotExist(self) -> None:
        """Test no sysroot fails."""
        request = self._GetRequest(
            build_target="board",
            output_dir=self.output_dir,
            sysroot=self.does_not_exist,
        )
        response = self.response
        artifacts.BundleSimpleChromeArtifacts(
            request, response, self.api_config
        )
        self.assertFalse(self.response.artifacts)

    def testNoOutputDir(self) -> None:
        """Test no output dir fails."""
        request = self._GetRequest(
            chroot=self.chroot,
            sysroot=self.sysroot_path,
            build_target="board",
        )
        response = self.response
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleSimpleChromeArtifacts(
                request, response, self.api_config
            )

    def testOutputDirDoesNotExist(self) -> None:
        """Test no output dir fails."""
        request = self._GetRequest(
            chroot=self.chroot,
            sysroot=self.sysroot_path,
            build_target="board",
            output_dir=self.does_not_exist,
        )
        response = self.response
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleSimpleChromeArtifacts(
                request, response, self.api_config
            )

    def testOutputHandling(self) -> None:
        """Test response output."""
        files = ["file1", "file2", "file3"]
        expected_files = [os.path.join(self.output_dir, f) for f in files]
        self.PatchObject(
            artifacts_svc,
            "BundleSimpleChromeArtifacts",
            return_value=expected_files,
        )
        request = self._GetRequest(
            chroot=self.chroot,
            sysroot=self.sysroot_path,
            build_target="board",
            output_dir=self.output_dir,
        )
        response = self.response

        artifacts.BundleSimpleChromeArtifacts(
            request, response, self.api_config
        )

        self.assertTrue(response.artifacts)
        self.assertCountEqual(
            expected_files, [a.artifact_path.path for a in response.artifacts]
        )


class BundleVmFilesTest(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """BuildVmFiles tests."""

    def setUp(self) -> None:
        self.output_dir = os.path.join(self.tempdir, "output")
        osutils.SafeMakedirs(self.output_dir)

        self.response = artifacts_pb2.BundleResponse()

    def _GetInput(
        self,
        chroot: Optional[str] = None,
        sysroot: Optional[str] = None,
        test_results_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
    ) -> artifacts_pb2.BundleVmFilesRequest:
        """Helper to build out an input message instance.

        Args:
            chroot: The chroot path.
            sysroot: The sysroot path relative to the chroot.
            test_results_dir: The test results directory relative to the
                sysroot.
            output_dir: The directory where the results tarball should be saved.
        """
        return artifacts_pb2.BundleVmFilesRequest(
            chroot={"path": chroot},
            sysroot={"path": sysroot},
            test_results_dir=test_results_dir,
            output_dir=output_dir,
        )

    def testValidateOnly(self) -> None:
        """Quick check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleVmFiles")
        in_proto = self._GetInput(
            chroot="/chroot/dir",
            sysroot="/build/board",
            test_results_dir="/test/results",
            output_dir=self.output_dir,
        )
        artifacts.BundleVmFiles(
            in_proto, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleVmFiles")
        in_proto = self._GetInput(
            chroot="/chroot/dir",
            sysroot="/build/board",
            test_results_dir="/test/results",
            output_dir=self.output_dir,
        )
        artifacts.BundleVmFiles(in_proto, self.response, self.mock_call_config)
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].path,
            os.path.join(self.output_dir, "f1.tar"),
        )

    def testChrootMissing(self) -> None:
        """Test error handling for missing chroot."""
        in_proto = self._GetInput(
            sysroot="/build/board",
            test_results_dir="/test/results",
            output_dir=self.output_dir,
        )

        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleVmFiles(in_proto, self.response, self.api_config)

    def testTestResultsDirMissing(self) -> None:
        """Test error handling for missing test results directory."""
        in_proto = self._GetInput(
            chroot="/chroot/dir",
            sysroot="/build/board",
            output_dir=self.output_dir,
        )

        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleVmFiles(in_proto, self.response, self.api_config)

    def testOutputDirMissing(self) -> None:
        """Test error handling for missing output directory."""
        in_proto = self._GetInput(
            chroot="/chroot/dir",
            sysroot="/build/board",
            test_results_dir="/test/results",
        )

        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleVmFiles(in_proto, self.response, self.api_config)

    def testOutputDirDoesNotExist(self) -> None:
        """Test error handling for output directory that does not exist."""
        in_proto = self._GetInput(
            chroot="/chroot/dir",
            sysroot="/build/board",
            output_dir=os.path.join(self.tempdir, "dne"),
            test_results_dir="/test/results",
        )

        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleVmFiles(in_proto, self.response, self.api_config)

    def testValidCall(self) -> None:
        """Test image dir building."""
        in_proto = self._GetInput(
            chroot="/chroot/dir",
            sysroot="/build/board",
            test_results_dir="/test/results",
            output_dir=self.output_dir,
        )

        expected_files = ["/tmp/output/f1.tar", "/tmp/output/f2.tar"]
        patch = self.PatchObject(
            artifacts_svc, "BundleVmFiles", return_value=expected_files
        )

        artifacts.BundleVmFiles(in_proto, self.response, self.api_config)

        patch.assert_called_with(mock.ANY, "/test/results", self.output_dir)

        # Make sure we have artifacts, and that every artifact is an expected
        # file.
        self.assertTrue(self.response.artifacts)
        for artifact in self.response.artifacts:
            self.assertIn(artifact.path, expected_files)
            expected_files.remove(artifact.path)

        # Make sure we've seen all of the expected files.
        self.assertFalse(expected_files)


class BundleGceTarballTest(BundleTestCase):
    """Unittests for BundleGceTarball."""

    def testValidateOnly(self) -> None:
        """Check that a validate only call does not execute any logic."""
        patch = self.PatchObject(artifacts_svc, "BundleGceTarball")
        artifacts.BundleGceTarball(
            self.target_request, self.response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(artifacts_svc, "BundleGceTarball")
        artifacts.BundleGceTarball(
            self.target_request, self.response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(len(self.response.artifacts), 1)
        self.assertEqual(
            self.response.artifacts[0].artifact_path.path,
            os.path.join(self.output_dir, constants.TEST_IMAGE_GCE_TAR),
        )

    def testBundleGceTarball(self) -> None:
        """BundleGceTarball calls cbuildbot/commands with correct args."""
        bundle_gce_tarball = self.PatchObject(
            artifacts_svc,
            "BundleGceTarball",
            return_value=os.path.join(
                self.output_dir, constants.TEST_IMAGE_GCE_TAR
            ),
        )
        self.PatchObject(os.path, "exists", return_value=True)
        artifacts.BundleGceTarball(
            self.target_request, self.response, self.api_config
        )
        self.assertEqual(
            [
                artifact.artifact_path.path
                for artifact in self.response.artifacts
            ],
            [os.path.join(self.output_dir, constants.TEST_IMAGE_GCE_TAR)],
        )

        latest = os.path.join(
            self.source_root, "src/build/images/target/latest"
        )
        self.assertEqual(
            bundle_gce_tarball.call_args_list,
            [mock.call(self.output_dir, latest)],
        )

    def testBundleGceTarballNoImageDir(self) -> None:
        """BundleGceTarball dies when image dir does not exist."""
        self.PatchObject(os.path, "exists", return_value=False)
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.BundleGceTarball(
                self.target_request, self.response, self.api_config
            )


class FetchCentralizedSuitesTestCase(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Unittests for FetchCentralizedSuites."""

    sysroot_path = "/build/coral"
    chroot_name = "chroot"

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        pathlib.Path(self.chroot.path).touch()
        self.chroot.out_path.touch()
        self.expected_suite_set_file = self.chroot.full_path(
            "/build/coral/usr/share/centralized-suites/suite_sets.pb"
        )
        self.expected_suite_file = self.chroot.full_path(
            "/build/coral/usr/share/centralized-suites/suites.pb"
        )
        self.expected_mock_suite_set = "/centralized-suites/suite_sets.pb"
        self.expected_mock_suite = "/centralized-suites/suites.pb"
        self.PatchObject(cros_build_lib, "AssertOutsideChroot")

    def createFetchCentralizedSuitesRequest(
        self, use_sysroot_path=True, use_chroot=True
    ):
        """Construct a FetchCentralizedSuitesRequest for use in test cases."""
        request = artifacts_pb2.FetchCentralizedSuitesRequest()
        if use_sysroot_path:
            request.sysroot.path = self.sysroot_path
        if use_chroot:
            request.chroot.path = self.chroot.path
            request.chroot.out_path = str(self.chroot.out_path)
        return request

    def testValidateOnly(self) -> None:
        """Check that a validate only call does not execute any logic."""
        patch = self.PatchObject(controller_util, "ParseSysroot")
        request = self.createFetchCentralizedSuitesRequest()
        response = artifacts_pb2.FetchCentralizedSuitesResponse()
        artifacts.FetchCentralizedSuites(
            request, response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(controller_util, "ParseSysroot")
        request = self.createFetchCentralizedSuitesRequest()
        response = artifacts_pb2.FetchCentralizedSuitesResponse()
        artifacts.FetchCentralizedSuites(
            request, response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertEqual(
            response.suite_set_file.path.path, self.expected_mock_suite_set
        )
        self.assertEqual(
            response.suite_file.path.path, self.expected_mock_suite
        )

    def testNoSysrootPath(self) -> None:
        """Check that a request with no sysroot.path results in failure."""
        request = self.createFetchCentralizedSuitesRequest(
            use_sysroot_path=False
        )
        response = artifacts_pb2.FetchCentralizedSuitesResponse()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.FetchCentralizedSuites(request, response, self.api_config)

    def testNoChroot(self) -> None:
        """Check that a request with no chroot results in failure."""
        request = self.createFetchCentralizedSuitesRequest(use_chroot=False)
        response = artifacts_pb2.FetchCentralizedSuitesResponse()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.FetchCentralizedSuites(request, response, self.api_config)

    def testSuccess(self) -> None:
        """Check that a well-formed request yields the expected results."""
        request = self.createFetchCentralizedSuitesRequest(use_chroot=True)
        response = artifacts_pb2.FetchCentralizedSuitesResponse()
        artifacts.FetchCentralizedSuites(request, response, self.api_config)
        self.assertEqual(
            response.suite_set_file.path.path, self.expected_suite_set_file
        )
        self.assertEqual(
            response.suite_file.path.path, self.expected_suite_file
        )
        self.assertEqual(
            response.suite_set_file.path.location, common_pb2.Path.OUTSIDE
        )
        self.assertEqual(
            response.suite_file.path.location, common_pb2.Path.OUTSIDE
        )


class FetchMetadataTestCase(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Unittests for FetchMetadata."""

    sysroot_path = "/build/fake"
    chroot_name = "chroot"

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        self.chroot = chroot_lib.Chroot(
            path=os.path.join(self.tempdir, "fake_chroot")
        )
        osutils.SafeMakedirs(self.chroot.path)
        self.expected_filepaths = [
            self.chroot.full_path(fp)
            for fp in (
                "/build/fake/usr/local/build/autotest/autotest_metadata.pb",
                "/build/fake/usr/share/tast/metadata/local/cros.pb",
                "/build/fake/build/share/tast/metadata/local/crosint.pb",
                "/build/fake/build/share/tast/metadata/local/crosint_intel.pb",
                "/build/fake/usr/share/tast/metadata/remote/cros.pb",
                "/build/fake/usr/share/tast/metadata/remote/crosint.pb",
                "/build/fake/usr/share/tast/metadata/remote/crosint_intel.pb",
                "/build/fake/usr/local/build/gtest/gtest_metadata.pb",
            )
        ]
        self.PatchObject(cros_build_lib, "AssertOutsideChroot")

    def createFetchMetadataRequest(
        self, use_sysroot_path=True, use_chroot=True
    ):
        """Construct a FetchMetadataRequest for use in test cases."""
        request = artifacts_pb2.FetchMetadataRequest()
        if use_sysroot_path:
            request.sysroot.path = self.sysroot_path
        if use_chroot:
            request.chroot.path = self.chroot.path
        return request

    def testValidateOnly(self) -> None:
        """Check that a validate only call does not execute any logic."""
        patch = self.PatchObject(controller_util, "ParseSysroot")
        request = self.createFetchMetadataRequest()
        response = artifacts_pb2.FetchMetadataResponse()
        artifacts.FetchMetadata(request, response, self.validate_only_config)
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(controller_util, "ParseSysroot")
        request = self.createFetchMetadataRequest()
        response = artifacts_pb2.FetchMetadataResponse()
        artifacts.FetchMetadata(request, response, self.mock_call_config)
        patch.assert_not_called()
        self.assertGreater(len(response.filepaths), 0)

    def testNoSysrootPath(self) -> None:
        """Check that a request with no sysroot.path results in failure."""
        request = self.createFetchMetadataRequest(use_sysroot_path=False)
        response = artifacts_pb2.FetchMetadataResponse()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.FetchMetadata(request, response, self.api_config)

    def testNoChroot(self) -> None:
        """Check that a request with no chroot results in failure."""
        request = self.createFetchMetadataRequest(use_chroot=False)
        response = artifacts_pb2.FetchMetadataResponse()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.FetchMetadata(request, response, self.api_config)

    def testSuccess(self) -> None:
        """Check that a well-formed request yields the expected results."""
        request = self.createFetchMetadataRequest(use_chroot=True)
        response = artifacts_pb2.FetchMetadataResponse()
        artifacts.FetchMetadata(request, response, self.api_config)
        actual_filepaths = [fp.path.path for fp in response.filepaths]
        self.assertEqual(
            sorted(actual_filepaths), sorted(self.expected_filepaths)
        )
        self.assertTrue(
            all(
                fp.path.location == common_pb2.Path.OUTSIDE
                for fp in response.filepaths
            )
        )


class FetchTestHarnessMetadataTestCase(
    cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin
):
    """Unittests for FetchTestHarnessMetadata."""

    sysroot_path = "/build/fake_board"
    chroot_name = "chroot"

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        self.chroot = chroot_lib.Chroot(
            path=os.path.join(self.tempdir, "fake_chroot")
        )
        osutils.SafeMakedirs(self.chroot.path)

        tast_usr = "/build/fake_board/usr/share/tast/metadata/"
        tast_build = "/build/fake_board/build/share/tast/metadata/"
        self.expected_filepaths = [
            self.chroot.full_path(fp)
            for fp in (
                os.path.join(tast_usr, "local/cros_local_harness.pb"),
                os.path.join(tast_build, "local/crosint_local_harness.pb"),
                os.path.join(
                    tast_build, "local/crosint_intel_local_harness.pb"
                ),
                os.path.join(tast_usr, "remote/cros_remote_harness.pb"),
                os.path.join(tast_usr, "remote/crosint_remote_harness.pb"),
                os.path.join(
                    tast_usr, "remote/crosint_intel_remote_harness.pb"
                ),
            )
        ]
        self.PatchObject(cros_build_lib, "AssertOutsideChroot")

    def createFetchTestHarnessMetadataRequest(
        self, use_sysroot_path=True, use_chroot=True
    ):
        """Construct a FetchTestHarnessMetadataRequest for use in test cases."""
        request = artifacts_pb2.FetchTestHarnessMetadataRequest()
        if use_sysroot_path:
            request.sysroot.path = self.sysroot_path
        if use_chroot:
            request.chroot.path = self.chroot.path
        return request

    def testValidateOnly(self) -> None:
        """Check that a validate only call does not execute any logic."""
        patch = self.PatchObject(controller_util, "ParseSysroot")
        request = self.createFetchTestHarnessMetadataRequest()
        response = artifacts_pb2.FetchTestHarnessMetadataResponse()
        artifacts.FetchTestHarnessMetadata(
            request, response, self.validate_only_config
        )
        patch.assert_not_called()

    def testMockCall(self) -> None:
        """Test a mock call does not execute logic, returns mocked value."""
        patch = self.PatchObject(controller_util, "ParseSysroot")
        request = self.createFetchTestHarnessMetadataRequest()
        response = artifacts_pb2.FetchTestHarnessMetadataResponse()
        artifacts.FetchTestHarnessMetadata(
            request, response, self.mock_call_config
        )
        patch.assert_not_called()
        self.assertGreater(len(response.filepaths), 0)

    def testNoSysrootPath(self) -> None:
        """Check that a request with no sysroot.path results in failure."""
        request = self.createFetchTestHarnessMetadataRequest(
            use_sysroot_path=False
        )
        response = artifacts_pb2.FetchTestHarnessMetadataResponse()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.FetchTestHarnessMetadata(
                request, response, self.api_config
            )

    def testNoChroot(self) -> None:
        """Check that a request with no chroot results in failure."""
        request = self.createFetchTestHarnessMetadataRequest(use_chroot=False)
        response = artifacts_pb2.FetchTestHarnessMetadataResponse()
        with self.assertRaises(cros_build_lib.DieSystemExit):
            artifacts.FetchTestHarnessMetadata(
                request, response, self.api_config
            )

    def testSuccess(self) -> None:
        """Check that a well-formed request yields the expected results."""
        request = self.createFetchTestHarnessMetadataRequest(use_chroot=True)
        response = artifacts_pb2.FetchTestHarnessMetadataResponse()
        artifacts.FetchTestHarnessMetadata(request, response, self.api_config)
        actual_filepaths = [fp.path.path for fp in response.filepaths]
        self.assertEqual(
            sorted(actual_filepaths), sorted(self.expected_filepaths)
        )
        self.assertTrue(
            all(
                fp.path.location == common_pb2.Path.OUTSIDE
                for fp in response.filepaths
            )
        )


class GetTest(cros_test_lib.MockTempDirTestCase, api_config.ApiConfigMixin):
    """Get function tests."""

    def setUp(self) -> None:
        self.sysroot_path = "/build/target"
        self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)

    def _InputProto(self):
        """Helper to build an input proto instance."""
        # pylint: disable=line-too-long
        return artifacts_pb2.GetRequest(
            sysroot=sysroot_pb2.Sysroot(path=self.sysroot_path),
            artifact_info=common_pb2.ArtifactsByService(
                sysroot=common_pb2.ArtifactsByService.Sysroot(
                    output_artifacts=[
                        common_pb2.ArtifactsByService.Sysroot.ArtifactInfo(
                            artifact_types=[
                                common_pb2.ArtifactsByService.Sysroot.ArtifactType.FUZZER_SYSROOT
                            ]
                        )
                    ],
                ),
                image=common_pb2.ArtifactsByService.Image(
                    output_artifacts=[
                        common_pb2.ArtifactsByService.Image.ArtifactInfo(
                            artifact_types=[
                                common_pb2.ArtifactsByService.Image.ArtifactType.LICENSE_CREDITS
                            ]
                        )
                    ],
                ),
                test=common_pb2.ArtifactsByService.Test(
                    output_artifacts=[
                        common_pb2.ArtifactsByService.Test.ArtifactInfo(
                            artifact_types=[
                                common_pb2.ArtifactsByService.Test.ArtifactType.HWQUAL
                            ]
                        )
                    ],
                ),
            ),
            result_path=common_pb2.ResultPath(
                path=common_pb2.Path(path=str(self.tempdir))
            ),
        )
        # pylint: enable=line-too-long

    def _OutputProto(self):
        """Helper to build an output proto instance."""
        return artifacts_pb2.GetResponse()

    def testSuccess(self) -> None:
        """Test Get."""
        # pylint: disable=line-too-long
        image_mock = self.PatchObject(
            image_controller,
            "GetArtifacts",
            return_value=[
                {
                    "paths": ["/foo/bar/license_credits.html"],
                    "type": common_pb2.ArtifactsByService.Image.ArtifactType.LICENSE_CREDITS,
                }
            ],
        )
        sysroot_mock = self.PatchObject(
            sysroot_controller,
            "GetArtifacts",
            return_value=[
                {
                    "type": common_pb2.ArtifactsByService.Sysroot.ArtifactType.FUZZER_SYSROOT,
                    "failed": True,
                    "failure_reason": "Bad data!",
                }
            ],
        )
        test_mock = self.PatchObject(
            test_controller,
            "GetArtifacts",
            return_value=[
                {
                    "paths": ["/foo/bar/hwqual.tar.xz"],
                    "type": common_pb2.ArtifactsByService.Test.ArtifactType.HWQUAL,
                }
            ],
        )
        # pylint: enable=line-too-long

        in_proto = self._InputProto()
        out_proto = self._OutputProto()
        artifacts.Get(
            in_proto,
            out_proto,
            self.api_config,
        )

        image_mock.assert_called_once()
        sysroot_mock.assert_called_once()
        test_mock.assert_called_once()

        # pylint: disable=line-too-long
        expected = common_pb2.UploadedArtifactsByService(
            sysroot=common_pb2.UploadedArtifactsByService.Sysroot(
                artifacts=[
                    common_pb2.UploadedArtifactsByService.Sysroot.ArtifactPaths(
                        artifact_type=common_pb2.ArtifactsByService.Sysroot.ArtifactType.FUZZER_SYSROOT,
                        failed=True,
                        failure_reason="Bad data!",
                    )
                ]
            ),
            image=common_pb2.UploadedArtifactsByService.Image(
                artifacts=[
                    common_pb2.UploadedArtifactsByService.Image.ArtifactPaths(
                        artifact_type=common_pb2.ArtifactsByService.Image.ArtifactType.LICENSE_CREDITS,
                        paths=[
                            common_pb2.Path(
                                path="/foo/bar/license_credits.html",
                                location=common_pb2.Path.OUTSIDE,
                            )
                        ],
                    )
                ]
            ),
            test=common_pb2.UploadedArtifactsByService.Test(
                artifacts=[
                    common_pb2.UploadedArtifactsByService.Test.ArtifactPaths(
                        artifact_type=common_pb2.ArtifactsByService.Test.ArtifactType.HWQUAL,
                        paths=[
                            common_pb2.Path(
                                path="/foo/bar/hwqual.tar.xz",
                                location=common_pb2.Path.OUTSIDE,
                            )
                        ],
                    )
                ]
            ),
        )
        # pylint: enable=line-too-long
        self.assertEqual(out_proto.artifacts, expected)
