# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for vm_test_stages."""

import os
import re

from chromite.cbuildbot import cbuildbot_unittest
from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import generic_stages_unittest
from chromite.cbuildbot.stages import vm_test_stages
from chromite.lib import cgroups
from chromite.lib import config_lib
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import failures_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import results_lib
from chromite.lib.buildstore import FakeBuildStore


# pylint: disable=too-many-ancestors


class VMTestStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cbuildbot_unittest.SimpleBuilderTestCase,
):
    """Tests for the VMTest stage."""

    BOT_ID = "betty-full"
    RELEASE_TAG = ""

    def setUp(self):
        self.PatchObject(commands, "CreateTestRoot", return_value=self.tempdir)
        for cmd in (
            "GenerateStackTraces",
            "ArchiveFile",
            "UploadArchivedFile",
            "BuildAndArchiveTestResultsTarball",
        ):
            self.PatchObject(commands, cmd, autospec=True)
        self.run_test_suite_mock = self.PatchObject(
            vm_test_stages, "RunTestSuite", autospec=True
        )
        for cmd in (
            "ArchiveTestResults",
            "ArchiveVMFiles",
            "RunDevModeTest",
            "RunCrosVMTest",
            "ListTests",
            "GetTestResultsDir",
        ):
            self.PatchObject(vm_test_stages, cmd, autospec=True)
        self.PatchObject(
            vm_test_stages.VMTestStage,
            "_NoTestResults",
            autospec=True,
            return_value=False,
        )
        self.PatchObject(osutils, "RmDir", autospec=True)
        self.PatchObject(cgroups, "SimpleContainChildren", autospec=True)
        self._Prepare()
        self.buildstore = FakeBuildStore()

        # Simulate breakpad symbols being ready.
        board_runattrs = self._run.GetBoardRunAttrs(self._current_board)
        board_runattrs.SetParallel("breakpad_symbols_generated", True)
        board_runattrs.SetParallel("autotest_tarball_generated", True)

    def ConstructStage(self):
        # pylint: disable=protected-access
        self._run.GetArchive().SetupArchivePath()
        stage = vm_test_stages.VMTestStage(
            self._run, self.buildstore, self._current_board
        )
        image_dir = stage.GetImageDirSymlink()
        osutils.Touch(
            os.path.join(image_dir, constants.TEST_KEY_PRIVATE), makedirs=True
        )
        return stage

    def testQuickTests(self):
        """Tests quick unit and cros_au_test_harness tests are correct."""
        self._run.config["vm_tests"] = [
            config_lib.VMTestConfig(constants.SIMPLE_AU_TEST_TYPE)
        ]
        self.RunStage()

    def testFailedTest(self):
        """Tests quick unit and cros_au_test_harness tests are correct."""
        self.PatchObject(
            vm_test_stages.VMTestStage,
            "_RunTest",
            autospec=True,
            side_effect=Exception(),
        )
        self.assertRaises(failures_lib.StepFailure, self.RunStage)

    def testRaisesInfraFail(self):
        """Tests that a infra failures has been raised."""
        commands.BuildAndArchiveTestResultsTarball.side_effect = OSError(
            "Cannot archive"
        )
        stage = self.ConstructStage()
        self.assertRaises(
            failures_lib.InfrastructureFailure, stage.PerformStage
        )

    def testSkipVMTest(self):
        """Tests trybot with no vm test."""
        extra_cmd_args = ["--novmtests"]
        self._Prepare(extra_cmd_args=extra_cmd_args)
        # _Prepare resets the board_runattrs.
        board_runattrs = self._run.GetBoardRunAttrs(self._current_board)
        board_runattrs.SetParallel("autotest_tarball_generated", True)
        self.RunStage()

    def testReportTestResults(self):
        """Test trybot with reporting function."""
        self._run.config["vm_tests"] = [
            config_lib.VMTestConfig(constants.SIMPLE_AU_TEST_TYPE)
        ]
        self._run.config["vm_test_report_to_dashboards"] = True
        self.RunStage()

    def testForgivingVMTest(self):
        """Test if a test is warn-only, it actually warns."""
        self._run.config["vm_tests"] = [
            config_lib.VMTestConfig(
                constants.VM_SUITE_TEST_TYPE,
                warn_only=True,
                test_suite="bvt-perbuild",
            ),
            config_lib.VMTestConfig(
                constants.VM_SUITE_TEST_TYPE,
                warn_only=False,
                test_suite="bvt-arc",
            ),
        ]

        # pylint: disable=unused-argument
        def _MockRunTestSuite(
            buildroot,
            board,
            image_path,
            results_dir,
            test_config,
            *args,
            **kwargs,
        ):
            # Only raise exception in one test.
            if test_config.test_suite == "bvt-perbuild":
                raise Exception()

        # pylint: enable=unused-argument

        self.run_test_suite_mock.side_effect = _MockRunTestSuite
        results_lib.Results.Clear()
        self.RunStage()
        result = results_lib.Results.Get()[0]
        self.assertEqual(result.result, results_lib.Results.FORGIVEN)
        # Make sure that all tests were actually run.
        self.assertEqual(
            vm_test_stages.RunTestSuite.call_count,
            len(self._run.config["vm_tests"]),
        )


