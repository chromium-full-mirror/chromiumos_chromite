# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite main test runner.

Run the specified tests.  If none are specified, we'll scan the
tree looking for tests to run and then only run the semi-fast ones.

https://docs.pytest.org/en/latest/how-to/usage.html#specifying-which-tests-to-run

Examples:
# Run all tests in a module.
$ ./run_tests lib/osutils_unittest.py
# Run a class of tests in a module.
$ ./run_tests lib/osutils_unittest.py::TestOsutils
# Run a single test.
$ ./run_tests lib/osutils_unittest.py::TestOsutils::testIsSubPath

# Use -- to pass options down to pytest.
$ ./run_tests -- --help
# List all tests that'd be run.
$ ./run_tests -- --collect-only
# Run only the tests that failed last run.
$ ./run_tests -- --lf
"""

import logging
import os
import sys

import debugpy  # pylint: disable=import-error
import pytest  # pylint: disable=import-error

from chromite.api import compile_build_api_proto
from chromite.format import formatters
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import gs
from chromite.lib import namespaces
from chromite.lib import qemu
from chromite.lint import linters
from chromite.scripts import clang_format
from chromite.utils import shell_util


DEBUGGER_PORT = 5678


def main(argv) -> None:
    parser = get_parser()
    opts = parser.parse_args()
    opts.Freeze()

    pytest_args = opts.pytest_args

    if opts.chroot:
        ensure_chroot_exists()
        re_execute_inside_chroot(argv)
    else:
        pytest_args += ["--no-chroot"]

    if opts.network:
        pytest_args += ["-m", "not network_test or network_test"]

    if opts.precache:
        precache()

    if opts.quick:
        logging.info("Skipping test namespacing due to --quickstart.")
    elif opts.wait_for_debugger:
        # Namespacing renders the debugger TCP port inaccessible from outside.
        logging.info("Skipping test namespacing due to --wait-for-debugger.")
    else:
        # Namespacing is enabled by default because tests may break each other
        # or interfere with parts of the running system if not isolated in a
        # namespace. Disabling namespaces is not recommended for general use.
        namespaces.ReExecuteWithNamespace(
            [sys.argv[0], "--no-precache"] + argv, network=opts.network
        )

    jobs = opts.jobs

    if opts.pdb:
        jobs = 0
        pytest_args += ["--pdb"]

    if jobs is None:
        # Default to running in a single process under --quickstart or
        # --wait-for-debugger. User args can still override this. Cap it at 64
        # by default to prevent the overhead from spawning too many nodes.
        jobs = (
            0
            if opts.quick or opts.wait_for_debugger
            else min(os.cpu_count(), 64)
        )
    pytest_args = ["-n", str(jobs)] + pytest_args

    # Check the environment.  https://crbug.com/1015450
    st = os.stat("/")
    if st.st_mode & 0o007 != 0o005:
        cros_build_lib.Die(
            f"The root directory has broken permissions: {st.st_mode:o}\n"
            "Fix with: sudo chmod o+rx-w /"
        )
    if st.st_uid or st.st_gid:
        cros_build_lib.Die(
            f"The root directory has broken ownership: {st.st_uid}:{st.st_gid}"
            " (should be 0:0)\nFix with: sudo chown 0:0 /"
        )

    if opts.wait_for_debugger:
        # Breakpoints can be set using the breakpoint() built-in function.
        # Restricting the test runner to a single test case or _unittest.py
        # file is recommended.
        logging.notice(
            f"Waiting for a debugger to connect to port {DEBUGGER_PORT}..."
        )
        debugpy.listen(("localhost", DEBUGGER_PORT))
        debugpy.wait_for_client()
        logging.notice("Debugger connected.")

    logging.debug("Running: pytest %s", shell_util.cmd_to_str(pytest_args))
    sys.exit(pytest.main(pytest_args))


def precache() -> None:
    """Do some network-dependent stuff before we disallow network access."""
    # pylint: disable=protected-access
    logging.notice("Caching tools from network (cipd/vpython/etc...)")

    # This is a cheesy hack to make sure gsutil is populated in the cache before
    # we run tests. This is a partial workaround for crbug.com/468838.
    gs.GSContext.InitializeCache()
    # Ensure protoc is installed for api/compile_build_api_proto_unittest.
    compile_build_api_proto.InstallProtoc(
        compile_build_api_proto.ProtocVersion.CHROMITE
    )
    # Ensure various tools are available.
    cros_build_lib.dbg_run(
        [constants.CHROMITE_DIR / "scripts" / "black", "--version"],
        capture_output=True,
    )
    cros_build_lib.dbg_run(
        [constants.CHROMITE_DIR / "scripts" / "isort", "--version"],
        capture_output=True,
    )
    formatters.gn._find_gn()
    formatters.star._find_buildifier()
    formatters.textproto._find_txtpbfmt()
    linters.shell._find_shellcheck()
    qemu.InstallFromCipd()
    with clang_format.ClangFormat():
        pass


def re_execute_inside_chroot(argv) -> None:
    """Re-execute the test wrapper inside the chroot."""
    if cros_build_lib.IsInsideChroot():
        return

    target = constants.CHROMITE_DIR / "scripts" / "run_tests"
    relpath = os.path.relpath(target, ".")
    # If we're in the scripts dir, make sure we always have a relative path,
    # otherwise cros_sdk will search $PATH and fail.
    if os.path.sep not in relpath:
        relpath = os.path.join(".", relpath)
    cmd = [
        "cros_sdk",
        "--working-dir",
        ".",
        "--",
        relpath,
    ]
    os.execvp(cmd[0], cmd + argv)


def ensure_chroot_exists() -> None:
    """Ensure that a chroot exists for us to run tests in."""
    chroot = os.path.join(constants.SOURCE_ROOT, constants.DEFAULT_CHROOT_DIR)
    if not os.path.exists(chroot) and not cros_build_lib.IsInsideChroot():
        cros_build_lib.run(["cros_sdk", "--create"])


def get_parser():
    """Build the parser for command line arguments."""
    parser = commandline.ArgumentParser(
        description=__doc__,
        epilog="To see the help output for pytest:\n$ %(prog)s -- --help",
        default_log_level="notice",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of tests to run in parallel.",
    )
    parser.add_argument(
        "--pdb",
        action="store_true",
        help="Automatically enable Python debugger on failure (implies -j0).",
    )
    parser.add_argument(
        "--wait-for-debugger",
        action="store_true",
        help=(
            f"Wait for a debugger to connect to port {DEBUGGER_PORT} (implies "
            "--quickstart)."
        ),
    )
    parser.add_argument(
        "--quickstart",
        dest="quick",
        action="store_true",
        help=(
            "Skip normal test sandboxing and namespacing for faster start up "
            "time."
        ),
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Include network tests.",
    )
    parser.add_bool_argument(
        "--precache",
        True,
        "Cache packages from the network before running tests.",
        "Skip precaching packages from the network.",
    )
    parser.add_argument(
        "--no-chroot",
        dest="chroot",
        action="store_false",
        help=(
            "Don't initialize or enter a chroot for the test invocation. May "
            "cause tests to unexpectedly fail!"
        ),
    )
    parser.add_argument(
        "pytest_args",
        metavar="pytest arguments",
        nargs="*",
        help="Arguments to pass down to pytest (use -- to help separate)",
    )
    return parser
