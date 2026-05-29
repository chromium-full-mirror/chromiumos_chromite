# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for commands."""

import os
from unittest import mock

from chromite.cbuildbot import commands
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import partial_mock
from chromite.lib import path_util


class ChromeSDKTest(cros_test_lib.RunCommandTempDirTestCase):
    """Basic tests for ChromeSDK commands with run mocked out."""

    BOARD = "daisy_foo"
    EXTRA_ARGS = ("--monkey", "banana")
    EXTRA_ARGS2 = ("--donkey", "kong")
    CHROME_SRC = "chrome_src"
    CMD = ["bar", "baz"]
    CWD = "fooey"

    def setUp(self) -> None:
        self.inst = commands.ChromeSDK(self.CWD, self.BOARD)

    def testRunCommand(self) -> None:
        """Test that running a command is possible."""
        self.inst.Run(self.CMD)
        self.assertCommandContains([self.BOARD] + self.CMD, cwd=self.CWD)

    def testRunCommandWithRunArgs(self) -> None:
        """Test run_args optional argument for run kwargs."""
        self.inst.Run(self.CMD, run_args={"log_output": True})
        self.assertCommandContains(
            [self.BOARD] + self.CMD, cwd=self.CWD, log_output=True
        )

    def testRunCommandKwargs(self) -> None:
        """Exercise optional arguments."""
        custom_inst = commands.ChromeSDK(
            self.CWD,
            self.BOARD,
            extra_args=list(self.EXTRA_ARGS),
            chrome_src=self.CHROME_SRC,
            debug_log=True,
        )
        custom_inst.Run(self.CMD, list(self.EXTRA_ARGS2))
        self.assertCommandContains(
            ["debug", self.BOARD]
            + list(self.EXTRA_ARGS)
            + list(self.EXTRA_ARGS2)
            + self.CMD,
            cwd=self.CWD,
        )

    def MockGetDefaultTarget(self) -> None:
        self.rc.AddCmdResult(
            partial_mock.In("qlist-%s" % self.BOARD),
            stdout="%s" % constants.CHROME_CP,
        )

    def testNinjaWithRunArgs(self) -> None:
        """Test that running ninja with run_args.

        run_args is an optional argument for run kwargs.
        """
        self.MockGetDefaultTarget()
        self.inst.Ninja(run_args={"log_output": True})
        self.assertCommandContains(
            [
                "autoninja",
                "-C",
                "out_%s/Release" % self.BOARD,
                "chromiumos_preflight",
            ],
            cwd=self.CWD,
            log_output=True,
        )

    def testNinjaOptions(self) -> None:
        """Test that running ninja with non-default options."""
        self.MockGetDefaultTarget()
        custom_inst = commands.ChromeSDK(self.CWD, self.BOARD)
        custom_inst.Ninja(debug=True)
        self.assertCommandContains(
            [
                "autoninja",
                "-C",
                "out_%s/Debug" % self.BOARD,
                "chromiumos_preflight",
            ]
        )


