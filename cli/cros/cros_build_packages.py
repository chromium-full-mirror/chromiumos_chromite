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

from chromite.third_party.opentelemetry import trace

from chromite.cli import command
from chromite.lib import build_target_lib
from chromite.lib import chromite_config
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import sysroot_lib
from chromite.lib import telemetry
from chromite.service import sysroot
from chromite.utils import timer


def build_shell_bool_style_args(
    parser: commandline.ArgumentParser,
    name: str,
    default_val: bool,
    help_str: str,
) -> None:
    """Build the shell boolean input argument equivalent.

    For a given input arg name 'argA', we create two python arguments;
    --argA, and --no-argA.

    Args:
        parser: The parser to update.
        name: The input argument name. This will be used as 'dest' variable
            name.
        default_val: The default value to assign.
        help_str: The help string for the input argument.
    """
    arg = f"--{name}"
    py_narg = f"--no-{name}"
    default_val_str = f"{help_str} (Default: %(default)s)."
    dest = name.replace("-", "_")

    parser.add_argument(
        arg,
        action="store_true",
        default=default_val,
        dest=dest,
        help=default_val_str,
    )
    parser.add_argument(
        py_narg,
        action="store_false",
        dest=dest,
        help="Don't " + help_str.lower(),
    )


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
        build_shell_bool_style_args(
            parser,
            "usepkg",
            True,
            "Use binary packages to bootstrap when possible.",
        )
        build_shell_bool_style_args(
            parser,
            "usepkgonly",
            False,
            "Use binary packages only to bootstrap; abort if any are missing.",
        )
        build_shell_bool_style_args(
            parser, "workon", True, "Force-build workon packages."
        )
        build_shell_bool_style_args(
            parser,
            "withrevdeps",
            True,
            "Calculate reverse dependencies on changed ebuilds.",
        )
        build_shell_bool_style_args(
            parser,
            "cleanbuild",
            False,
            "Delete sysroot if it exists before building.",
        )
        build_shell_bool_style_args(
            parser,
            "pretend",
            False,
            "Pretend building packages, just display which packages would have "
            "been installed.",
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
        build_shell_bool_style_args(
            group,
            "autosetgov",
            False,
            "Automatically set cpu governor to 'performance'.",
        )
        build_shell_bool_style_args(
            group,
            "autosetgov-sticky",
            False,
            "Remember --autosetgov setting for future runs.",
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
        build_shell_bool_style_args(
            group,
            "skip-chroot-upgrade",
            False,
            "Skip the automatic chroot upgrade; use with care.",
        )
        build_shell_bool_style_args(
            group,
            "skip-toolchain-update",
            False,
            "Skip automatic toolchain update",
        )
        build_shell_bool_style_args(
            group,
            "skip-setup-board",
            False,
            "Skip running setup_board. Implies "
            "--skip-chroot-upgrade --skip-toolchain-update.",
        )

        # Image Type selection related options.
        group = parser.add_argument_group("Image Type Options")
        build_shell_bool_style_args(
            group, "withdev", True, "Build useful developer friendly utilities."
        )
        build_shell_bool_style_args(
            group,
            "withdebug",
            True,
            "Build debug versions of Chromium-OS-specific packages.",
        )
        build_shell_bool_style_args(
            group, "withfactory", True, "Build factory installer."
        )
        build_shell_bool_style_args(
            group, "withtest", True, "Build packages required for testing."
        )
        build_shell_bool_style_args(
            group, "withautotest", True, "Build autotest client code."
        )
        build_shell_bool_style_args(
            group,
            "withdebugsymbols",
            False,
            "Install the debug symbols for all packages.",
        )

        # Advanced Options.
        group = parser.add_argument_group("Advanced Options")
        group.add_argument(
            "--accept-licenses", help="Licenses to append to the accept list."
        )
        build_shell_bool_style_args(
            group, "eclean", True, "Run eclean to delete old binpkgs."
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
        build_shell_bool_style_args(
            group,
            "expandedbinhosts",
            True,
            "Allow expanded binhost inheritance.",
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
        build_shell_bool_style_args(
            group,
            "reuse-pkgs-from-local-boards",
            False,
            "Bootstrap from local packages instead of remote packages.",
        )

        # --run-goma option is designed to be used on bots.
        # If you're trying to build packages with goma in your local dev env,
        # this is *not* the option you're looking for.  Please see comments
        # below.  This option; 1) starts goma, 2) builds packages (expecting
        # that goma is used), then 3) stops goma explicitly.
        # 4) is a request from the goma team, so that stats/logs can be taken.
        # Note: GOMA_DIR is expected to be passed via env var.
        #
        # In local dev env cases, compiler_proxy is expected to keep running.
        # In such a case;
        #   $ python ${GOMA_DIR}/goma_ctl.py ensure_start
        #   $ cros build-image (... and options without --run-goma ...)
        # is an expected commandline sequence. If you set --run-goma flag while
        # compiler_proxy is already running, the existing compiler_proxy will be
        # stopped.
        build_shell_bool_style_args(
            group,
            "run-goma",
            False,
            "When set, (re)starts goma, builds packages, and then stops goma.",
        )
        # This option is for building chrome remotely.
        # 1) starts reproxy 2) builds chrome with reproxy and 3) stops reproxy
        # so logs/stats can be collected.
        # Note: RECLIENT_DIR and REPROXY_CFG env var will be deprecated July
        # 2022.  Use --reclient-dir and --reproxy-cfg input options instead.
        build_shell_bool_style_args(
            group,
            "run_remoteexec",
            False,
            "If set to true, starts RBE reproxy, builds packages, and then "
            "stops reproxy.",
        )

        build_shell_bool_style_args(
            group, "bazel", False, "Use Bazel to build packages."
        )

        build_shell_bool_style_args(
            group,
            "bazel_lite",
            False,
            "Perform lite build with a limited set of packages.",
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
            update_toolchain=not options.skip_toolchain_update,
            upgrade_chroot=not options.skip_chroot_upgrade,
            local_build=options.reuse_pkgs_from_local_boards,
            expanded_binhost_inheritance=options.expandedbinhosts,
            use_cq_prebuilts=options.usepkg,
            backtrack=options.backtrack,
        )
        options.build_run_config = sysroot.BuildPackagesRunConfig(
            usepkg=options.usepkg,
            install_debug_symbols=options.withdebugsymbols,
            packages=options.packages,
            use_goma=options.run_goma,
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
        )

    @timer.timed("Elapsed time (cros build-packages)")
    def Run(self) -> None:
        commandline.RunInsideChroot()

        chromite_config.initialize()
        telemetry.initialize(
            chromite_config.TELEMETRY_CONFIG,
            log_traces=self.options.log_telemetry,
        )
        try:
            build_packages(self.options)
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
            "sticky_update_enabled": (
                chromite_config.SDK_UPDATE_STICKY_CONFIG.exists()
            ),
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
