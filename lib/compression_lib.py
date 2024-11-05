# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Library for creating and unpacking compressed files."""

from __future__ import annotations

import enum
import functools
import logging
import os
from pathlib import Path
import time
from typing import Any, List, Optional, Union

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import metrics_lib
from chromite.utils import shell_util


# The number of files is larger than this, we will use -T option
# and files to be added may not show up to the command line.
_THRESHOLD_TO_USE_T_FOR_TAR = 50

# CIPD package to use for pzstd.
_ZSTD_PACKAGE = "chromiumos/infra/tools/zstd"
_ZSTD_VERSION = "abrFYnkC7NRoeegtP-DBjpFl2qboH8T8LC-9CevwR38C"


class CompressionType(enum.IntEnum):
    """Type of compression."""

    NONE = 0
    GZIP = 1
    BZIP2 = 2
    XZ = 3
    ZSTD = 4

    @classmethod
    def from_str(cls, s: str) -> Optional[CompressionType]:
        """Convert a compression string type to a constant.

        Args:
            s: string to check

        Returns:
            A constant, or None if the compression type is unknown.
        """
        _COMP_STR = {
            "gz": cls.GZIP,
            "bz2": cls.BZIP2,
            "xz": cls.XZ,
            "zst": cls.ZSTD,
        }
        if s:
            return _COMP_STR.get(s)
        else:
            return cls.NONE

    @classmethod
    def from_extension(
        cls, file_name: Union[Path, "os.PathLike[str]"]
    ) -> CompressionType:
        """Retrieve a compression type constant from a compression file's name.

        Args:
            file_name: Name of a compression file.

        Returns:
            A constant, return CompressionType.NONE if the extension is unknown.
        """
        ext = os.path.splitext(file_name)[-1]
        _COMP_EXT = {
            ".tgz": cls.GZIP,
            ".gz": cls.GZIP,
            ".tbz2": cls.BZIP2,
            ".bz2": cls.BZIP2,
            ".txz": cls.XZ,
            ".xz": cls.XZ,
            ".zst": cls.ZSTD,
        }
        return _COMP_EXT.get(ext, cls.NONE)

    @classmethod
    def detect_from_file(
        cls,
        path: Union[str, "os.PathLike[str]"],
    ) -> CompressionType:
        """Detect the type of compression used by |path| by sniffing its data.

        Args:
            path: The file to sniff.

        Returns:
            The compression type if we could detect it.
        """
        if not isinstance(path, Path):
            path = Path(path)

        with path.open("rb") as f:
            data = f.read(6)

        MAGIC_TO_TYPE = (
            (b"BZh", cls.BZIP2),
            (b"\x1f\x8b", cls.GZIP),
            (b"\xfd\x37\x7a\x58\x5a\x00", cls.XZ),
            (b"\x28\xb5\x2f\xfd", cls.ZSTD),
            (b"\x50\x2a\x4d\x18", cls.ZSTD),
        )
        for magic, ctype in MAGIC_TO_TYPE:
            if data.startswith(magic):
                return ctype
        return cls.NONE


def _ensure_pzstd() -> str:
    """Download pzstd from cipd as required.

    Returns:
        Command to run for pzstd.
    """
    # Yucky deferred import is to avoid circular import of chromite.lib.cache
    # during unit tests.
    # pylint: disable-next=wrong-import-position
    from chromite.lib import cipd

    if cros_build_lib.IsInsideChroot():
        return "pzstd"

    cipd_bin = cipd.GetCIPDFromCache()
    pkg_path = cipd.InstallPackage(cipd_bin, _ZSTD_PACKAGE, _ZSTD_VERSION)
    return str(pkg_path / "bin" / "pzstd")


def find_compressor(
    compression: CompressionType,
    chroot: Optional[Union[Path, str]] = None,
    root: Union[Path, str] = "/",
) -> str:
    """Locate a compressor utility program (possibly in a chroot).

    Since we compress/decompress a lot, make it easy to locate a
    suitable utility program in a variety of locations.  We favor
    the one in the chroot over /, and the parallel implementation
    over the single threaded one.

    Args:
        compression: The type of compression desired.
        chroot: Optional path to a chroot to search.
        root: Optional path to a root to search to override the default root.

    Returns:
        Path to a compressor.

    Raises:
        ValueError: If compression is unknown.
    """
    if compression == CompressionType.XZ:
        return str(constants.CHROMITE_SCRIPTS_DIR / "xz_auto")
    elif compression == CompressionType.GZIP:
        possible_progs = ["pigz", "gzip"]
    elif compression == CompressionType.BZIP2:
        possible_progs = ["lbzip2", "pbzip2", "bzip2"]
    elif compression == CompressionType.ZSTD:
        return _ensure_pzstd()
    elif compression == CompressionType.NONE:
        return "cat"
    else:
        raise ValueError("unknown compression")

    roots = []
    if chroot:
        roots.append(chroot)
    roots.append(root)

    for prog in possible_progs:
        for r in roots:
            for subdir in ["", "usr"]:
                path = os.path.join(r, subdir, "bin", prog)
                if os.path.exists(path):
                    return path

    return possible_progs[-1]


