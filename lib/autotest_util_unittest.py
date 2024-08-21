# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the autotest_util module."""

import os
from unittest import mock

from chromite.lib import autotest_util
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import sysroot_lib
from chromite.utils import matching


def create_tast_layout(
    chroot: chroot_lib.Chroot,
    _sysroot: sysroot_lib.Sysroot,
) -> None:
    """Create a layout that matches a real public tast install."""
    D = cros_test_lib.Directory
    filesystem = (
        D(
            "usr",
            (
                D("bin", ("tast", "remote_test_runner")),
                D(
                    "libexec",
                    (
                        D(
                            "tast",
                            (
                                D(
                                    "bundles",
                                    (D("remote", ("cros", "crosint")),),
                                ),
                            ),
                        ),
                    ),
                ),
                D(
                    "share",
                    (D("tast", (D("data", (D("go.chromium.org", ()),)),)),),
                ),
            ),
        ),
    )
    cros_test_lib.CreateOnDiskHierarchy(chroot.path, filesystem)


class BuildTarballTests(cros_test_lib.RunCommandTempDirTestCase):
    """Tests related to building tarball artifacts."""

    # pylint: disable=protected-access

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self._buildroot = os.path.join(self.tempdir, "buildroot")
        os.makedirs(self._buildroot)
        self._board = "test-board"
        self.basedir = os.path.normpath(
            os.path.join(
                self._buildroot,
                "chroot",
                "build",
                self._board,
                constants.AUTOTEST_BUILD_PATH,
                "..",
            )
        )
        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot",
            out_path=self.tempdir / "out",
        )
        self.sysroot = sysroot_lib.Sysroot(
            build_target_lib.get_default_sysroot_path(self._board)
        )
        self.builder = autotest_util.AutotestTarballBuilder(
            self.basedir, self.tempdir, self.chroot, self.sysroot
        )

    def testBuildAutotestPackagesTarball(self) -> None:
        """Tests that generating the autotest packages tarball is correct."""
        tar_mock = self.PatchObject(self.builder, "_BuildTarball")
        tar_path = os.path.join(self.tempdir, self.builder._PACKAGES_ARCHIVE)

        self.builder.BuildAutotestPackagesTarball()

        tar_mock.assert_called_once_with(
            ["autotest/packages"], tar_path, compressed=False
        )

    def testBuildAutotestTestSuitesTarball(self) -> None:
        """Tests that generating the autotest packages tarball is correct."""
        tar_mock = self.PatchObject(self.builder, "_BuildTarball")
        tar_path = os.path.join(self.tempdir, self.builder._TEST_SUITES_ARCHIVE)

        self.builder.BuildAutotestTestSuitesTarball()

        tar_mock.assert_called_once_with(["autotest/test_suites"], tar_path)

    def testBuildAutotestControlFilesTarball(self) -> None:
        """Verify generating the autotest control files tarball is correct."""
        control_file_list = [
            "autotest/client/site_tests/testA/control",
            "autotest/server/site_tests/testB/control",
        ]
        tar_path = os.path.join(
            self.tempdir, self.builder._CONTROL_FILES_ARCHIVE
        )

        tar_mock = self.PatchObject(self.builder, "_BuildTarball")
        self.PatchObject(
            matching, "FindFilesMatching", return_value=control_file_list
        )

        self.builder.BuildAutotestControlFilesTarball()

        tar_mock.assert_called_once_with(
            control_file_list, tar_path, compressed=False
        )

    def testBuildAutotestServerPackageTarball(self) -> None:
        """Verify generating the autotest server package tarball is correct."""
        control_file_list = [
            "autotest/server/site_tests/testA/control",
            "autotest/server/site_tests/testB/control",
        ]
        tar_path = os.path.join(
            self.tempdir, self.builder._SERVER_PACKAGE_ARCHIVE
        )

        create_tast_layout(self.chroot, self.sysroot)
        expected_files = list(control_file_list)
        ssp_files = []

        # All the chroot files should exist.
        for p in self.builder._TAST_SSP_CHROOT_FILES:
            path = p.get_src(self.chroot, self.sysroot)
            expected_files.append(path)
            ssp_files.append(p)

        # Verify skipping of source files.
        for p in self.builder._TAST_SSP_SOURCE_FILES:
            ssp_files.append(
                autotest_util.PathMapping(
                    os.path.join(self.basedir, p.raw_src),
                    missing_ok=True,
                )
            )

        tar_mock = self.PatchObject(self.builder, "_BuildTarball")
        self.PatchObject(
            self.builder, "_GetTastSspFiles", return_value=ssp_files
        )
        # Pass a copy of the file list so the code under test can't mutate it.
        self.PatchObject(
            matching, "FindFilesMatching", return_value=control_file_list
        )

        self.builder.BuildAutotestServerPackageTarball()

        tar_mock.assert_called_once_with(
            expected_files, tar_path, extra_args=mock.ANY, check=False
        )

    def testBuildAutotestTarball(self) -> None:
        """Tests that generating the autotest tarball is correct."""
        tar_mock = self.PatchObject(self.builder, "_BuildTarball")
        tar_path = os.path.join(self.tempdir, self.builder._AUTOTEST_ARCHIVE)

        self.builder.BuildAutotestTarball()

        tar_mock.assert_called_once_with(["autotest/"], tar_path)