class BuildTarballTests(cros_test_lib.RunCommandTempDirTestCase):
    """Tests related to building tarball artifacts."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self._buildroot = os.path.join(self.tempdir, "buildroot")
        self._path_resolver = path_util.ChrootPathResolver(
            source_path=self._buildroot
        )
        os.makedirs(self._buildroot)
        self._board = "test-board"
        self._cwd = os.path.abspath(
            self._path_resolver.FromChroot(
                os.path.join(
                    "/build",
                    self._board,
                    constants.AUTOTEST_BUILD_PATH,
                    "..",
                )
            )
        )
        self._sysroot_build = self._path_resolver.FromChroot(
            os.path.join("/build", self._board, "build")
        )
        self._tarball_dir = self.tempdir

    def testBuildAutotestPackagesTarball(self) -> None:
        """Tests that generating the autotest packages tarball is correct."""
        with mock.patch.object(commands, "BuildTarball") as m:
            commands.BuildAutotestPackagesTarball(
                self._buildroot, self._cwd, self._tarball_dir
            )
            m.assert_called_once_with(
                self._buildroot,
                ["autotest/packages"],
                os.path.join(self._tarball_dir, "autotest_packages.tar"),
                cwd=self._cwd,
                compressed=False,
            )

    def testBuildAutotestControlFilesTarball(self) -> None:
        """Tests generating the autotest control files tarball is correct."""
        control_file_list = [
            "autotest/client/site_tests/testA/control",
            "autotest/server/site_tests/testB/control",
        ]
        with mock.patch.object(commands, "FindFilesWithPattern") as find_mock:
            find_mock.return_value = control_file_list
            with mock.patch.object(commands, "BuildTarball") as tar_mock:
                commands.BuildAutotestControlFilesTarball(
                    self._buildroot, self._cwd, self._tarball_dir
                )
                tar_mock.assert_called_once_with(
                    self._buildroot,
                    control_file_list,
                    os.path.join(self._tarball_dir, "control_files.tar"),
                    cwd=self._cwd,
                    compressed=False,
                )

    def testBuildAutotestServerPackageTarball(self) -> None:
        """Tests generating the autotest server package tarball is correct."""
        control_file_list = [
            "autotest/server/site_tests/testA/control",
            "autotest/server/site_tests/testB/control",
        ]
        # Pass a copy of the file list so the code under test can't mutate it.
        self.PatchObject(
            commands,
            "FindFilesWithPattern",
            return_value=list(control_file_list),
        )
        tar_mock = self.PatchObject(commands, "BuildTarball")

        expected_files = list(control_file_list)

        # Touch Tast paths so they'll be included in the tar command. Skip
        # creating the last file so we can verify that it's omitted from the tar
        # command.
        for p in commands.TAST_SSP_CHROOT_FILES[:-1]:
            path = path_util.FromChrootPath(
                p,
                source_path=self._buildroot,
            )
            if not os.path.exists(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            # TODO(b/236161656): Fix.
            # pylint: disable-next=consider-using-with
            open(path, "ab").close()
            expected_files.append(path)

        commands.BuildAutotestServerPackageTarball(
            self._buildroot, self._cwd, self._tarball_dir
        )

        tar_mock.assert_called_once_with(
            self._buildroot,
            expected_files,
            os.path.join(self._tarball_dir, commands.AUTOTEST_SERVER_PACKAGE),
            cwd=self._cwd,
            extra_args=mock.ANY,
            check=False,
        )


class UnmockedTests(cros_test_lib.MockTempDirTestCase):
    """Test cases which really run tests, instead of using mocks.

    ...except that we mock IsInsideChroot, for consistent behavior and to test
    the real flow, where chromite code runs outside the SDK.
    """

    _TEST_BOARD = "board"

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

    def findFilesWithPatternExpectedResults(self, root, files):
        """Generate the expected results for testFindFilesWithPattern"""
        return [os.path.join(root, f) for f in files]

    def testFindFilesWithPattern(self) -> None:
        """Verifies FindFilesWithPattern searches and excludes files properly"""
        search_files = (
            "file1",
            "test1",
            "file2",
            "dir1/file1",
            "dir1/test1",
            "dir2/file2",
        )
        search_files_root = os.path.join(
            self.tempdir, "FindFilesWithPatternTest"
        )
        cros_test_lib.CreateOnDiskHierarchy(search_files_root, search_files)
        find_all = commands.FindFilesWithPattern("*", target=search_files_root)
        expected_find_all = self.findFilesWithPatternExpectedResults(
            search_files_root, search_files
        )
        self.assertEqual(set(find_all), set(expected_find_all))
        find_test_files = commands.FindFilesWithPattern(
            "test*", target=search_files_root
        )
        find_test_expected = self.findFilesWithPatternExpectedResults(
            search_files_root, ["test1", "dir1/test1"]
        )
        self.assertEqual(set(find_test_files), set(find_test_expected))
        find_exclude = commands.FindFilesWithPattern(
            "*",
            target=search_files_root,
            exclude_dirs=(os.path.join(search_files_root, "dir1"),),
        )
        find_exclude_expected = self.findFilesWithPatternExpectedResults(
            search_files_root, ["file1", "test1", "file2", "dir2/file2"]
        )
        self.assertEqual(set(find_exclude), set(find_exclude_expected))