def compress_file(
    infile: Union[str, "os.PathLike[str]"],
    outfile: Union[str, "os.PathLike[str]"],
    compression_level: Optional[int] = None,
) -> cros_build_lib.CompletedProcess:
    """Compress a file using compressor specified by |outfile| suffix.

    Args:
        infile: File to compress.
        outfile: Name of output file. Compression used is based on the
            type of suffix of the name specified (e.g.: .bz2).
        compression_level: Optional compression level.
            Please use a level the target compression utility supports.
    """
    comp_type = CompressionType.from_extension(outfile)
    assert comp_type and comp_type != CompressionType.NONE
    comp = find_compressor(comp_type)
    cmd = [comp, "-c"]
    if compression_level is not None:
        cmd += [f"-{compression_level}"]
    cmd += ["--", infile]
    return cros_build_lib.run(cmd, stdout=outfile)


def decompress_file(
    infile: Union[str, "os.PathLike[str]"],
    outfile: Union[str, "os.PathLike[str]"],
) -> cros_build_lib.CompletedProcess:
    """Decompress a file using compressor specified by |infile| suffix.

    Args:
        infile: File to uncompress. Compression used is based on the
            type of suffix of the name specified (e.g.: .bz2).
        outfile: Name of output file.
    """
    comp_type = CompressionType.from_extension(infile)
    assert comp_type and comp_type != CompressionType.NONE
    comp = find_compressor(comp_type)
    return cros_build_lib.run([comp, "-dc", infile], stdout=outfile)


class TarballError(Exception):
    """Error while running tar.

    We may run tar multiple times because of "soft" errors.  The result is from
    the last run instance.
    """


@metrics_lib.timed("lib.compression_lib.create_tarball")
def create_tarball(
    tarball_path: Union[Path, int, str],
    cwd: Union[Path, str],
    sudo: Optional[bool] = False,
    compression: CompressionType = CompressionType.XZ,
    compressor: Optional[List[str]] = None,
    chroot: Optional[Union[Path, str]] = None,
    inputs: Optional[List[str]] = None,
    timeout: int = 300,
    extra_args: Optional[List[str]] = None,
    **kwargs: Any,
) -> cros_build_lib.CompletedProcess:
    """Create a tarball.  Executes 'tar' on the commandline.

    Args:
        tarball_path: The path of the tar file to generate. Can be file
            descriptor.
        cwd: The directory to run the tar command.
        sudo: Whether to run with "sudo".
        compression: The type of compression desired.  See the find_compressor
            function for details.
        compressor: Override |compression| options and use this tool.
        chroot: Optionally used for searching the compressor. See
            find_compressor().
        inputs: A list of files or directories relative to `cwd` to add to the
            tarball. If unset, defaults to ".".
        timeout: The number of seconds to wait on soft failure.
        extra_args: A list of extra args to pass to "tar".
        **kwargs: Any run options/overrides to use.

    Returns:
        The cmd_result object returned by the run invocation.

    Raises:
        TarballError: if the tar command failed, possibly after retry.
    """
    if inputs is None:
        inputs = ["."]

    if extra_args is None:
        extra_args = []
    debug_level = kwargs.setdefault("debug_level", logging.INFO)

    # Use a separate compression program - this enables parallel compression
    # in some cases.
    if compressor is None:
        compressor = [find_compressor(compression, chroot=chroot)]
    # Using 'raw' hole detection instead of 'seek' isn't that much slower, but
    # will provide much better results when archiving large disk images that are
    # not fully sparse.
    cmd = (
        ["tar"]
        + extra_args
        + [
            "--sparse",
            "--hole-detection=raw",
            "--use-compress-program",
            shell_util.cmd_to_str(compressor),
            "-c",
        ]
    )

    rc_stdout = None
    if isinstance(tarball_path, int):
        cmd += ["--to-stdout"]
        rc_stdout = tarball_path
    else:
        cmd += ["-f", str(tarball_path)]

    if len(inputs) > _THRESHOLD_TO_USE_T_FOR_TAR:
        # Since we log the command at debug_level, and the inputs would be
        # listed there if there were fewer, log the full list here.
        logging.log(
            debug_level, "tar inputs: %s", shell_util.cmd_to_str(inputs)
        )
        cmd += ["--null", "-T", "/dev/stdin"]
        rc_input = b"\0".join(x.encode("utf-8") for x in inputs)
    else:
        cmd += list(inputs)
        rc_input = None

    if sudo:
        rc_func = functools.partial(cros_build_lib.sudo_run, preserve_env=True)
    else:
        rc_func = cros_build_lib.run

    # If tar fails with status 1, retry twice. Once after timeout seconds and
    # again 2*timeout seconds after that.
    for try_count in range(3):
        try:
            result = rc_func(
                cmd,
                cwd=cwd,
                **dict(kwargs, check=False, input=rc_input, stdout=rc_stdout),
            )
        except cros_build_lib.RunCommandError as e:
            # There are cases where run never executes the command (cannot find
            # tar, cannot execute tar, such as when cwd does not exist).
            # Although the run command will show low-level problems, we also
            # want to log the context of what create_tarball was trying to do.
            logging.error(
                "create_tarball unable to run tar for %s in %s. cmd={%s}",
                tarball_path,
                cwd,
                cmd,
            )
            raise e
        if result.returncode == 0:
            return result
        if result.returncode != 1 or try_count > 1:
            # Since the build is abandoned at this point, we will take 5 entire
            # minutes to track down the competing process. Error will have the
            # low-level tar command error, so log the context of the tar command
            # (tarball_path file, current working dir).
            logging.error(
                "create_tarball failed creating %s in %s. cmd={%s}",
                tarball_path,
                cwd,
                cmd,
            )
            raise TarballError(
                f"Failed to create tarball ({result.returncode=})"
            )

        assert result.returncode == 1
        time.sleep(timeout * (try_count + 1))
        logging.warning(
            "create_tarball: tar: source modification time changed "
            "(see crbug.com/547055), retrying"
        )