class RunTestSuiteTest(cros_test_lib.RunCommandTempDirTestCase):
    """Test RunTestSuite functionality."""

    TEST_BOARD = "betty"
    BUILD_ROOT = "/fake/root"
    RESULTS_DIR = "/tmp/taco"
    TEST_IMAGE_OUTSIDE_CHROOT = os.path.join(BUILD_ROOT, "test.img")
    TEST_IMAGE_INSIDE_CHROOT = os.path.join(
        constants.CHROOT_SOURCE_ROOT, constants.TEST_IMAGE_BIN
    )
    PRIVATE_KEY_OUTSIDE_CHROOT = os.path.join(BUILD_ROOT, "rsa")
    PRIVATE_KEY_INSIDE_CHROOT = os.path.join(
        constants.CHROOT_SOURCE_ROOT, "rsa"
    )
    SSH_PORT = 9226

    def setUp(self):
        self.PatchObject(
            path_util,
            "FromChrootPath",
            new=lambda path: re.sub(
                r"^%s" % constants.CHROOT_SOURCE_ROOT, self.BUILD_ROOT, path
            ),
        )
        self.PatchObject(
            path_util,
            "ToChrootPath",
            new=lambda path: re.sub(
                r"^%s" % self.BUILD_ROOT, constants.CHROOT_SOURCE_ROOT, path
            ),
        )

    def _RunTestSuite(self, test_config, allow_chrome_crashes=False):
        vm_test_stages.RunTestSuite(
            self.BUILD_ROOT,
            self.TEST_BOARD,
            self.TEST_IMAGE_OUTSIDE_CHROOT,
            self.RESULTS_DIR,
            allow_chrome_crashes=allow_chrome_crashes,
            test_config=test_config,
            ssh_private_key=self.PRIVATE_KEY_OUTSIDE_CHROOT,
            ssh_port=self.SSH_PORT,
        )
        self.assertCommandContains(["--board=%s" % self.TEST_BOARD])
        if test_config.use_ctest:
            self.assertCommandContains(
                [
                    os.path.join(
                        self.BUILD_ROOT,
                        "src",
                        "platform",
                        "crostestutils",
                        "au_test_harness",
                        "cros_au_test_harness.py",
                    ),
                    "--no_graphics",
                    "--verbose",
                    "--target_image=%s" % self.TEST_IMAGE_OUTSIDE_CHROOT,
                    "--test_prefix=SimpleTestVerify",
                    "--ssh_private_key=%s" % self.PRIVATE_KEY_OUTSIDE_CHROOT,
                ]
            )
            self.assertCommandContains(enter_chroot=True, expected=False)
        else:
            self.assertCommandContains(
                [
                    "cros_run_test",
                    "--debug",
                    "--image-path=%s" % self.TEST_IMAGE_INSIDE_CHROOT,
                    "--results-dir=%s" % self.RESULTS_DIR,
                    "--private-key=%s" % self.PRIVATE_KEY_INSIDE_CHROOT,
                ]
            )
            self.assertCommandContains(enter_chroot=True)
            self.assertCommandContains(check=False)

    def testSimple(self):
        """Test SIMPLE config."""
        config = config_lib.VMTestConfig(constants.SIMPLE_AU_TEST_TYPE)
        self._RunTestSuite(config)
        self.assertCommandContains(["--test_prefix=SimpleTestVerify"])

    def testSmoke(self):
        """Test SMOKE config."""
        config = config_lib.VMTestConfig(
            constants.VM_SUITE_TEST_TYPE, test_suite="smoke"
        )
        self._RunTestSuite(config)
        self.assertCommandContains(["--verify_suite_name=smoke"])

    def testGceSmokeTestType(self):
        """Test GCE test with gce-smoke suite."""
        config = config_lib.GCETestConfig(
            constants.GCE_SUITE_TEST_TYPE, test_suite="gce-smoke"
        )
        self._RunTestSuite(config)
        self.assertCommandContains(["--test_prefix=SimpleTestVerify"])
        self.assertCommandContains(["--type=gce"])
        self.assertCommandContains(["--verify_suite_name=gce-smoke"])

    def testGceSanityTestType(self):
        """Test GCE test with gce-sanity suite."""
        config = config_lib.GCETestConfig(
            constants.GCE_SUITE_TEST_TYPE, test_suite="gce-sanity"
        )
        self._RunTestSuite(config)
        self.assertCommandContains(["--test_prefix=SimpleTestVerify"])
        self.assertCommandContains(["--type=gce"])
        self.assertCommandContains(["--verify_suite_name=gce-sanity"])

    def testSmokeChromite(self):
        """Test SMOKE config using chromite VM code path."""
        config = config_lib.VMTestConfig(
            constants.VM_SUITE_TEST_TYPE, test_suite="smoke", use_ctest=False
        )
        self._RunTestSuite(config)
        self.assertCommandContains(["--autotest=suite:smoke"])
        self.assertCommandContains(
            ["---test_that-args=-allow_chrome_crashes"], expected=False
        )

    def testWhitelistChromeCrashes(self):
        """Test SMOKE config with allowing chrome crashes."""
        config = config_lib.VMTestConfig(
            constants.VM_SUITE_TEST_TYPE, test_suite="smoke", use_ctest=False
        )
        self._RunTestSuite(config, allow_chrome_crashes=True)
        self.assertCommandContains(["--autotest=suite:smoke"])
        self.assertCommandContains(["--test_that-args=--allow-chrome-crashes"])


