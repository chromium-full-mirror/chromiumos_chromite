# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for updating and building in the chroot environment."""

import os
from typing import Dict, List, Optional, Set, Union

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import sysroot_lib
from chromite.lib.telemetry import trace


if cros_build_lib.IsInsideChroot():
    # These import libraries outside chromite.
    from chromite.scripts import cros_list_modified_packages as workon
    from chromite.scripts import cros_setup_toolchains as toolchain


tracer = trace.get_tracer(__name__)


def _GetToolchainPackages() -> List[str]:
    """Get a list of host toolchain packages."""
    # Load crossdev cache first for faster performance.
    toolchain.Crossdev.Load(False)
    packages = toolchain.GetTargetPackages("host")
    return [toolchain.GetPortagePackage("host", x) for x in packages]


def GetEmergeCommand(
    sysroot: Optional[str] = None,
) -> List[Union[str, "os.PathLike[str]"]]:
    """Returns the emerge command to use for |sysroot| (host if None)."""
    cmd: List[Union[str, "os.PathLike[str]"]] = [
        constants.CHROMITE_BIN_DIR / "parallel_emerge"
    ]
    if sysroot and sysroot != "/":
        cmd.append(f"--sysroot={sysroot}")
    return cmd


@tracer.start_as_current_span("chroot_util.Emerge")
def Emerge(
    packages: List[str],
    sysroot: str,
    with_deps: bool = True,
    rebuild_deps: bool = True,
    use_binary: bool = True,
    jobs: int = 0,
    debug_output: bool = False,
) -> None:
    """Emerge the specified |packages|.

    Args:
        packages: List of packages to emerge.
        sysroot: Path to the sysroot in which to emerge.
        with_deps: Whether to include dependencies.
        rebuild_deps: Whether to rebuild dependencies.
        use_binary: Whether to use binary packages.
        jobs: Number of jobs to run in parallel.
        debug_output: Emit debug level output.

    Raises:
        cros_build_lib.RunCommandError: If emerge returns an error.
    """
    cros_build_lib.AssertInsideChroot()

    span = trace.get_current_span()
    span.set_attributes(
        {
            "sysroot": sysroot,
            "packages": packages,
            "with_deps": with_deps,
            "rebuild_deps": rebuild_deps,
            "use_binary": use_binary,
            "jobs": jobs,
        }
    )

    if not packages:
        raise ValueError("No packages provided")

    cmd = GetEmergeCommand(sysroot)
    cmd.append("-uNv")

    modified_packages = workon.ListModifiedWorkonPackages(
        sysroot_lib.Sysroot(sysroot)
    )
    if modified_packages is not None:
        mod_pkg_list = " ".join(modified_packages)
        cmd += [
            "--reinstall-atoms=" + mod_pkg_list,
            "--usepkg-exclude=" + mod_pkg_list,
        ]

    cmd.append("--deep" if with_deps else "--nodeps")
    if use_binary:
        cmd += ["-g", "--with-bdeps=y"]
        if sysroot == "/":
            # Only update toolchains in the chroot when binpkgs are available.
            # The toolchain rollout process only takes place when the chromiumos
            # sdk builder finishes a successful build and pushes out binpkgs.
            cmd += ["--useoldpkg-atoms=%s" % " ".join(_GetToolchainPackages())]

    if rebuild_deps:
        cmd.append("--rebuild-if-unbuilt")
    if jobs:
        cmd.append(f"--jobs={jobs}")
    if debug_output:
        cmd.append("--show-output")

    # We might build chrome, in which case we need to pass 'CHROME_ORIGIN'.
    cros_build_lib.sudo_run(cmd + packages, preserve_env=True)


@tracer.start_as_current_span("chroot_util.RunUnittests")
def RunUnittests(
    sysroot: str,
    packages: Set[str],
    extra_env: Optional[Dict[str, str]] = None,
    keep_going: bool = False,
    verbose: bool = False,
    jobs: int = 0,
) -> None:
    """Runs the unit tests for |packages|.

    Args:
        sysroot: Path to the sysroot to build the tests in.
        packages: List of packages to test.
        extra_env: Python dictionary containing the extra environment variable
            to pass to the build command.
        keep_going: Tolerate package failure from parallel_emerge.
        verbose: If True, show the output from emerge, even when the tests
            succeed.
        jobs: Max number of parallel jobs. (optional)

    Raises:
        RunCommandError if the unit tests failed.
    """
    span = trace.get_current_span()
    span.set_attributes(
        {
            "sysroot": sysroot,
            "packages": list(packages),
            "keep_going": keep_going,
            "jobs": jobs,
        }
    )

    env = extra_env.copy() if extra_env else {}

    if "FEATURES" in env:
        env["FEATURES"] += " test"
    else:
        env["FEATURES"] = "test"

    env["PKGDIR"] = os.path.join(sysroot, constants.UNITTEST_PKG_PATH)

    command = [
        constants.CHROMITE_BIN_DIR / "parallel_emerge",
        "--sysroot=%s" % sysroot,
    ]

    if keep_going:
        command += ["--keep-going=y"]

    if verbose:
        command += ["--show-output"]
        command += ["--verbose"]

    if jobs:
        command += [f"--jobs={jobs}"]

    command += list(packages)

    cros_build_lib.sudo_run(command, extra_env=env)