def extract_tarball(
    tarball_path: Union[Path, str],
    install_path: Union[Path, str],
    files_to_extract: Optional[List[str]] = None,
    excluded_files: Optional[List[str]] = None,
    return_extracted_files: bool = False,
    sudo: Optional[bool] = False,
    replace_install_path: Optional[bool] = False,
) -> List[str]:
    """Extracts a tarball using tar.

    Detects whether the tarball is compressed or not based on the file
    extension and extracts the tarball into the install_path.

    Args:
        tarball_path: Path to the tarball to extract.
        install_path: Path to extract the tarball to.
        files_to_extract: String of specific files in the tarball to extract.
        excluded_files: String of files to not extract.
        return_extracted_files: whether the caller expects the list of files
            extracted; if False, returns an empty list.
        sudo: Whether to run with "sudo".
        replace_install_path: Try removing files and directory hierarchies in
            install_path before extracting over them.

    Returns:
        List of absolute paths of the files extracted (possibly empty).

    Raises:
        TarballError: if the tar command failed
    """
    # Use a separate decompression program - this enables parallel decompression
    # in some cases.
    cmd = [
        "tar",
        "--sparse",
        "-xf",
        str(tarball_path),
        "--directory",
        str(install_path),
    ]

    try:
        comp_type = CompressionType.detect_from_file(tarball_path)
    except FileNotFoundError as e:
        raise TarballError(f"File not found ({tarball_path=})") from e
    if comp_type == CompressionType.NONE:
        comp_type = CompressionType.from_extension(tarball_path)
    if comp_type != CompressionType.NONE:
        compressor = find_compressor(comp_type)
        cmd += ["--use-compress-program", shell_util.quote(compressor)]

    # If caller requires the list of extracted files, get verbose.
    if return_extracted_files:
        cmd += ["--verbose"]

    if replace_install_path:
        cmd += ["--overwrite-dir", "--recursive-unlink"]

    if excluded_files:
        for exclude in excluded_files:
            cmd.extend(["--exclude", exclude])

    if files_to_extract:
        cmd.extend(files_to_extract)

    if sudo:
        rc_func = functools.partial(cros_build_lib.sudo_run, preserve_env=True)
    else:
        rc_func = cros_build_lib.run

    try:
        result = rc_func(cmd, capture_output=True, encoding="utf-8")
    except cros_build_lib.RunCommandError as e:
        raise TarballError(
            "An error occurred when attempting to untar %s:\n%s"
            % (tarball_path, e)
        ) from e

    if result.returncode != 0:
        logging.error(
            "extract_tarball failed extracting %s. cmd={%s}", tarball_path, cmd
        )
        raise TarballError(f"Failed to extract tarball ({result.returncode=}")

    if return_extracted_files:
        return [
            os.path.join(install_path, filename)
            for filename in result.stdout.splitlines()
            if not filename.endswith("/")
        ]
    return []


def is_tarball(path: Union[Path, "os.PathLike[str]"]) -> bool:
    """Guess if this is a tarball based on the filename."""
    suffixes = Path(path).suffixes
    if not suffixes:
        return False

    if suffixes[-1] == ".tar":
        return True

    if len(suffixes) >= 2 and suffixes[-2] == ".tar":
        return suffixes[-1] in (".bz2", ".gz", ".xz", ".zst")

    return suffixes[-1] in (".tbz2", ".tbz", ".tgz", ".txz")
