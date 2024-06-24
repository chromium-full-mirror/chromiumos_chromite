# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for remoteexec_lib.py"""

import datetime
import getpass
import gzip
import json
import os
from pathlib import Path
import time

from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import remoteexec_lib
from chromite.utils import hostname_util


class TestLogArchiver(cros_test_lib.MockTempDirTestCase):
    """Tests for remoteexec_lib."""

    def setUp(self) -> None:
        self.src_dir = self.tempdir / "remoteexec_src_dir"
        self.dest_dir = self.tempdir / "remoteexec_dest_dir"

        osutils.SafeMakedirs(self.src_dir)
        osutils.SafeMakedirs(self.dest_dir)

        self.archiver = remoteexec_lib.LogsArchiver(self.dest_dir)
        self.archiver.remoteexec_log_dir_for_testing = self.src_dir

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

    def testNinjaLogArchive(self) -> None:
        """Test successful archive of ninja logs."""
        log_path = os.path.join(self.src_dir, "reclient-chromeos-chrome")

        ninja_log_path = os.path.join(log_path, "ninja_log")
        osutils.WriteFile(ninja_log_path, "Ninja Log Content\n", makedirs=True)
        timestamp = datetime.datetime(2024, 4, 1, 12, 0, 0)
        mtime = time.mktime(timestamp.timetuple())
        os.utime(ninja_log_path, ((time.time(), mtime)))

        osutils.WriteFile(
            os.path.join(log_path, "ninja_command"), "ninja_command"
        )
        osutils.WriteFile(os.path.join(log_path, "ninja_cwd"), "ninja_cwd")
        osutils.WriteFile(
            os.path.join(log_path, "ninja_env"),
            "key1=value1\0key2=value2\0",
        )
        osutils.WriteFile(os.path.join(log_path, "ninja_exit"), "0")

        archived_results = self.archiver.archive()

        username = getpass.getuser()
        pid = os.getpid()
        hostname = hostname_util.get_host_name()
        ninjalog_base_filename = "ninja_log.%s.%s.20240401-120000.%d" % (
            username,
            hostname,
            pid,
        )
        ninjalog_filename = ninjalog_base_filename + ".gz"
        # Verify the archived files in the dest_dir
        archived_dir_files = os.listdir(self.dest_dir)
        self.assertCountEqual(
            archived_dir_files,
            [
                ninjalog_filename,
            ],
        )
        # Verify the archived_tuple result.
        self.assertEqual(
            archived_results,
            [
                ninjalog_filename,
            ],
        )

        # Verify content of ninja_log file.
        ninjalog_path = os.path.join(self.dest_dir, ninjalog_filename)

        with gzip.open(ninjalog_path, "rt", encoding="utf-8") as gzip_file:
            ninja_log_content = gzip_file.read()

        content, eof, metadata_json = ninja_log_content.split("\n", 3)
        self.assertEqual("Ninja Log Content", content)
        self.assertEqual("# end of ninja log", eof)
        metadata = json.loads(metadata_json)
        self.assertEqual(
            metadata,
            {
                "platform": "chromeos",
                "cmdline": ["ninja_command"],
                "cwd": "ninja_cwd",
                "exit": 0,
                "env": {"key1": "value1", "key2": "value2"},
            },
        )

        # Verify that we cleaned up the source files after archiving.
        self.assertNotExists(
            os.path.join(self.dest_dir, ninjalog_base_filename)
        )
        self.assertNotExists(ninja_log_path)
