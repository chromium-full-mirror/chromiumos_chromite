# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the compression_lib module."""

import os
from pathlib import Path
from typing import List

import pytest

from chromite.lib import cipd
from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils


class TarballTests(cros_test_lib.TempDirTestCase):
    """Test tarball handling functions."""

    def setUp(self) -> None:
        """Create files/dirs needed for tar test."""
        self.tarball_path = os.path.join(self.tempdir, "test.tar.xz")
        self.input_dir = os.path.join(self.tempdir, "inputs")
        self.inputs = [
            "inputA",
            "inputB",
            "sub/subfile",
            "sub2/subfile",
        ]

        self.inputs_with_dirs = [
            "inputA",
            "inputB",
            "sub",
            "sub2",
        ]

        # Create the input files.
        for i in self.inputs:
            osutils.WriteFile(os.path.join(self.input_dir, i), i, makedirs=True)

    def test_create_success(self) -> None:
        """Create a tarfile."""
        compression_lib.create_tarball(
            self.tarball_path, self.input_dir, inputs=self.inputs
        )

    def test_create_success_with_dirs(self) -> None:
        """Create a tarfile."""
        compression_lib.create_tarball(
            self.tarball_path, self.input_dir, inputs=self.inputs_with_dirs
        )

    def test_create_success_with_too_many_files(self) -> None:
        """Test a tarfile creation with -T /dev/stdin."""
        # pylint: disable=protected-access
        num_inputs = compression_lib._THRESHOLD_TO_USE_T_FOR_TAR + 1
        inputs = ["input%s" % x for x in range(num_inputs)]
        largeInputDir = os.path.join(self.tempdir, "largeinputs")
        for i in inputs:
            osutils.WriteFile(os.path.join(largeInputDir, i), i, makedirs=True)
        compression_lib.create_tarball(
            self.tarball_path, largeInputDir, inputs=inputs
        )

    def test_create_extract_success_with_no_compression_program(self) -> None:
        """Create a tarfile without any compression, then extract it."""
        path = os.path.join(self.tempdir, "test.tar")
        compression_lib.create_tarball(path, self.input_dir, inputs=self.inputs)
        compression_lib.extract_tarball(path, self.tempdir)

        # Again, but using Path instead of str paths.
        path = Path(path)
        compression_lib.create_tarball(
            path, Path(self.input_dir), inputs=self.inputs
        )
        compression_lib.extract_tarball(path, self.tempdir)

    def test_create_extract_success_with_compression_program(self) -> None:
        """Create a tarfile with compression, then extract it."""
        tar_files = [
            "test.tar.gz",
            "test.tar.bz2",
            "test.tar.xz",
            "test.tar.zst",
        ]
        dir_path = self.tempdir / "dir"
        dir_path.mkdir()
        D = cros_test_lib.Directory
        dir_structure = [
            D(".", []),
            D("test", ["file1.txt"]),
            D("foo", ["file1.txt"]),
            D("bar", ["file1.txt", "file2.c"]),
        ]
        cros_test_lib.CreateOnDiskHierarchy(dir_path, dir_structure)

        for tar_file in tar_files:
            tar_file_path = self.tempdir / tar_file
            comp = compression_lib.CompressionType.from_extension(tar_file)
            compression_lib.create_tarball(
                tar_file_path, dir_path, compression=comp
            )
            cros_test_lib.VerifyTarball(tar_file_path, dir_structure)

    def test_extract_failure_with_missing_file(self) -> None:
        """Verify that stderr from tar is printed if in encounters an error."""
        tarball = "a-tarball-which-does-not-exist.tar.gz"

        with pytest.raises(compression_lib.TarballError):
            compression_lib.extract_tarball(tarball, self.tempdir)

    def test_custom_compressor(self) -> None:
        """Create a tarfile with a custom compressor program."""
        # The "compressor" will write a unique string, and then read+discard all
        # of input to avoid races where the compressor exits before tar writes
        # all of the data to it.
        compression_lib.create_tarball(
            self.tarball_path,
            self.input_dir,
            inputs=self.inputs,
            compressor=["sh", "-c", "echo hi bye; cat >/dev/null"],
        )
        assert osutils.ReadFile(self.tarball_path) == "hi bye\n"


@pytest.mark.parametrize(
    ["filename", "is_tarball"],
    [
        ("file.tar", True),
        ("file.tar.bz2", True),
        ("file.tar.gz", True),
        ("file.tar.xz", True),
        ("file.tar.zst", True),
        ("file.tbz", True),
        ("file.txz", True),
        ("file.txt", False),
        ("file.tart", False),
        ("file.bz2", False),
    ],
)
def test_is_tarball(filename: str, is_tarball: bool) -> None:
    """Test is_tarball helper function."""
    assert compression_lib.is_tarball(filename) == is_tarball


