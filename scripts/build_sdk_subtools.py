# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""build_sdk_subtools rebuilds binary packages exported by the subtools builder.

The build_sdk_subtools process takes (copies) an amd64-host base SDK, compiles
and installs additional packages needed by subtools, then creates relocatable
binary subtool bundles that can be consumed by other build hosts and developer
machines.

If build_sdk_subtools has already been invoked for the provided chroot, all
non-toolchain packages in the subtools deptree that have updated revisions or
changed USE flags will be rebuilt, along with reverse dependencies.

Packages (e.g. an ebuild) provide manifests that describes how files, once
installed, are to be bundled and exported.

If packages are specified in the command line, only consider the deptree from
those specific packages rather than all of virtual/target-sdk-subtools.
"""

import argparse
import logging
import os
from pathlib import Path
import sys
from typing import List, Optional, Protocol

from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import sysroot_lib
from chromite.service import sdk_subtools


assert sys.version_info >= (3, 8), "build_sdk_subtools uses Python 3.8 features"


# Affects where building occurs (e.g. /build/amd64-subtools-host) if not
# overridden by --output-dir. Note this will be a chroot.
SUBTOOLS_OUTPUT_DIR = "amd64-subtools-host"

# Flag passed to subprocesses in chroots that might not yet be set up as a
# subtools chroot.
_RELAUNCH_FOR_SETUP_FLAG = "--relaunch-for-setup"

# Used to populate a test manifest in /etc/cros/standalone-packages.d/.
# Ebuilds will later be updated to provide these files instead.
_TEST_PACKAGE = (
    sdk_subtools.SUBTOOLS_EXPORTS_CONFIG_DIR / "shellcheck.textproto"
)
_TEST_PACKAGE_CONTENTS = """\
# proto-file: chromiumos/build/api/subtools.proto
# proto-message: chromiumos.build.api.SubtoolPackage
name: "shellcheck"
type: EXPORT_CIPD
max_files: 2
paths: [{
    input: "/usr/bin/shellcheck"
},{
    input: "/usr/share/doc/*/LICENSE.gz"
    ebuild_filter: "dev-util/shellcheck"
}]
"""


class Options(Protocol):
    """Protocol to formalize commandline arguments."""

    clean: bool
    setup_chroot: bool
    update_packages: bool
    relaunch_for_setup: bool
    output_dir: Path
    packages: List[str]
    jobs: int

    def Freeze(self) -> None:
        pass


def get_parser() -> commandline.ArgumentParser:
    """Returns the cmdline argparser, populates the options and descriptions."""
    parser = commandline.ArgumentParser(description=__doc__)

    parser.add_bool_argument(
        "--clean",
        False,
        "Remove the subtools chroot and re-extract the SDK.",
        "Re-use an existing subtools chroot.",
    )

    parser.add_bool_argument(
        "--setup-chroot",
        True,
        "Look for a newer base SDK and set it up as a subtools SDK.",
        "Don't look for a newer base SDK and assume the chroot is setup.",
    )

    parser.add_bool_argument(
        "--update-packages",
        True,
        "Update and install packages before looking for things to export.",
        "Only export packages already installed in the subtools SDK.",
    )

    parser.add_argument(
        "--output-dir",
        type=osutils.ExpandPath,
        metavar="PATH",
        help=f"Extract SDK and build in chroot (e.g. {SUBTOOLS_OUTPUT_DIR}).",
    )

    parser.add_argument(
        "packages",
        nargs="*",
        default=["virtual/target-sdk-subtools"],
        help="Packages to build before looking for export candidates.",
    )

    parser.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=os.cpu_count(),
        help="Number of packages to build in parallel. (Default: %(default)s)",
    )

    parser.add_argument(
        _RELAUNCH_FOR_SETUP_FLAG,
        action="store_true",
        default=False,
        help=argparse.SUPPRESS,
    )

    # TODO(b/277992359): Consider possibly relevant flags from build_packages:
    #  * --rebuild_revdeps=no: don't rebuild reverse dependencies.
    #  * --skip-toolchain-update? Likely no - the SDK is our toolchain.
    #  * --withdebugsymbols
    #  * --rebuild=no "Automatically rebuild dependencies"
    #  * --backtrack
    #  * --bazel  "Use Bazel to build packages"

    return parser


def parse_args(argv: Optional[List[str]]) -> Options:
    """Parse and validate CLI arguments."""

    parser = get_parser()
    opts: Options = parser.parse_args(argv)
    opts.Freeze()
    return opts


def _setup_base_sdk(
    build_target: build_target_lib.BuildTarget,
    setup_chroot: bool,
) -> None:
    """SetupBoard workalike that converts a regular SDK into a subtools chroot.

    Runs inside the /build/amd64-subtools-host subtools SDK chroot.
    """
    cros_build_lib.AssertInsideChroot()
    cros_build_lib.AssertRootUser()

    sdk_subtools.setup_base_sdk(build_target, setup_chroot)

    if setup_chroot:
        _TEST_PACKAGE.write_text(_TEST_PACKAGE_CONTENTS, encoding="utf-8")


def _run_inside_subtools_chroot(opts: Options) -> None:
    """Steps that build_sdk_subtools performs once it is in its chroot."""
    if opts.update_packages:
        try:
            sdk_subtools.update_packages(opts.packages, opts.jobs)
        except sysroot_lib.PackageInstallError as e:
            cros_build_lib.Die(e)

    sdk_subtools.bundle_and_export()


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    opts = parse_args(argv)
    return build_sdk_subtools(opts, argv if argv else [])


def build_sdk_subtools(opts: Options, argv: List[str]) -> int:
    """Executes SDK subtools builder steps according to `opts`."""
    # BuildTarget needs a str, but opts.output_dir is osutils.ExpandPath.
    custom_output_dir = str(opts.output_dir) if opts.output_dir else None
    build_target = build_target_lib.BuildTarget(
        name=SUBTOOLS_OUTPUT_DIR, build_root=custom_output_dir
    )

    # If the process is in the subtools chroot, we must assume it's already set
    # up (we are in it). So start building.
    if sdk_subtools.is_inside_subtools_chroot() and not opts.relaunch_for_setup:
        _run_inside_subtools_chroot(opts)
        return 0

    # Otherwise, we have the option to set it up. Then restart inside it. The
    # setup runs `cros_sdk` to get a base SDK, creates an SDK subprocess to set
    # it up as a subtools SDK, then restarts inside the subtools SDK.
    if cros_build_lib.IsInsideChroot():
        if opts.relaunch_for_setup:
            # This is the subprocess of the not-in-chroot path used to convert
            # the base SDK to a subtools SDK (within the chroot).
            _setup_base_sdk(build_target, opts.setup_chroot)
            return 0
        else:
            cros_build_lib.Die(
                "build_sdk_subtools must be run outside the chroot."
            )

    logging.info("Initializing subtools builder in %s", build_target.root)
    subtools_chroot = os.path.join(
        constants.DEFAULT_CHROOT_PATH, build_target.root.lstrip("/")
    )
    chroot_args = ["--chroot", subtools_chroot]

    if opts.setup_chroot:
        # Get an SDK. TODO(b/277992359):
        #   - Fetch an SDK version pinned by pupr rather than the default.
        #   - Should this use cros_sdk_lib directly?

        # Pass "--skip-chroot-upgrade": the SDK should initially be used
        # "as-is", but later steps may upgrade packages in the subtools deptree.
        cros_sdk_args = ["--create", "--skip-chroot-upgrade"]
        cros_sdk_args += ["--delete"] if opts.clean else []
        cros_sdk = cros_build_lib.run(
            ["cros_sdk"] + chroot_args + cros_sdk_args,
            check=False,
            cwd=constants.SOURCE_ROOT,
        )
        if cros_sdk.returncode != 0:
            return cros_sdk.returncode

        # Invoke `_setup_base_sdk()` inside the SDK.
        setup_base_sdk = cros_build_lib.sudo_run(
            ["build_sdk_subtools"] + argv + [_RELAUNCH_FOR_SETUP_FLAG],
            check=False,
            enter_chroot=True,
            chroot_args=chroot_args,
            cwd=constants.SOURCE_ROOT,
        )
        if setup_base_sdk.returncode != 0:
            return setup_base_sdk.returncode

    raise commandline.ChrootRequiredError(
        ["build_sdk_subtools"] + argv, chroot_args=chroot_args
    )
