# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros build-packages updates the set of binary packages needed by ChromiumOS.

The build-packages process cross compiles all packages that have been
updated into the given sysroot and builds binary packages as a side-effect.
The output packages will be used by `cros build-image` to create a bootable
ChromiumOS image.

If packages are specified in the command line, only build those specific
packages and any dependencies they might need.
"""

import argparse
import logging
import os
import urllib.error
import urllib.request

from chromite.cli import command
from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import sysroot_lib
from chromite.lib.telemetry import trace
from chromite.service import sysroot
from chromite.utils import timer


tracer = trace.get_tracer(__name__)


@command.command_decorator("build-packages")
class BuildPackagesCommand(command.CliCommand):
    """Update the set of binary packages used by ChromiumOS."""

    @classmethod
    def AddParser(cls, parser: commandline.ArgumentParser):
        """Build the parser.

        Args:
            parser: The argument parser.
        """
        super().AddParser(parser)

        parser.add_argument(
            "-b",
            "--board",
            "--build-target",
            dest="board",
            default=cros_build_lib.GetDefaultBoard(),
            help="The board to build packages for.",
        )
        parser.add_argument(
            "--profile",
            help="The portage configuration profile to use. Profile "
            "must be located in overlay-board/profiles.",
        )
        parser.add_bool_argument(
            "--usepkg",
            True,
            "Use binary packages when available.",
            "Don't use binary packages.",
        )
        parser.add_bool_argument(
            "--usepkgonly",
            False,
            "Only use binary packages; abort if any are missing.",
            "Prefer binary packages, but build from source if needed.",
        )
        parser.add_bool_argument(
            "--workon",
            True,
            "Force-build workon packages.",
            "Don't force-build workon packages.",
        )
        parser.add_bool_argument(
            "--withrevdeps",
            True,
            "Calculate reverse dependencies on changed ebuilds.",
            "Don't calculate reverse dependencies.",
        )
        parser.add_bool_argument(
            "--cleanbuild",
            False,
            "Delete sysroot if it exists before building.",
            "Re-use existing sysroot state.",
        )
        parser.add_bool_argument(
            "--pretend",
            False,
            "Only display which packages would be installed.",
            "Build packages like normal.",
        )

        # The --sysroot flag specifies the environment variables ROOT and
        # PKGDIR.  This allows fetching and emerging of all packages to
        # specified sysroot.  Note that --sysroot will setup the board normally
        # in /build/$BOARD, if it's not setup yet. It also expects the toolchain
        # to already be installed in the sysroot.
        # --usepkgonly and --norebuild are required, because building is not
        # supported when board_root is set.
        parser.add_argument(
            "--sysroot", type="str_path", help="Emerge packages to sysroot."
        )

        # CPU Governor related options.
        group = parser.add_argument_group("CPU Governor Options")
        group.add_bool_argument(
            "--autosetgov",
            False,
            "Automatically set cpu governor to 'performance' when building.",
            "Do not change the cpu governor.",
        )
        group.add_bool_argument(
            "--autosetgov-sticky",
            False,
            "Remember --autosetgov setting for future runs.",
            "Only change the cpu governor for this run.",
        )

        # Chrome building related options.
        group = parser.add_argument_group(
            "Chrome Options",
            description="By default, the build will use any available "
            "chromeos-chrome binpkg, and build Chromium if no usable binpkg "
            "can be found. These options alter that behavior.",
        )
        exclusive_chrome_group = group.add_mutually_exclusive_group()
        exclusive_chrome_group.add_argument(
            "--chrome",
            action="store_true",
            help="Ensure Chrome is installed, building from source if "
            "necessary.",
        )
        exclusive_chrome_group.add_argument(
            "--chromium",
            action="store_true",
            help="Ensure Chromium is installed, building from source if "
            "necessary.",
        )

        # Legacy Chrome arguments.
        group.add_argument(
            "--internal", action="store_true", help=argparse.SUPPRESS
        )
        group.add_argument(
            "--no-internal",
            "--nointernal",
            dest="internal",
            action="store_false",
            help=argparse.SUPPRESS,
        )
        group.add_argument(
            "--use-any-chrome",
            action="store_true",
            default=True,
            help=argparse.SUPPRESS,
        )
        group.add_argument(
            "--no-use-any-chrome",
            "--nouse-any-chrome",
            action="store_false",
            help=argparse.SUPPRESS,
        )

        # Setup board related options.
        group = parser.add_argument_group("Setup Board Config Options")
        group.add_bool_argument(
            "--skip-chroot-upgrade",
            True,
            "Skip the automatic chroot upgrade; use with care.",
            "Upgrade the chroot first.",
        )
        group.add_bool_argument(
            "--skip-toolchain-update",
            False,
            "Deprecated (flag is ignored if passed).",
            "Deprecated (flag is ignored if passed).",
        )
        group.add_bool_argument(
            "--skip-setup-board",
            False,
            "Skip running setup_board. Implies --skip-chroot-upgrade.",
            "Automatically setup the board before building.",
        )

        # Image Type selection related options.
        group = parser.add_argument_group("Image Type Options")
        group.add_bool_argument(
            "--withdev",
            True,
            "Build useful developer friendly utilities.",
            "Omit extra dev image related packages.",
        )
        group.add_bool_argument(
            "--withdebug",
            True,
            "Build debug versions of CrOS-specific packages. "
            "Enables DCHECK, USE=cros-debug, etc...",
            "Build release versions of CrOS-specific packages.",
        )
        group.add_bool_argument(
            "--withfactory",
            True,
            "Build factory installer.",
            "Omit factory related packages.",
        )
        group.add_bool_argument(
            "--withtest",
            True,
            "Build packages required for testing.",
            "Omit test image related packages.",
        )
        group.add_bool_argument(
            "--withautotest",
            True,
            "Build autotest client code.",
            "Omit autotest related packages.",
        )
        group.add_bool_argument(
            "--withdebugsymbols",
            False,
            argparse.SUPPRESS,
            argparse.SUPPRESS,
        )

        # Advanced Options.
        group = parser.add_argument_group("Advanced Options")
        group.add_argument(
            "--accept-licenses", help="Licenses to append to the accept list."
        )
        group.add_bool_argument(
            "--eclean",
            True,
            "Run eclean to delete old binpkgs.",
            "Don't run eclean.",
        )
        group.add_argument(
            "--jobs",
            type=int,
            default=os.cpu_count(),
            help=(
                "Number of packages to build in parallel. (Default: "
                "%(default)s)"
            ),
        )
        group.add_bool_argument(
            "--expandedbinhosts",
            True,
            "Allow expanded binhost inheritance.",
            "Don't expand binhosts.",
        )
        group.add_argument(
            "--backtrack",
            type=int,
            default=sysroot.BACKTRACK_DEFAULT,
            help="See emerge --backtrack.",
        )

        # The --reuse-pkgs-from-local-boards flag tells Portage to share binary
        # packages between boards that are built locally, so that the total time
        # required to build several boards is reduced. This flag is only useful
        # when you are not able to use remote binary packages, since remote
        # binary packages are usually more up to date than anything you have
        # locally.
        group.add_bool_argument(
            "--reuse-pkgs-from-local-boards",
            False,
            "Bootstrap from local packages instead of remote packages.",
            "Only pull remote binpkgs.",
        )

        # This option is for building chrome remotely.
        # 1) starts reproxy 2) builds chrome with reproxy and 3) stops reproxy
        # so logs/stats can be collected.
        # Note: RECLIENT_DIR and REPROXY_CFG env var will be deprecated July
        # 2022.  Use --reclient-dir and --reproxy-cfg input options instead.
        group.add_bool_argument(
            "--run-remoteexec",
            False,
            "Start RBE reproxy, build packages, and then stop reproxy.",
            "Don't use RBE to build.",
        )
        deprecated_note = "Flag will be removed Jan 2025. Use %s instead."
        group.add_argument(
            "--run_remoteexec",
            action="store_true",
            deprecated=deprecated_note % "--run-remoteexec",
            help=argparse.SUPPRESS,
        )
        group.add_argument(
            "--no-run_remoteexec",
            action="store_false",
            deprecated=deprecated_note % "--no-run-remoteexec",
            help=argparse.SUPPRESS,
        )

        group.add_bool_argument(
            "--bazel",
            False,
            "Use Bazel to build packages.",
            "Use portage (emerge) to build packages.",
        )

        group.add_bool_argument(
            "--bazel-lite",
            False,
            "Perform lite build with a limited set of packages.",
            "Build all packages.",
        )
        group.add_argument(
            "--bazel_lite",
            action="store_true",
            deprecated=deprecated_note % "--bazel-lite",
            help=argparse.SUPPRESS,
        )
        group.add_argument(
            "--no-bazel_lite",
            action="store_false",
            deprecated=deprecated_note % "--no-bazel-lite",
            help=argparse.SUPPRESS,
        )

        group.add_bool_argument(
            "--bazel-use-remote-execution",
            False,
            "Execute Bazel actions remotely.",
            "Execute Bazel actions locally.",
        )

        parser.add_argument("packages", nargs="*", help="Packages to build.")
        return parser

    @classmethod
    def ProcessOptions(
        cls,
        parser: commandline.ArgumentParser,
        options: commandline.ArgumentNamespace,
    ) -> None:
        if not options.board:
            # Not supplied and no default set.
            parser.error("--board is required")

        if options.chrome:
            options.internal = True
            options.use_any_chrome = False
        elif options.chromium:
            options.internal = False
            options.use_any_chrome = False

        if options.cleanbuild:
            # Turn off incremental builds when force replacing the sysroot since
            # they can't be incremental.
            options.withrevdeps = False

        options.setup_board_run_config = sysroot.SetupBoardRunConfig(
            force=options.cleanbuild,
            usepkg=options.usepkg,
            jobs=options.jobs,
            quiet=True,
            upgrade_chroot=not options.skip_chroot_upgrade,
            local_build=options.reuse_pkgs_from_local_boards,
            expanded_binhost_inheritance=options.expandedbinhosts,
            use_cq_prebuilts=options.usepkg,
            backtrack=options.backtrack,
        )
        options.build_run_config = sysroot.BuildPackagesRunConfig(
            usepkg=options.usepkg,
            packages=options.packages,
            use_remoteexec=options.run_remoteexec,
            incremental_build=options.withrevdeps,
            dryrun=options.pretend,
            usepkgonly=options.usepkgonly,
            workon=options.workon,
            install_auto_test=options.withautotest,
            autosetgov=options.autosetgov,
            autosetgov_sticky=options.autosetgov_sticky,
            use_any_chrome=options.use_any_chrome,
            internal_chrome=options.internal,
            eclean=options.eclean,
            jobs=options.jobs,
            local_pkg=options.reuse_pkgs_from_local_boards,
            dev_image=options.withdev,
            factory_image=options.withfactory,
            test_image=options.withtest,
            debug_version=options.withdebug,
            backtrack=options.backtrack,
            bazel=options.bazel,
            bazel_lite=options.bazel_lite,
            bazel_use_remote_execution=options.bazel_use_remote_execution,
        )

    @timer.timed("Elapsed time (cros build-packages)")
    def Run(self) -> None:
        commandline.RunInsideChroot()

        try:
            build_packages(self.options)
            logging.notice("cros build-packages completed successfully.")
        except sysroot_lib.PackageInstallError as e:
            try:
                with urllib.request.urlopen(
                    "https://chromiumos-status.appspot.com/current?format=raw"
                ) as request:
                    logging.notice("Tree Status: %s", request.read().decode())
            except urllib.error.HTTPError:
                pass
            cros_build_lib.Die(e)


@tracer.start_as_current_span("cli.cros.cros_build_packages.build_packages")
def build_packages(opts: commandline.ArgumentNamespace) -> None:
    span = trace.get_current_span()

    build_target = build_target_lib.BuildTarget(
        opts.board,
        build_root=opts.sysroot,
        profile=opts.profile,
    )
    board_root = sysroot_lib.Sysroot(build_target.root)
    if not board_root.Exists():
        # Disable incremental builds when the sysroot doesn't exist.
        opts.build_run_config.is_incremental = False

    span.set_attributes(
        {
            "board": build_target.name,
            "packages": opts.packages or [],
            "is_complete": not opts.packages,
            "is_incremental": opts.build_run_config.is_incremental,
            "workon": opts.workon is True,
            "bazel": opts.bazel is True,
        }
    )

    # TODO(xcl): Update run_configs to have a common base set of configs for
    # setup_board and cros build-packages.
    if not opts.skip_setup_board:
        sysroot.SetupBoard(
            build_target,
            accept_licenses=opts.accept_licenses,
            run_configs=opts.setup_board_run_config,
        )

    sysroot.BuildPackages(build_target, board_root, opts.build_run_config)
