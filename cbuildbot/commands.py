# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the various individual commands a builder can run."""

import fnmatch
import os

from chromite.lib import compression_lib
from chromite.lib import cros_build_lib
from chromite.lib import path_util


# Filename for tarball containing Autotest server files needed for Server-Side
# Packaging.
AUTOTEST_SERVER_PACKAGE = "autotest_server_package.tar.bz2"

# Directory within AUTOTEST_SERVER_PACKAGE where Tast files needed to run with
# Server-Side Packaging are stored.
_TAST_SSP_SUBDIR = "tast"

# Tast files and directories to include in AUTOTEST_SERVER_PACKAGE relative to
# the build root. Public so it can be used by commands_unittest.py.
TAST_SSP_CHROOT_FILES = [
    "chroot/etc/tast/vars",  # Secret variables tast interprets.
    "chroot/usr/bin/remote_test_runner",  # Runs remote tests.
    "chroot/usr/bin/tast",  # Main Tast executable.
    "chroot/usr/libexec/tast/bundles",  # Dir containing test bundles.
    "chroot/usr/share/tast/data",  # Dir containing test data.
    "src/platform/tast/tools/run_tast.sh",  # Helper script to run SSP tast.
]

# =========================== Main Commands ===================================


def _BuildTarball(
    buildroot, input_list, tarball_path, cwd=None, compressed=True, **kwargs
):
    """Tars and zips files and directories from input_list to tarball_path.

    Args:
        buildroot: Root directory where build occurs.
        input_list: A list of files and directories to be archived.
        tarball_path: Path of output tar archive file.
        cwd: Current working directory when tar command is executed.
        compressed: Whether or not the tarball should be compressed with pbzip2.
        **kwargs: Keyword arguments to pass to create_tarball.

    Returns:
        Return value of compression_lib.create_tarball.
    """
    compressor = compression_lib.CompressionType.NONE
    chroot = None
    if compressed:
        compressor = compression_lib.CompressionType.BZIP2
        chroot = os.path.join(buildroot, "chroot")
    return compression_lib.create_tarball(
        tarball_path,
        cwd,
        compression=compressor,
        chroot=chroot,
        inputs=input_list,
        **kwargs,
    )


def _FindFilesWithPattern(pattern, target="./", cwd=os.curdir, exclude_dirs=()):
    """Search the root directory recursively for matching filenames.

    Args:
        pattern: the pattern used to match the filenames.
        target: the target directory to search.
        cwd: current working directory.
        exclude_dirs: Directories to not include when searching.

    Returns:
        A list of paths of the matched files.
    """
    # Backup the current working directory before changing it
    old_cwd = os.getcwd()
    os.chdir(cwd)

    matches = []
    for root, _, filenames in os.walk(target):
        if not any(root.startswith(e) for e in exclude_dirs):
            for filename in fnmatch.filter(filenames, pattern):
                matches.append(os.path.join(root, filename))

    # Restore the working directory
    os.chdir(old_cwd)

    return matches


def _BuildAutotestControlFilesTarball(buildroot, cwd, tarball_dir):
    """Tar up the autotest control files.

    Args:
        buildroot: Root directory where build occurs.
        cwd: Current working directory.
        tarball_dir: Location for storing autotest tarball.

    Returns:
        Path of the partial autotest control files tarball.
    """
    # Find the control files in autotest/
    control_files = _FindFilesWithPattern(
        "control*",
        target="autotest",
        cwd=cwd,
        exclude_dirs=["autotest/test_suites"],
    )
    control_files_tarball = os.path.join(tarball_dir, "control_files.tar")
    _BuildTarball(
        buildroot,
        control_files,
        control_files_tarball,
        cwd=cwd,
        compressed=False,
    )
    return control_files_tarball


def _BuildAutotestPackagesTarball(buildroot, cwd, tarball_dir):
    """Tar up the autotest packages.

    Args:
        buildroot: Root directory where build occurs.
        cwd: Current working directory.
        tarball_dir: Location for storing autotest tarball.

    Returns:
        Path of the partial autotest packages tarball.
    """
    input_list = ["autotest/packages"]
    packages_tarball = os.path.join(tarball_dir, "autotest_packages.tar")
    _BuildTarball(
        buildroot, input_list, packages_tarball, cwd=cwd, compressed=False
    )
    return packages_tarball


def _BuildAutotestTestSuitesTarball(buildroot, cwd, tarball_dir):
    """Tar up the autotest test suite control files.

    Args:
        buildroot: Root directory where build occurs.
        cwd: Current working directory.
        tarball_dir: Location for storing autotest tarball.

    Returns:
        Path of the autotest test suites tarball.
    """
    test_suites_tarball = os.path.join(tarball_dir, "test_suites.tar.bz2")
    _BuildTarball(
        buildroot, ["autotest/test_suites"], test_suites_tarball, cwd=cwd
    )
    return test_suites_tarball


def _BuildAutotestServerPackageTarball(buildroot, cwd, tarball_dir):
    """Tar up the autotest files required by the server package.

    Args:
        buildroot: Root directory where build occurs.
        cwd: Current working directory.
        tarball_dir: Location for storing autotest tarballs.

    Returns:
        The path of the autotest server package tarball.
    """
    # Find all files in autotest excluding certain directories.
    autotest_files = _FindFilesWithPattern(
        "*",
        target="autotest",
        cwd=cwd,
        exclude_dirs=(
            "autotest/packages",
            "autotest/client/deps/",
            "autotest/client/tests",
            "autotest/client/site_tests",
        ),
    )

    tast_files, transforms = _GetTastServerFilesAndTarTransforms(buildroot)

    tarball = os.path.join(tarball_dir, AUTOTEST_SERVER_PACKAGE)
    _BuildTarball(
        buildroot,
        autotest_files + tast_files,
        tarball,
        cwd=cwd,
        extra_args=transforms,
        check=False,
    )
    return tarball