# Tests for tar exceptions.
class FailedCreateTarballExceptionTests(
    cros_test_lib.TempDirTestCase, cros_test_lib.LoggingTestCase
):
    """Tests exception handling for create_tarball."""

    def setUp(self) -> None:
        self.input_dir = os.path.join(self.tempdir, "BadInputDirectory")

    def test_success(self) -> None:
        """Verify tarball creation when cwd and target dir exist."""
        target_dir = os.path.join(self.tempdir, "target_dir")
        target_file = os.path.join(target_dir, "stuff.tar")
        osutils.SafeMakedirs(target_dir)
        working_dir = os.path.join(self.tempdir, "working_dir")
        osutils.SafeMakedirs(working_dir)
        osutils.WriteFile(os.path.join(working_dir, "file1.txt"), "file1")
        osutils.WriteFile(os.path.join(working_dir, "file2.txt"), "file2")
        compression_lib.create_tarball(target_file, working_dir)
        target_contents = os.listdir(target_dir)
        self.assertEqual(target_contents, ["stuff.tar"])

    def test_failure_bad_target(self) -> None:
        """Verify expected error when target does not exist."""
        target_dir = os.path.join(self.tempdir, "target_dir")
        target_file = os.path.join(target_dir, "stuff.tar")
        working_dir = os.path.join(self.tempdir, "working_dir")
        osutils.SafeMakedirs(working_dir)
        with cros_test_lib.LoggingCapturer() as logs:
            with self.assertRaises(compression_lib.TarballError):
                compression_lib.create_tarball(target_file, working_dir)
            self.AssertLogsContain(logs, "create_tarball failed creating")

    def test_failure_bad_working_dir(self) -> None:
        """Verify expected error when cwd does not exist."""
        target_dir = os.path.join(self.tempdir, "target_dir")
        osutils.SafeMakedirs(target_dir)
        target_file = os.path.join(target_dir, "stuff.tar")
        working_dir = os.path.join(self.tempdir, "working_dir")
        with cros_test_lib.LoggingCapturer() as logs:
            with self.assertRaises(cros_build_lib.RunCommandError):
                compression_lib.create_tarball(target_file, working_dir)
            self.AssertLogsContain(logs, "create_tarball unable to run tar for")


# Tests for tar failure retry logic.
class FailedCreateTarballTests(cros_test_lib.RunCommandTestCase):
    """Tests special case error handling for create_tarball."""

    def setUp(self) -> None:
        """Mock run mock."""
        # Each test can change this value as needed.  Each element is the return
        # code in the CompletedProcess for subsequent calls to run().
        self.tarResults = []

        def Result(*_args, **_kwargs):
            """Creates CompletedProcess objects for each tarResults value."""
            return cros_build_lib.CompletedProcess(
                stdout="", stderr="", returncode=self.tarResults.pop(0)
            )

        self.rc.SetDefaultCmdResult(side_effect=Result)

    def test_success(self) -> None:
        """create_tarball works the first time."""
        self.tarResults = [0]
        compression_lib.create_tarball("foo", "bar", inputs=["a", "b"])

        self.assertEqual(self.rc.call_count, 1)

    def test_failed_once_soft(self) -> None:
        """Force a single retry for create_tarball."""
        self.tarResults = [1, 0]
        compression_lib.create_tarball(
            "foo", "bar", inputs=["a", "b"], timeout=0
        )

        self.assertEqual(self.rc.call_count, 2)

    def test_failed_once_hard(self) -> None:
        """Test unrecoverable error."""
        self.tarResults = [2]
        with pytest.raises(compression_lib.TarballError):
            compression_lib.create_tarball("foo", "bar", inputs=["a", "b"])

        self.assertEqual(self.rc.call_count, 1)

    def test_failed_thrice_soft(self) -> None:
        """Exhaust retries for recoverable errors."""
        self.tarResults = [1, 1, 1]
        with pytest.raises(compression_lib.TarballError):
            compression_lib.create_tarball(
                "foo", "bar", inputs=["a", "b"], timeout=0
            )

        self.assertEqual(self.rc.call_count, 3)