class UnmockedTests(cros_test_lib.TempDirTestCase):
    """Test cases which really run tests, instead of using mocks."""

    def testListFaliedTests(self):
        """Tests if we can list failed tests."""
        test_report_1 = """
/tmp/taco/taste_tests/all/results-01-has_salsa              [  PASSED  ]
/tmp/taco/taste_tests/all/results-01-has_salsa/has_salsa    [  PASSED  ]
/tmp/taco/taste_tests/all/results-02-has_cheese             [  FAILED  ]
/tmp/taco/taste_tests/all/results-02-has_cheese/has_cheese  [  FAILED  ]
/tmp/taco/taste_tests/all/results-02-has_cheese/has_cheese   FAIL: No cheese.
"""
        test_report_2 = """
/tmp/taco/verify_tests/all/results-01-has_salsa              [  PASSED  ]
/tmp/taco/verify_tests/all/results-01-has_salsa/has_salsa    [  PASSED  ]
/tmp/taco/verify_tests/all/results-02-has_cheese             [  PASSED  ]
/tmp/taco/verify_tests/all/results-02-has_cheese/has_cheese  [  PASSED  ]
"""
        results_path = os.path.join(self.tempdir, "tmp/taco")
        os.makedirs(results_path)
        # Create two reports with the same content to test that we don't
        # list the same test twice.
        osutils.WriteFile(
            os.path.join(results_path, "taste_tests", "all", "test_report.log"),
            test_report_1,
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(
                results_path, "taste_tests", "failed", "test_report.log"
            ),
            test_report_1,
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(
                results_path, "verify_tests", "all", "test_report.log"
            ),
            test_report_2,
            makedirs=True,
        )

        self.assertEqual(
            vm_test_stages.ListTests(results_path, show_passed=False),
            [("has_cheese", "taste_tests/all/results-02-has_cheese")],
        )

    def testArchiveTestResults(self):
        """Test if we can archive a test results dir."""
        test_results_dir = "tmp/taco"
        results_path = os.path.join(self.tempdir, "chroot", test_results_dir)
        archive_dir = os.path.join(self.tempdir, "archived_taco")
        os.makedirs(results_path)
        os.makedirs(archive_dir)
        # File that should be archived.
        osutils.Touch(os.path.join(results_path, "foo.txt"))
        # Flies that should be ignored.
        osutils.Touch(
            os.path.join(results_path, "chromiumos_qemu_disk.bin.foo")
        )
        os.symlink("/src/foo", os.path.join(results_path, "taco_link"))
        vm_test_stages.ArchiveTestResults(results_path, archive_dir)
        self.assertExists(os.path.join(archive_dir, "foo.txt"))
        self.assertNotExists(
            os.path.join(archive_dir, "chromiumos_qemu_disk.bin.foo")
        )
        self.assertNotExists(os.path.join(archive_dir, "taco_link"))

    def testArchiveVMFiles(self):
        """Validate ArchiveVMFiles success in archiving files."""
        test_buildroot = os.path.join(self.tempdir, "buildroot")
        image_dir = os.path.join(test_buildroot, "chroot", "testResultsDir")
        test_path_archive_output = os.path.join(self.tempdir, "testResultsDir")
        os.makedirs(test_path_archive_output)
        vm_files = ["abc.txt"]
        cros_test_lib.CreateOnDiskHierarchy(image_dir, vm_files)
        result = vm_test_stages.ArchiveVMFiles(
            test_buildroot, "testResultsDir", test_path_archive_output
        )
        # The expected output is the test_path_archive_output with the one file
        # that matches the constants VM pattern prefix, which will be converted
        # to a .bin.tar file.
        expected_result = []
        self.assertEqual(result, expected_result)
