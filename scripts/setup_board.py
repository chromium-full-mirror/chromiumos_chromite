# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""setup_board builds the sysroot for a board.

The setup_board process includes the simple directory creations, installs
several configuration files, sets up portage command wrappers and configs,
and installs the toolchain and some core dependency packages (e.g. kernel
headers, gcc-libs).
"""

import argparse
import logging

from chromite.lib import build_target_lib
from chromite.lib import commandline
from chromite.lib import portage_util
from chromite.lib import sysroot_lib
from chromite.lib.telemetry import trace
from chromite.service import sysroot


tracer = trace.get_tracer(__name__)


def GetParser():
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)

    parser.add_argument(
        "-b",
        "--board",
        "--build-target",
        required=True,
        dest="board",
        help="The name of the board to set up.",
    )
    parser.add_argument(
        "--default",
        action="store_true",
        default=False,
        help="Set the board to the default board in your chroot.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force re-creating the board root.",
    )
    # The positive and negative versions of the arguments are used.
    # TODO(saklein) Simplify usages to a single version of the argument.
    parser.add_argument(
        "--usepkg",
        action="store_true",
        default=True,
        dest="usepkg",
        help="Use binary packages to bootstrap.",
    )
    parser.add_argument(
        "--nousepkg",
        action="store_false",
        default=True,
        dest="usepkg",
        help="Do not use binary packages to bootstrap.",
    )

    advanced = parser.add_argument_group("Advanced Options")
    advanced.add_argument(
        "--accept-licenses", help="Licenses to append to the accept list."
    )

    # Build target related arguments.
    target = parser.add_argument_group("Advanced Build Target Options")
    target.add_argument(
        "--profile",
        help="The portage configuration profile to use. Profile "
        "must be located in overlay-board/profiles.",
    )
    target.add_argument("--board-root", type="str_path", help="Board root.")
    target.add_bool_argument(
        "--public",
        default=None,
        enabled_desc=(
            "Simulate a public build by selecting only public overlays.  Note "
            "behavior differences may still exist when using an actual public "
            "checkout, i.e., this is for convenience only.  Don't use this to "
            "produce a build which is guaranteed to be free of all private "
            "artifacts.  By default, this is enabled for boards without a "
            "private overlay."
        ),
        disabled_desc=(
            "Disable --public on a normally-public board (e.g., amd64-generic)."
        ),
    )
    target.add_argument(
        "--reuse-configs",
        action="store_true",
        help="Reuse the build target configs from the existing sysroot.",
    )

    # Arguments related to the build itself.
    build = parser.add_argument_group("Advanced Build Modification Options")
    build.add_argument(
        "--jobs",
        type=int,
        help="Maximum number of packages to build in parallel.",
    )
    build.add_argument(
        "--regen-configs",
        action="store_true",
        default=False,
        help="Regenerate all config files (useful for "
        "modifying profiles without rebuild).",
    )
    build.add_argument(
        "--quiet",
        action="store_true",
        default=False,
        help="Don't print warnings when board already exists.",
    )
    build.add_bool_argument(
        "--setup-toolchains",
        default=False,
        enabled_desc="Setup or update toolchains for the board.",
        disabled_desc="Use currently installed toolchain versions.",
    )
    build.add_argument(
        "--skip-toolchain-update",
        action="store_false",
        dest="toolchain_update",
        deprecated="Alias for --no-toolchain-update",
    )
    build.add_bool_argument(
        "--update-chroot",
        default=None,
        enabled_desc="Call update_chroot.",
        disabled_desc="Don't call update_chroot.",
    )
    build.add_argument(
        "--skip-chroot-upgrade",
        action="store_false",
        dest="update_chroot",
        deprecated="Alias for --no-update-chroot.",
    )
    build.add_argument(
        "--skip-board-pkg-init",
        action="store_true",
        default=False,
        help="Don't emerge any packages during setup_board into "
        "the board root.",
    )
    build.add_argument(
        "--reuse-pkgs-from-local-boards",
        dest="reuse_local",
        action="store_true",
        default=False,
        help="Bootstrap from local packages instead of remote packages.",
    )
    build.add_argument(
        "--backtrack",
        type=int,
        default=sysroot.BACKTRACK_DEFAULT,
        help="See emerge --backtrack.",
    )

    parser.add_argument(
        "--fewer-binhosts",
        dest="expanded_binhost_inheritance",
        default=True,
        action="store_false",
        help=argparse.SUPPRESS,
    )

    return parser


def _ParseArgs(args):
    """Parse and validate arguments."""
    parser = GetParser()
    opts = parser.parse_args(args)

    # Translate raw options to config objects.
    opts.build_target = build_target_lib.BuildTarget(
        opts.board,
        build_root=opts.board_root,
        profile=opts.profile,
        public=opts.public,
    )
    if opts.reuse_configs:
        sysroot_path = (
            opts.board_root
            or build_target_lib.get_default_sysroot_path(opts.board)
        )
        sysroot_inst = sysroot_lib.Sysroot(sysroot_path)
        if not sysroot_inst.Exists():
            parser.error(
                "--reuse-configs can only be used with an existing sysroot."
            )
        try:
            opts.build_target = sysroot_inst.build_target
        except sysroot_lib.NoBuildTargetFileError:
            logging.exception("No build target configuration file.")
            parser.error(
                "The sysroot does not have a build target configuration "
                "file, it probably just predates the file. If this error "
                "persists after setting up the board without using "
                "--reuse-configs please file a bug for the CrOS Build team."
            )

    update_chroot = opts.update_chroot
    if update_chroot is None:
        update_chroot = opts.setup_toolchains

    opts.run_config = sysroot.SetupBoardRunConfig(
        set_default=opts.default,
        force=opts.force,
        usepkg=opts.usepkg,
        jobs=opts.jobs,
        regen_configs=opts.regen_configs,
        quiet=opts.quiet,
        update_toolchain=opts.setup_toolchains,
        upgrade_chroot=update_chroot,
        init_board_pkgs=not opts.skip_board_pkg_init,
        local_build=opts.reuse_local,
        expanded_binhost_inheritance=opts.expanded_binhost_inheritance,
        use_cq_prebuilts=opts.usepkg,
        backtrack=opts.backtrack,
    )

    opts.Freeze()
    return opts


def main(argv):
    commandline.RunInsideChroot()
    opts = _ParseArgs(argv)
    with tracer.start_as_current_span("chromite.scripts.setup_board") as span:
        try:
            span.set_attributes(
                {
                    "build_target": opts.build_target.name,
                    "update_chroot": opts.run_config.update_chroot,
                    "update_toolchain": opts.run_config.update_toolchain,
                    "set_default": opts.run_config.set_default,
                }
            )
            sysroot.SetupBoard(
                opts.build_target, opts.accept_licenses, opts.run_config
            )
        except portage_util.MissingOverlayError as e:
            # Add a bit more user-friendly message as people can typo names
            # easily.
            logging.error(
                "%s\n"
                "Double check the --board setting and make sure you're syncing "
                "the right manifest (internal-vs-external).",
                e,
            )
            return 1
        except sysroot.Error as e:
            logging.error(e)
            return 1