class FindCompressorTests(cros_test_lib.MockTempDirTestCase):
    """Tests for find_compressor."""

    def _test_comp(
        self, comps: List[str], comp_type: compression_lib.CompressionType
    ) -> None:
        """Helper for find_compressor testing."""
        for comp in comps:
            comp_root = self.tempdir / comp
            comp_path = comp_root / "bin" / comp
            osutils.Touch(comp_path, makedirs=True, mode=0o755)
            self.assertEqual(
                comp_path,
                Path(
                    compression_lib.find_compressor(comp_type, root=comp_root)
                ),
            )

    def test_find_compressor_xz(self) -> None:
        """Test find_compressor with xz."""
        self.assertEqual(
            str(constants.CHROMITE_SCRIPTS_DIR / "xz_auto"),
            compression_lib.find_compressor(compression_lib.CompressionType.XZ),
        )

    def test_find_compressor_gzip(self) -> None:
        """Test find_compressor with gzip."""
        comps = ("pigz", "gzip")
        self._test_comp(comps, compression_lib.CompressionType.GZIP)

    def test_find_compressor_gzip_not_found(self) -> None:
        """Test find_compressor with missing xz."""
        self.assertEqual(
            "gzip",
            compression_lib.find_compressor(
                compression_lib.CompressionType.GZIP, root=self.tempdir
            ),
        )

    def test_find_compressor_bzip2(self) -> None:
        """Test find_compressor with bzip2."""
        comps = ("lbzip2", "pbzip2", "bzip2")
        self._test_comp(comps, compression_lib.CompressionType.BZIP2)

    def test_find_compressor_bzip2_not_found(self) -> None:
        """Test find_compressor with missing bzip2."""
        self.assertEqual(
            "bzip2",
            compression_lib.find_compressor(
                compression_lib.CompressionType.BZIP2, root=self.tempdir
            ),
        )

    def test_find_compressor_zstd_inside_chroot(self) -> None:
        """Test find_compressor with zstd inside the chroot."""
        assert (
            compression_lib.find_compressor(
                compression_lib.CompressionType.ZSTD
            )
            == "pzstd"
        )

    def test_find_compressor_zstd_outside_chroot(self) -> None:
        """Test find_compressor uses cipd outside the chroot."""
        fake_cipd_path = Path("/some/path/to/a/fake/cipd")
        fake_pzstd_path = Path("/some/path/to/a/fake/pzstd")

        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        self.PatchObject(cipd, "GetCIPDFromCache", return_value=fake_cipd_path)
        self.PatchObject(cipd, "InstallPackage", return_value=fake_pzstd_path)

        assert compression_lib.find_compressor(
            compression_lib.CompressionType.ZSTD
        ) == str(fake_pzstd_path / "bin" / "pzstd")

    def test_find_compressor_none(self) -> None:
        """Test find_compressor for none type."""
        self.assertEqual(
            "cat",
            compression_lib.find_compressor(
                compression_lib.CompressionType.NONE
            ),
        )

    def test_find_compressor_invalid(self) -> None:
        """Test find_compressor with invalid compression type."""
        with self.assertRaises(ValueError):
            compression_lib.find_compressor(888)


class CompressFileTests(
    cros_test_lib.TempDirTestCase, cros_test_lib.RunCommandTestCase
):
    """Tests for compress_file."""

    def test_compress_file(self) -> None:
        """Test compress_file."""
        self.PatchObject(
            compression_lib.CompressionType,
            "from_extension",
            return_value=compression_lib.CompressionType.ZSTD,
        )
        self.PatchObject(
            compression_lib, "find_compressor", return_value="<foobar comp>"
        )

        # Run test.
        compression_lib.compress_file(
            self.tempdir / "infile", self.tempdir / "outfile"
        )

        # Verify.
        self.rc.assertCommandCalled(
            ["<foobar comp>", "-c", "--", self.tempdir / "infile"],
            stdout=self.tempdir / "outfile",
        )

    def test_compress_file_with_compression_level(self) -> None:
        """Test compress_file with compression level."""
        self.PatchObject(
            compression_lib.CompressionType,
            "from_extension",
            return_value=compression_lib.CompressionType.ZSTD,
        )
        self.PatchObject(
            compression_lib, "find_compressor", return_value="<foobar comp>"
        )

        # Run test.
        compression_lib.compress_file(
            self.tempdir / "infile",
            self.tempdir / "outfile",
            compression_level=123,
        )

        # Verify.
        self.rc.assertCommandCalled(
            [
                "<foobar comp>",
                "-c",
                "-123",
                "--",
                self.tempdir / "infile",
            ],
            stdout=self.tempdir / "outfile",
        )

    def test_compress_file_with_zero_compression_level(self) -> None:
        """Test compress_file with compression level as 0."""
        self.PatchObject(
            compression_lib.CompressionType,
            "from_extension",
            return_value=compression_lib.CompressionType.ZSTD,
        )
        self.PatchObject(
            compression_lib, "find_compressor", return_value="<foobar comp>"
        )

        # Run test.
        compression_lib.compress_file(
            self.tempdir / "infile",
            self.tempdir / "outfile",
            compression_level=0,
        )

        # Verify.
        self.rc.assertCommandContains(
            [
                "<foobar comp>",
                "-c",
                "-0",
                "--",
                self.tempdir / "infile",
            ],
            stdout=self.tempdir / "outfile",
        )
