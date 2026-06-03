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

import contextlib
import logging
import os
import subprocess
import sys

import debugpy  # pylint: disable=import-error
import pytest  # pylint: disable=import-error

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import ensure_bootstrap
from chromite.lib import namespaces
from chromite.utils import shell_util


DEBUGGER_PORT = 5678


def main(argv) -> None:
    parser = get_parser()
    opts = parser.parse_args()
    if opts.typing is None:
        opts.typing = not opts.pytest_args
        if opts.pytest_args:
            logging.info("Skipping type checking due to custom test args")
    opts.freeze()

    pytest_args = opts.pytest_args

    if opts.chroot:
        ensure_chroot_exists()
        re_execute_inside_chroot(argv)
    else:
        pytest_args += ["--no-chroot"]

    if opts.network:
        pytest_args += ["-m", "not network_test or network_test"]

    if opts.precache:
        logging.notice("Caching tools from network (cipd/vpython/etc...)")
        ensure_bootstrap.for_everything()

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
        cros_build_lib.die(
            f"The root directory has broken permissions: {st.st_mode:o}\n"
            "Fix with: sudo chmod o+rx-w /"
        )
    if st.st_uid or st.st_gid:
        cros_build_lib.die(
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

    with contextlib.ExitStack() as stack:
        # If the user is running custom pytest stuff, like specific tests,
        # don't run the typing logic too.
        if not opts.typing:
            typing_proc = None
        else:
            # Launch type checking in parallel with pytest.
            cmd = [constants.CHROMITE_SCRIPTS_DIR / "run_typing"]
            logging.debug(
                "Running: %s in %s",
                shell_util.cmd_to_str(cmd),
                constants.CHROMITE_DIR,
            )
            typing_proc = stack.enter_context(
                subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    encoding="utf-8",
                    cwd=constants.CHROMITE_DIR,
                )
            )

        logging.debug("Running: pytest %s", shell_util.cmd_to_str(pytest_args))
        returncode = pytest.main(pytest_args)

        if typing_proc is not None:
            # Typing should be finished by now, so collect the results.
            stdout = typing_proc.communicate()[0].strip()
            if stdout:
                logging.notice("Python type checking results (KI ignored):")
                print(stdout)
            if returncode == 0:
                # If unittests already failed, no need to check typing.
                returncode = typing_proc.returncode

    sys.exit(returncode)


def re_execute_inside_chroot(argv) -> None:
    """Re-execute the test wrapper inside the chroot."""
    if cros_build_lib.IsInsideChroot():
        return

    target = constants.CHROMITE_SCRIPTS_DIR / "run_tests"
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
    parser.add_bool_argument(
        "--chroot",
        True,
        "Run all tests inside of the SDK for hermetic runtime.",
        "Do not initialize or attempt to enter the SDK for tests.",
    )
    parser.add_bool_argument(
        "--typing",
        None,
        "Run codebase through type checking.",
        "Do not type check the codebase.",
    )
    parser.add_argument(
        "pytest_args",
        metavar="pytest arguments",
        nargs="*",
        help="Arguments to pass down to pytest (use -- to help separate)",
    )
    return parser