def _GetTastServerFilesAndTarTransforms(buildroot):
    """Returns Tast server files and corresponding tar transform flags.

    The returned paths should be included in AUTOTEST_SERVER_PACKAGE. The
    --transform arguments should be passed to GNU tar to convert the paths to
    appropriate destinations in the tarball.

    Args:
        buildroot: Absolute path to root build directory.

    Returns:
        (files, transforms), where files is a list of absolute paths to Tast
        server files/directories and transforms is a list of --transform
        arguments to pass to GNU tar when archiving those files.
    """
    files = []
    transforms = []

    for p in TAST_SSP_CHROOT_FILES:
        path = path_util.FromChrootPath(
            p,
            source_path=buildroot,
        )
        if os.path.exists(path):
            files.append(path)
            dest = os.path.join(_TAST_SSP_SUBDIR, os.path.basename(path))
            transforms.append(
                "--transform=s|^%s|%s|" % (os.path.relpath(path, "/"), dest)
            )

    return files, transforms


def BuildAutotestTarballsForHWTest(buildroot, cwd, tarball_dir):
    """Generate the "usual" autotest tarballs required for running HWTests.

    These tarballs are created in multiple places wherever they need to be
    staged for running HWTests.

    Args:
        buildroot: Root directory where build occurs.
        cwd: Current working directory.
        tarball_dir: Location for storing autotest tarballs.

    Returns:
        A list of paths of the generated tarballs.

    TODO(crbug.com/924655): Has been ported to a build API endpoint. Remove this
    function and any unused child functions when the stages have been updated to
    use the API call.
    """
    return [
        _BuildAutotestControlFilesTarball(buildroot, cwd, tarball_dir),
        _BuildAutotestPackagesTarball(buildroot, cwd, tarball_dir),
        _BuildAutotestTestSuitesTarball(buildroot, cwd, tarball_dir),
        _BuildAutotestServerPackageTarball(buildroot, cwd, tarball_dir),
    ]


class ChromeSDK:
    """Wrapper for the 'cros chrome-sdk' command."""

    def __init__(
        self,
        cwd,
        board,
        extra_args=None,
        chrome_src=None,
        debug_log=True,
        cache_dir=None,
        target_tc=None,
        toolchain_url=None,
    ) -> None:
        """Initialization.

        Args:
            cwd: Where to invoke 'cros chrome-sdk'.
            board: The board to run chrome-sdk for.
            extra_args: Extra args to pass in on the command line.
            chrome_src: Path to pass in with --chrome-src.
            debug_log: If set, run with debug log-level.
            cache_dir: Specify non-default cache directory.
            target_tc: Override target toolchain.
            toolchain_url: Override toolchain url pattern.
        """
        self.cwd = cwd
        self.board = board
        self.extra_args = extra_args or []
        if chrome_src:
            self.extra_args += ["--chrome-src", chrome_src]
        self.debug_log = debug_log
        self.cache_dir = cache_dir
        self.target_tc = target_tc
        self.toolchain_url = toolchain_url

    def Run(self, cmd, extra_args=None, run_args=None):
        """Run a command inside the chrome-sdk context.

        Args:
            cmd: Command (list) to run inside 'cros chrome-sdk'.
            extra_args: Extra arguments for 'cros chorme-sdk'.
            run_args: If set (dict), pass to run as kwargs.

        Returns:
            A CompletedProcess object.
        """
        if run_args is None:
            run_args = {}
        cros_cmd = ["cros"]
        if self.debug_log:
            cros_cmd += ["--log-level", "debug"]
        if self.cache_dir:
            cros_cmd += ["--cache-dir", self.cache_dir]
        if self.target_tc:
            self.extra_args += ["--target-tc", self.target_tc]
        if self.toolchain_url:
            self.extra_args += ["--toolchain-url", self.toolchain_url]
        cros_cmd += ["chrome-sdk", "--board", self.board] + self.extra_args
        cros_cmd += (extra_args or []) + ["--"] + cmd
        return cros_build_lib.run(cros_cmd, cwd=self.cwd, **run_args)

    def Ninja(self, debug=False, run_args=None):
        """Run 'ninja' inside a chrome-sdk context.

        Args:
            debug: Whether to do a Debug build (defaults to Release).
            run_args: If set (dict), pass to run as kwargs.

        Returns:
            A CompletedProcess object.
        """
        return self.Run(self.GetNinjaCommand(debug=debug), run_args=run_args)

    def GetNinjaCommand(self, debug=False):
        """Returns a command line to run "ninja".

        Args:
            debug: Whether to do a Debug build (defaults to Release).

        Returns:
            Command line to run "ninja".
        """
        cmd = ["autoninja"]
        cmd += [
            "-C",
            self._GetOutDirectory(debug=debug),
            "chromiumos_preflight",
        ]
        return cmd

    def VMTest(self, image_path, debug=False):
        """Run cros_run_test in a VM.

        Only run tests for boards where we build a VM.

        Args:
            image_path: VM image path.
            debug: True if this is a debug build.

        Returns:
            A CompletedProcess object.
        """
        return self.Run(
            [
                "cros_run_test",
                "--copy-on-write",
                "--deploy",
                "--board=%s" % self.board,
                "--image-path=%s" % image_path,
                "--build-dir=%s" % self._GetOutDirectory(debug=debug),
            ]
        )

    def _GetOutDirectory(self, debug=False):
        """Returns the path to the output directory.

        Args:
            debug: Whether to do a Debug build (defaults to Release).

        Returns:
            Path to the output directory.
        """
        flavor = "Debug" if debug else "Release"
        return "out_%s/%s" % (self.board, flavor)
