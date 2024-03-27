# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for remoteexec_lib.py"""

from pathlib import Path

from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import remoteexec_lib


class TestLogArchiver(cros_test_lib.RunCommandTempDirTestCase):
    """Tests for remoteexec_lib."""

    def setUp(self) -> None:
        self.src_dir = self.tempdir / "src_dir"
        self.dest_dir = self.tempdir / "dest_dir"

        osutils.SafeMakedirs(self.src_dir)
        osutils.SafeMakedirs(self.dest_dir)

        self.archiver = remoteexec_lib.LogsArchiver(self.dest_dir)
        self.archiver.src_dir_for_testing = self.src_dir

    def _create_file(self, package_name: str, filename: str) -> Path:
        path = self.src_dir / f"reclient-{package_name}" / filename
        osutils.WriteFile(
            path,
            f"Package: {package_name}\nFile: {filename}",
            makedirs=True,
        )
        return path

    def testArchiveFiles(self) -> None:
        """Test LogArchiver.Archive() method."""
        interesting_log_files = [
            self._create_file("chromeos-chrome", "test.INFO.log"),
            self._create_file("chromeos-chrome", "reproxy_test.INFO"),
            self._create_file("chromeos-chrome", "reproxy_test.rrpl"),
        ]
        uninteresting_log_files = [
            self._create_file("chromeos-chrome", "test.INFO"),
        ]

        archive_files = self.archiver.archive()

        self.assertEqual(
            archive_files,
            [
                "reclient-chromeos-chrome/test.INFO.log.gz",
                "reclient-chromeos-chrome/reproxy_test.INFO.gz",
                "reclient-chromeos-chrome/reproxy_test.rrpl.gz",
            ],
        )

        for file in archive_files:
            self.assertExists(self.dest_dir / file)

        for file in interesting_log_files:
            self.assertNotExists(file)

        for file in uninteresting_log_files:
            self.assertExists(file)
