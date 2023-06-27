# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing various flavours of VM test stages.

These stages all test the ChromeOS image by running it in some sort of VM.
The tests themselves may vary, as may the harness used to manage the VM.
But they all share some common operations around creating the VM image,
archiving results and VM images in case of failure.
"""

import logging
import os
import re
import shutil

from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import generic_stages
from chromite.lib import cgroups
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import failures_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import timeout_util
from chromite.service import artifacts as artifacts_svc


_GCE_TEST_RESULTS = "gce_test_results_%(attempt)s"
_VM_TEST_RESULTS = "vm_test_results_%(attempt)s"

_ERROR_MSG = """
!!!%(test_name)s failed!!!

Logs are uploaded in the corresponding %(test_results)s. This can be found
by clicking on the artifacts link in the "Report" Stage. Specifically look
for the test_harness/failed for the failing tests. For more
particulars, please refer to which test failed i.e. above see the
individual test that failed -- or if an update failed, check the
corresponding update directory.
"""

# For sorting through VM test results.
_TEST_REPORT_FILENAME = "test_report.log"
_TEST_PASSED = "PASSED"
_TEST_FAILED = "FAILED"

# This is where the external disk is mounted by moblab VM.
_MOBLAB_STATIC_MOUNT_PATH = os.path.join("/", "mnt", "moblab")
# Must be under '.../static' for staging to work.
_MOBLAB_PAYLOAD_CACHE_DIR = os.path.join("static", "prefetched")
_DEVSERVER_STAGE_URL = (
    "http://localhost:8080/stage?local_path=%(payload_dir)s"
    "&delete_source=True"
    "&artifacts=full_payload,stateful,quick_provision,"
    "test_suites,control_files,autotest_packages,autotest_server_package"
)


class VMTestStage(
    generic_stages.BoardSpecificBuilderStage, generic_stages.ArchivingStageMixin
):
    """Run autotests in a virtual machine."""

    option_name = "tests"
    config_name = "vm_tests"
    category = constants.TEST_INFRA_STAGE

    def __init__(
        self,
        builder_run,
        buildstore,
        board,
        vm_tests=None,
        ssh_port=9228,
        test_basename=None,
        **kwargs,
    ):
        """Initiailization of the VMTestStage.

        Args:
            builder_run: BoardRunAttributes object for this stage.
            buildstore: BuildStore instance to make DB calls with.
            board: The active board for this stage.
            vm_tests: vm_tests to run at this stage. If None is specified, use
                builder_run.config.vm_tests instead.
            ssh_port: ssh port to access the VM. Default: 9228.
            test_basename: The basename that the tests are archived to. If None
                is specified, use constants.VM_TEST_RESULTS instead.
        """
        self._vm_tests = vm_tests
        self._ssh_port = ssh_port
        self._test_basename = test_basename
        self._stage_exception_handler = super()._HandleStageException
        super().__init__(builder_run, buildstore, board, **kwargs)

    def _PrintFailedTests(self, results_path, test_basename):
        """Print links to failed tests.

        Args:
            results_path: Path to directory containing the test results.
            test_basename: The basename that the tests are archived to.
        """
        test_list = ListTests(results_path, show_passed=False)
        for test_name, path in test_list:
            self.PrintDownloadLink(
                os.path.join(test_basename, path), text_to_display=test_name
            )

    def _NoTestResults(self, path):
        """Whether |path| is not a directory or is an empty directory."""
        return not os.path.isdir(path) or not os.listdir(path)

    @failures_lib.SetFailureType(failures_lib.InfrastructureFailure)
    def _ArchiveTestResults(self, test_results_dir, test_basename):
        """Archives test results to Google Storage.

        Args:
            test_results_dir: Name of the directory containing the test results.
            test_basename: The basename to archive the tests.
        """
        results_path = GetTestResultsDir(self._build_root, test_results_dir)

        # Skip archiving if results_path does not exist or is an empty
        # directory.
        if self._NoTestResults(results_path):
            return

        archived_results_dir = os.path.join(self.archive_path, test_basename)
        # Copy relevant files to archvied_results_dir.
        ArchiveTestResults(results_path, archived_results_dir)
        upload_paths = [os.path.basename(archived_results_dir)]
        # Create the compressed tarball to upload.
        # TODO: We should revisit whether uploading the tarball is necessary.
        test_tarball = commands.BuildAndArchiveTestResultsTarball(
            archived_results_dir, self._build_root
        )
        upload_paths.append(test_tarball)

        got_symbols = self.GetParallel(
            "breakpad_symbols_generated", pretty_name="breakpad symbols"
        )
        upload_paths += commands.GenerateStackTraces(
            self._build_root,
            self._current_board,
            test_results_dir,
            self.archive_path,
            got_symbols,
        )

        self._Upload(upload_paths)
        self._PrintFailedTests(results_path, test_basename)

        # Remove the test results directory.
        osutils.RmDir(results_path, ignore_missing=True, sudo=True)

    @failures_lib.SetFailureType(failures_lib.InfrastructureFailure)
    def _ArchiveVMFiles(self, test_results_dir):
        vm_files = ArchiveVMFiles(
            self._build_root,
            os.path.join(test_results_dir, "test_harness"),
            self.archive_path,
        )
        # We use paths relative to |self.archive_path|, for prettier
        # formatting on the web page.
        self._Upload([os.path.basename(image) for image in vm_files])

    def _Upload(self, filenames):
        logging.info("Uploading artifacts to Google Storage...")
        with self.ArtifactUploader(archive=False, strict=False) as queue:
            for filename in filenames:
                queue.put([filename])
                if filename.endswith(".dmp.txt"):
                    prefix = "crash: "
                elif constants.VM_DISK_PREFIX in os.path.basename(filename):
                    prefix = "vm_disk: "
                elif constants.VM_MEM_PREFIX in os.path.basename(filename):
                    prefix = "vm_memory: "
                else:
                    prefix = ""
                self.PrintDownloadLink(filename, prefix)

    def _RunTest(self, test_config, test_results_dir):
        """Run a VM test.

        Args:
            test_config: Any config_lib.VMTestConfig with test_type in
                constants.VALID_VM_TEST_TYPES.
            test_results_dir: The base directory to store the results.
        """
        test_type = test_config.test_type
        if test_type == constants.CROS_VM_TEST_TYPE:
            RunCrosVMTest(
                self._build_root, self._current_board, self.GetImageDirSymlink()
            )
        elif test_type == constants.DEV_MODE_TEST_TYPE:
            RunDevModeTest(
                self._build_root, self._current_board, self.GetImageDirSymlink()
            )
        else:
            image_path = os.path.join(
                self.GetImageDirSymlink(), constants.TEST_IMAGE_BIN
            )
            ssh_private_key = os.path.join(
                self.GetImageDirSymlink(), constants.TEST_KEY_PRIVATE
            )
            if not os.path.exists(ssh_private_key):
                # TODO: Disallow usage of default test key completely.
                logging.warning(
                    "Test key was not found in the image directory. "
                    "Default key will be used."
                )
                ssh_private_key = None

            RunTestSuite(
                self._build_root,
                self._current_board,
                image_path,
                os.path.join(test_results_dir, "test_harness"),
                test_config=test_config,
                allow_chrome_crashes=self._chrome_rev is None,
                ssh_private_key=ssh_private_key,
                ssh_port=self._ssh_port,
            )

    def WaitUntilReady(self):
        """Block until Archive completes tarring autotest/.

        The attribute 'autotest_tarball_generated' is set by ArchiveStage.

        Returns:
            Boolean that authorizes running of this stage.
        """
        return self.board_runattrs.GetParallel(
            "autotest_tarball_generated", timeout=None
        )

    def PerformStage(self):
        # These directories are used later to archive test artifacts.
        if not self._run.options.vmtests:
            return

        test_results_root = commands.CreateTestRoot(self._build_root)
        test_basename = _VM_TEST_RESULTS % dict(attempt=self._attempt)
        if self._test_basename:
            test_basename = self._test_basename
        try:
            if not self._vm_tests:
                self._vm_tests = self._run.config.vm_tests

            failed_tests = []
            for vm_test in self._vm_tests:
                logging.info("Running VM test %s.", vm_test.test_type)
                if vm_test.test_type == constants.VM_SUITE_TEST_TYPE:
                    per_test_results_dir = os.path.join(
                        test_results_root, vm_test.test_suite
                    )
                else:
                    per_test_results_dir = os.path.join(
                        test_results_root, vm_test.test_type
                    )
                try:
                    with cgroups.SimpleContainChildren("VMTest"):
                        r = " Reached VMTestStage test run timeout."
                        with timeout_util.Timeout(
                            vm_test.timeout, reason_message=r
                        ):
                            self._RunTest(vm_test, per_test_results_dir)
                except Exception:
                    failed_tests.append(vm_test)
                    if vm_test.warn_only:
                        logging.warning(
                            "Optional test failed. Forgiving the failure."
                        )
                    else:
                        raise

            if failed_tests:
                # If any of the tests failed but not raise an exception, mark
                # the stage as warning.
                self._stage_exception_handler = self._HandleExceptionAsWarning
                raise failures_lib.TestWarning(
                    "VMTestStage succeeded, but some optional tests failed."
                )
        except Exception as e:
            if not isinstance(e, failures_lib.TestWarning):
                # pylint: disable=logging-not-lazy
                logging.error(
                    _ERROR_MSG
                    % dict(test_name="VMTests", test_results=test_basename)
                )
            self._ArchiveVMFiles(test_results_root)
            raise
        finally:
            self._ArchiveTestResults(test_results_root, test_basename)

    def _HandleStageException(self, exc_info):
        return self._stage_exception_handler(exc_info)


def ListTests(results_path, show_failed=True, show_passed=True):
    """Returns a list of tests.

    Parse the test report logs from autotest to find tests.

    Args:
        results_path: Path to the directory of test results.
        show_failed: Return failed tests.
        show_passed: Return passed tests.

    Returns:
        A lists of (test_name, relative/path/to/tests)
    """
    # TODO: we don't have to parse the log to find tests once
    # crbug.com/350520 is fixed.
    reports = []
    for path, _, filenames in os.walk(results_path):
        reports.extend(
            [
                os.path.join(path, x)
                for x in filenames
                if x == _TEST_REPORT_FILENAME
            ]
        )

    tests = []
    processed_tests = []
    match_pattern = []
    if show_failed:
        match_pattern.append(_TEST_FAILED)
    if show_passed:
        match_pattern.append(_TEST_PASSED)

    for report in reports:
        logging.info("Parsing test report %s", report)
        # Format used in the report:
        #   /path/to/base/dir/test_harness/all/SimpleTestUpdateAndVerify/ \
        #     2_autotest_tests/results-01-security_OpenSSLBlacklist [  FAILED  ]
        #   /path/to/base/dir/test_harness/all/SimpleTestUpdateAndVerify/ \
        #     2_autotest_tests/results-01-security_OpenSSLBlacklist/ \
        #     security_OpenBlacklist [  FAILED  ]
        with open(report, encoding="utf-8") as f:
            folder_re = re.compile(r"([\./\w-]*)\s*\[\s*(\S+?)\s*\]")
            test_name_re = re.compile(r"results-[\d]+?-([\.\w_]*)")
            for line in f:
                r = folder_re.search(line)
                if r and r.group(2) in match_pattern:
                    file_path = r.group(1)
                    match = test_name_re.search(file_path)
                    if match:
                        test_name = match.group(1)
                    else:
                        # If no match is found (due to format change or other
                        # reasons), simply use the last component of file_path.
                        test_name = os.path.basename(file_path)

                    # A test may have subtests. We don't want to list all
                    # subtests.
                    if test_name not in processed_tests:
                        base_dirname = os.path.basename(results_path)
                        # Get the relative path from the test_results directory.
                        # Note that file_path is a chroot path, while
                        # results_path is a non-chroot path, so we cannot use
                        # os.path.relpath directly.
                        rel_path = file_path.split(base_dirname)[1].lstrip(
                            os.path.sep
                        )
                        tests.append((test_name, rel_path))
                        processed_tests.append(test_name)
    return tests


def GetTestResultsDir(buildroot, test_results_dir):
    """Returns the test results directory located in chroot.

    Args:
        buildroot: Root directory where build occurs.
        test_results_dir: Path from buildroot/chroot to find test results. This
            must a subdir of /tmp.
    """
    test_results_dir = test_results_dir.lstrip("/")
    return os.path.join(
        buildroot, constants.DEFAULT_CHROOT_DIR, test_results_dir
    )


def ArchiveTestResults(results_path, archive_dir):
    """Archives the test results to |archive_dir|.

    Args:
        results_path: Path to test results.
        archive_dir: Local directory to archive to.
    """
    cros_build_lib.sudo_run(
        ["chmod", "-R", "a+rw", results_path], print_cmd=False
    )
    if os.path.exists(archive_dir):
        osutils.RmDir(archive_dir)

    def _ShouldIgnore(dirname, file_list):
        # Note: We exclude VM disk and memory images. Instead, they are
        # archived via ArchiveVMFiles. Also skip any symlinks. gsutil
        # hangs on broken symlinks.
        return [
            x
            for x in file_list
            if x.startswith(constants.VM_DISK_PREFIX)
            or x.startswith(constants.VM_MEM_PREFIX)
            or os.path.islink(os.path.join(dirname, x))
        ]

    shutil.copytree(
        results_path, archive_dir, symlinks=False, ignore=_ShouldIgnore
    )


def ArchiveVMFiles(buildroot, test_results_dir, archive_path):
    """Archives the VM memory and disk images into tarballs.

    There may be multiple tests (e.g. SimpleTestUpdate and
    SimpleTestUpdateAndVerify), and multiple files for each test (one
    for the VM disk, and one for the VM memory). We create a separate
    tar file for each of these files, so that each can be downloaded
    independently.

    Args:
        buildroot: Build root directory.
        test_results_dir: Path from buildroot/chroot to find test results. This
            must a subdir of /tmp.
        archive_path: Directory the tarballs should be written to.

    Returns:
        The paths to the tarballs.
    """
    images_dir = os.path.join(buildroot, "chroot", test_results_dir.lstrip("/"))
    return artifacts_svc.ArchiveFilesFromImageDir(images_dir, archive_path)


def RunCrosVMTest(buildroot, board, image_dir):
    """Runs cros_vm_test script to verify cros commands work."""
    image_path = os.path.join(image_dir, constants.TEST_IMAGE_BIN)
    script = os.path.join(
        buildroot, "chromite", "cli", "cros", "tests", "cros_vm_test"
    )
    commands.RunBuildScript(
        buildroot, [script, "--board", board, "--image_path", image_path]
    )


def RunDevModeTest(buildroot, board, image_dir):
    """Runs the dev mode testing script to verify dev-mode scripts work."""
    crostestutils = os.path.join(buildroot, "src", "platform", "crostestutils")
    image_path = os.path.join(image_dir, constants.TEST_IMAGE_BIN)
    test_script = "devmode-test/devinstall_test.py"
    cmd = [
        os.path.join(crostestutils, test_script),
        "--verbose",
        board,
        image_path,
    ]
    cros_build_lib.run(cmd)


def RunTestSuite(
    buildroot,
    board,
    image_path,
    results_dir,
    test_config,
    allow_chrome_crashes,
    ssh_private_key=None,
    ssh_port=9228,
):
    """Runs the test harness suite."""
    if (
        test_config.use_ctest
        or test_config.test_type != constants.VM_SUITE_TEST_TYPE
    ):
        _RunTestSuiteUsingCtest(
            buildroot,
            board,
            image_path,
            results_dir,
            test_config,
            allow_chrome_crashes,
            ssh_private_key,
            ssh_port,
        )
    else:
        _RunTestSuiteUsingChromite(
            board,
            image_path,
            results_dir,
            test_config,
            allow_chrome_crashes,
            ssh_private_key,
            ssh_port,
        )


# TODO(zamorzaev): absorb this function into RunTestSuite after deprecating
# ctest.
def _RunTestSuiteUsingChromite(
    board,
    image_path,
    results_dir,
    test_config,
    allow_chrome_crashes,
    ssh_private_key=None,
    ssh_port=9228,
):
    """Runs the test harness suite using the chromite code path."""
    image_dir = os.path.dirname(image_path)
    image_path = os.path.join(image_dir, constants.TEST_IMAGE_BIN)

    cmd = [
        "cros_run_test",
        "--debug",
        "--board=%s" % board,
        "--image-path=%s" % path_util.ToChrootPath(image_path),
        "--ssh-port=%s" % ssh_port,
        "--autotest=suite:%s" % test_config.test_suite,
        "--results-dir=%s" % results_dir,
    ]

    if allow_chrome_crashes:
        cmd.append("--test_that-args=--allow-chrome-crashes")

    if ssh_private_key is not None:
        cmd.append("--private-key=%s" % path_util.ToChrootPath(ssh_private_key))

    # Give tests 10 minutes to clean up before shutting down.
    result = cros_build_lib.run(
        cmd, check=False, kill_timeout=10 * 60, enter_chroot=True
    )
    if result.returncode:
        results_dir_in_chroot = os.path.join(
            constants.SOURCE_ROOT,
            constants.DEFAULT_CHROOT_DIR,
            results_dir.lstrip("/"),
        )
        if os.path.exists(results_dir_in_chroot):
            error = "%s exited with code %d" % (
                " ".join(cmd),
                result.returncode,
            )
            with open(
                results_dir_in_chroot + "/failed_test_command",
                "w",
                encoding="utf-8",
            ) as failed:
                failed.write(error)

        raise failures_lib.TestFailure(
            "** VMTests failed with code %d **" % result.returncode
        )


def _RunTestSuiteUsingCtest(
    buildroot,
    board,
    image_path,
    results_dir,
    test_config,
    allow_chrome_crashes,
    ssh_private_key=None,
    ssh_port=9228,
):
    """Runs the test harness suite using the ctest code path."""
    results_dir_in_chroot = os.path.join(
        buildroot, "chroot", results_dir.lstrip("/")
    )
    osutils.RmDir(results_dir_in_chroot, ignore_missing=True)

    test_type = test_config.test_type
    cwd = os.path.join(buildroot, "src", "scripts")
    dut_type = "gce" if test_type == constants.GCE_SUITE_TEST_TYPE else "vm"

    crostestutils = os.path.join(buildroot, "src", "platform", "crostestutils")
    cmd = [
        os.path.join(
            crostestutils, "au_test_harness", "cros_au_test_harness.py"
        ),
        "--board=%s" % board,
        "--type=%s" % dut_type,
        "--no_graphics",
        "--verbose",
        "--target_image=%s" % image_path,
        "--test_results_root=%s" % results_dir_in_chroot,
    ]

    if test_type not in constants.VALID_VM_TEST_TYPES:
        raise AssertionError("Unrecognized test type %r" % test_type)

    if test_type in [
        constants.VM_SUITE_TEST_TYPE,
        constants.GCE_SUITE_TEST_TYPE,
    ]:
        cmd.append("--ssh_port=%s" % ssh_port)
        cmd.append("--verify_suite_name=%s" % test_config.test_suite)

    cmd.append("--test_prefix=SimpleTestVerify")

    if allow_chrome_crashes:
        cmd.append("--allow_chrome_crashes")

    if ssh_private_key is not None:
        cmd.append("--ssh_private_key=%s" % ssh_private_key)

    # Give tests 10 minutes to clean up before shutting down.
    result = cros_build_lib.run(cmd, cwd=cwd, check=False, kill_timeout=10 * 60)
    if result.returncode:
        if os.path.exists(results_dir_in_chroot):
            error = "%s exited with code %d" % (
                " ".join(cmd),
                result.returncode,
            )
            with open(
                results_dir_in_chroot + "/failed_test_command",
                "w",
                encoding="utf-8",
            ) as failed:
                failed.write(error)

        raise failures_lib.TestFailure(
            "** VMTests failed with code %d **" % result.returncode
        )
