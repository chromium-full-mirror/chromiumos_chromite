# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utilities for updating and building in the chroot environment."""

import os
from pathlib import Path
from typing import Dict, List, Optional, Set, Union

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
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


def _SetUpTestPortageConfig(
    tempdir: Path, sysroot: Path, packages: Set[str]
) -> None:
    """Sets up a temporary PORTAGE_CONFIGROOT directory structure.

    This allows us to isolate FEATURES configuration for the test run without
    modifying the sysroot configuration directly.
    """
    # Ensure it is readable by portage (dropped privileges).
    tempdir.chmod(0o755)

    etc_dir = tempdir / "etc"
    portage_dir = etc_dir / "portage"
    env_dir = portage_dir / "env"

    env_dir.mkdir(parents=True, exist_ok=True)

    # Symlink make.conf files from sysroot.
    sysroot_etc = sysroot / "etc"
    for p in sysroot_etc.glob("make.conf*"):
        (etc_dir / p.name).symlink_to(p)

    # Symlink portage files from sysroot.
    sysroot_portage = sysroot_etc / "portage"
    for p in sysroot_portage.iterdir():
        if p.name in ("env", "package.env"):
            continue
        (portage_dir / p.name).symlink_to(p)

    # Symlink existing env files from sysroot.
    sysroot_env = sysroot_portage / "env"
    if sysroot_env.is_dir():
        for p in sysroot_env.glob("*"):
            if p.name not in ("no_tests.env", "enable_tests.env"):
                (env_dir / p.name).symlink_to(p)

    # Write env files.
    # We want to run tests ONLY for the packages we explicitly target.
    # If we pass FEATURES=test in the environment, it overrides all config files
    # and forces tests for all dependencies (which often fail to run due to
    # architecture mismatch when cross-compiling).
    # By NOT setting FEATURES=test in the environment, we can use package.env
    # to selectively enable it.
    # Portage processes package.env matching lines in order.
    # 1. We map '*/*' to 'no_tests.env' to disable tests for all packages
    #    (including dependencies).
    # 2. We map our target packages to 'enable_tests.env' to enable tests
    #    for them.
    # Since the target package rules are more specific and processed after
    # the wildcard, they override the wildcard rule.
    osutils.WriteFile(env_dir / "no_tests.env", 'FEATURES="-test"\n')
    osutils.WriteFile(env_dir / "enable_tests.env", 'FEATURES="test"\n')

    # Write package.env.
    package_env_lines = []
    sysroot_package_env = sysroot_portage / "package.env"
    if sysroot_package_env.is_file():
        content = sysroot_package_env.read_text(encoding="utf-8")
        package_env_lines.append(content.rstrip() + "\n")
    elif sysroot_package_env.is_dir():
        for p in sorted(sysroot_package_env.iterdir()):
            if p.is_file():
                content = p.read_text(encoding="utf-8")
                package_env_lines.append(content.rstrip() + "\n")

    package_env_lines.append("*/* no_tests.env\n")
    package_env_lines.extend(
        f"{x} enable_tests.env\n" for x in sorted(packages)
    )
    osutils.WriteFile(portage_dir / "package.env", "".join(package_env_lines))


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

    # Set up a temporary PORTAGE_CONFIGROOT to manage FEATURES=test without
    # modifying the sysroot config directly, and to avoid running tests for
    # dependencies.
    with osutils.TempDir() as tempdir:
        tempdir_path = Path(tempdir)
        _SetUpTestPortageConfig(tempdir_path, Path(sysroot), packages)
        env["PORTAGE_CONFIGROOT"] = str(tempdir_path)
        env["SYSROOT"] = sysroot

        cros_build_lib.sudo_run(command, extra_env=env)
