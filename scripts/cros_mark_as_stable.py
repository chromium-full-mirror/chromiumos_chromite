# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module uprevs a given package's ebuild to the next revision."""

import logging
import os
import re

from chromite.lib import chromeos_version
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import portage_util
from chromite.lib import repo_util


# Commit message subject for uprevving Portage packages.
GIT_COMMIT_SUBJECT = "Marking set of ebuilds as stable"

# Commit message for uprevving Portage packages.
_GIT_COMMIT_MESSAGE = "Marking 9999 ebuild for %s as stable."

# Dictionary of valid commands with usage information.
COMMAND_DICTIONARY = {
    "commit": "Marks given ebuilds as stable locally",
}


# ======================= Global Helper Functions ========================


def CleanStalePackages(srcroot, boards, package_atoms) -> None:
    """Cleans up stale package info from a previous build.

    Args:
        srcroot: Root directory of the source tree.
        boards: Boards to clean the packages from.
        package_atoms: A list of package atoms to unmerge.
    """
    if package_atoms:
        logging.info("Cleaning up stale packages %s.", package_atoms)

    # First unmerge all the packages for a board, then eclean it.
    # We need these two steps to run in order (unmerge/eclean),
    # but we can let all the boards run in parallel.
    def _CleanStalePackages(board) -> None:
        if board:
            suffix = "-" + board
            runcmd = cros_build_lib.run
        else:
            suffix = ""
            runcmd = cros_build_lib.sudo_run

        emerge, eclean = "emerge" + suffix, "eclean" + suffix
        if not osutils.FindMissingBinaries([emerge, eclean]):
            if package_atoms:
                # If nothing was found to be unmerged, emerge will exit(1).
                result = runcmd(
                    [emerge, "-q", "--unmerge"] + list(package_atoms),
                    enter_chroot=True,
                    extra_env={"CLEAN_DELAY": "0"},
                    check=False,
                    cwd=srcroot,
                )
                if result.returncode not in (0, 1):
                    raise cros_build_lib.RunCommandError(
                        "unexpected error", result
                    )
            runcmd(
                [eclean, "-d", "packages"],
                cwd=srcroot,
                enter_chroot=True,
                stdout=True,
                stderr=True,
            )

    tasks = []
    for board in boards:
        tasks.append([board])
    tasks.append([None])

    parallel.RunTasksInProcessPool(_CleanStalePackages, tasks)


# ======================= End Global Helper Functions ========================


class GitBranch:
    """Wrapper class for a git branch."""

    def __init__(self, branch_name, tracking_branch, cwd) -> None:
        """Sets up variables but does not create the branch.

        Args:
            branch_name: The name of the branch.
            tracking_branch: The associated tracking branch.
            cwd: The git repository to work in.
        """
        self.branch_name = branch_name
        self.tracking_branch = tracking_branch
        self.cwd = cwd

    def CreateBranch(self) -> None:
        self.Checkout()

    def Checkout(self, branch=None) -> None:
        """Function used to check out to another GitBranch."""
        if not branch:
            branch = self.branch_name
        if branch == self.tracking_branch or self.Exists(branch):
            git.RunGit(self.cwd, ["checkout", "-f", branch])
        else:
            repo = repo_util.Repository.MustFind(self.cwd)
            repo.StartBranch(branch, projects=["."], cwd=self.cwd)

    def Exists(self, branch=None):
        """Returns True if the branch exists."""
        if not branch:
            branch = self.branch_name
        branches = git.RunGit(self.cwd, ["branch"]).stdout
        return branch in branches.split()


def GetParser():
    """Creates the argparse parser."""
    parser = commandline.ArgumentParser()
    parser.add_argument(
        "--all", action="store_true", help="Mark all packages as stable."
    )
    parser.add_argument(
        "-b",
        "--boards",
        action="split_extend",
        default=[],
        help="List of boards.",
    )
    parser.add_argument(
        "--drop_file", help="File to list packages that were revved."
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Passes dry-run to git push if pushing a change.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force the stabilization of packages marked for "
        "manual uprev. "
        "(only compatible with -p)",
    )
    parser.add_argument(
        "--list_revisions",
        action="store_true",
        help="List all revisions included in the commit message.",
    )
    parser.add_argument(
        "-o", "--overlays", help="Colon-separated list of overlays to modify."
    )
    parser.add_argument(
        "--overlay-type",
        help='Populates --overlays based on "public", "private"' ', or "both".',
    )
    parser.add_argument(
        "-p", "--packages", help="Colon separated list of packages to rev."
    )
    parser.add_argument(
        "--buildroot", type="str_path", help="Path to buildroot."
    )
    parser.add_argument(
        "-r",
        "--srcroot",
        type="str_path",
        help="Path to root src. Deprecated in favor of " "--buildroot",
    )
    parser.add_argument(
        "--staging_branch", help="The staging branch to push changes"
    )
    parser.add_argument(
        "command", choices=sorted(COMMAND_DICTIONARY), help="Command to run."
    )
    return parser


def main(argv) -> None:
    parser = GetParser()
    options = parser.parse_args(argv)

    # TODO: Remove this code in favor of a simple default on buildroot when
    #       srcroot is removed.
    if options.srcroot and not options.buildroot:
        # Convert /<repo>/src -> <repo>
        options.buildroot = os.path.dirname(options.srcroot)
    if not options.buildroot:
        options.buildroot = constants.SOURCE_ROOT
    options.srcroot = None

    options.freeze()

    if options.command == "commit":
        if not options.packages and not options.all:
            parser.error("Please specify at least one package (--packages)")
        if options.force and options.all:
            parser.error(
                "Cannot use --force with --all. You must specify a list of "
                "packages you want to force uprev."
            )

    if not os.path.isdir(options.buildroot):
        parser.error("buildroot is not a valid path: %s" % options.buildroot)

    if options.overlay_type and options.overlays:
        parser.error("Cannot use --overlay-type with --overlays.")

    portage_util.EBuild.VERBOSE = options.verbose

    package_list = None
    if options.packages:
        package_list = re.split(r"[:\s]", options.packages)

    overlays = []
    if options.overlays:
        for path in options.overlays.split(":"):
            if not os.path.isdir(path):
                cros_build_lib.die("Cannot find overlay: %s", path)
            overlays.append(os.path.realpath(path))
    elif options.overlay_type:
        overlays = portage_util.FindOverlays(
            options.overlay_type, buildroot=options.buildroot
        )
    else:
        logging.warning("Missing --overlays argument")
        overlays.extend(
            [
                "%s/src/private-overlays/chromeos-overlay" % options.buildroot,
                "%s/src/third_party/chromiumos-overlay" % options.buildroot,
            ]
        )

    manifest = git.ManifestCheckout.Cached(options.buildroot)

    # Dict mapping from each overlay to its tracking branch.
    overlay_tracking_branch = {}
    # Dict mapping from each git repository (project) to a list of its overlays.
    git_project_overlays = {}

    for overlay in overlays:
        remote_ref = git.GetTrackingBranchViaManifest(
            overlay, manifest=manifest
        )
        overlay_tracking_branch[overlay] = remote_ref.ref
        git_project_overlays.setdefault(remote_ref.project_name, []).append(
            overlay
        )

    if options.command == "commit":
        _WorkOnCommit(
            options,
            overlays,
            overlay_tracking_branch,
            git_project_overlays,
            manifest,
            package_list,
        )


def _WorkOnCommit(
    options,
    overlays,
    overlay_tracking_branch,
    git_project_overlays,
    manifest,
    package_list,
) -> None:
    """Commit uprevs of overlays in different git projects in parallel.

    Args:
        options: The options object returned by the argument parser.
        overlays: A list of overlays to work on.
        overlay_tracking_branch: A dict mapping from each overlay to its
            tracking branch.
        git_project_overlays: A dict mapping from each git repository to a list
            of its overlays.
        manifest: The manifest of the given source root.
        package_list: A list of packages passed from commandline to work on.
    """
    # We cleaned up self-referential ebuilds by this version, but don't enforce
    # the check on older ones to avoid breaking factory/firmware branches.
    root_version = chromeos_version.VersionInfo.from_repo(options.buildroot)
    no_self_repos_version = chromeos_version.VersionInfo("13099.0.0")
    reject_self_repo = root_version >= no_self_repos_version

    overlay_ebuilds = _GetOverlayToEbuildsMap(options, overlays, package_list)

    with parallel.Manager() as manager:
        # Contains the array of packages we actually revved.
        revved_packages = manager.list()
        new_package_atoms = manager.list()

        inputs = [
            [
                options,
                manifest,
                overlays_per_project,
                overlay_tracking_branch,
                overlay_ebuilds,
                revved_packages,
                new_package_atoms,
                reject_self_repo,
            ]
            for overlays_per_project in git_project_overlays.values()
        ]
        parallel.RunTasksInProcessPool(_CommitOverlays, inputs)

        chroot_path = os.path.join(
            options.buildroot, constants.DEFAULT_CHROOT_DIR
        )
        if os.path.exists(chroot_path):
            CleanStalePackages(
                options.buildroot, options.boards, new_package_atoms
            )
        if options.drop_file:
            osutils.WriteFile(options.drop_file, " ".join(revved_packages))


def _GetOverlayToEbuildsMap(options, overlays, package_list):
    """Get ebuilds for overlays.

    Args:
        options: The options object returned by the argument parser.
        overlays: A list of overlays to work on.
        package_list: A list of packages passed from commandline to work on.

    Returns:
        A dict mapping each overlay to a list of ebuilds belonging to it.
    """
    root_version = chromeos_version.VersionInfo.from_repo(options.buildroot)
    subdir_removal = chromeos_version.VersionInfo("10363.0.0")
    require_subdir_support = root_version < subdir_removal

    overlay_ebuilds = {}
    inputs = [
        [
            overlay,
            options.all,
            package_list,
            options.force,
            require_subdir_support,
        ]
        for overlay in overlays
    ]
    result = parallel.RunTasksInProcessPool(
        portage_util.GetOverlayEBuilds, inputs
    )
    for idx, ebuilds in enumerate(result):
        overlay_ebuilds[overlays[idx]] = ebuilds

    return overlay_ebuilds


def _CommitOverlays(
    options,
    manifest,
    overlays,
    overlay_tracking_branch,
    overlay_ebuilds,
    revved_packages,
    new_package_atoms,
    reject_self_repo=True,
) -> None:
    """Commit uprevs for overlays in sequence.

    Args:
        options: The options object returned by the argument parser.
        manifest: The manifest of the given source root.
        overlays: A list over overlays to commit.
        overlay_tracking_branch: A dict mapping from each overlay to its
            tracking branch.
        overlay_ebuilds: A dict mapping overlays to their ebuilds.
        revved_packages: A shared list of revved packages.
        new_package_atoms: A shared list of new package atoms.
        reject_self_repo: Whether to abort if the ebuild lives in the same git
            repo as it is tracking for uprevs.
    """
    for overlay in overlays:
        if not os.path.isdir(overlay):
            logging.warning("Skipping %s, which is not a directory.", overlay)
            continue

        # Note we intentionally work from the non push tracking branch;
        # everything built thus far has been against it (meaning, http mirrors),
        # thus we should honor that.  During the actual push, the code switches
        # to the correct urls, and does an appropriate rebasing.
        tracking_branch = overlay_tracking_branch[overlay]

        existing_commit = git.GetGitRepoRevision(overlay)

        # Make sure we run in the top-level git directory in case we are
        # adding/removing an overlay in existing_commit.
        git_root = git.FindGitTopLevel(overlay)
        if git_root is None:
            cros_build_lib.die("No git repo at overlay directory %s.", overlay)

        work_branch = GitBranch(
            constants.STABLE_EBUILD_BRANCH, tracking_branch, cwd=git_root
        )
        work_branch.CreateBranch()
        if not work_branch.Exists():
            cros_build_lib.die(
                "Unable to create stabilizing branch in %s" % overlay
            )

        # In the case of uprevving overlays that have patches applied to them,
        # include the patched changes in the stabilizing branch.
        git.RunGit(git_root, ["rebase", existing_commit])

        ebuilds = overlay_ebuilds.get(overlay, [])
        if ebuilds:
            with parallel.Manager() as manager:
                # Contains the array of packages we actually revved.
                messages = manager.list()
                ebuild_paths_to_add = manager.list()
                ebuild_paths_to_remove = manager.list()

                inputs = [
                    [
                        overlay,
                        ebuild,
                        manifest,
                        options,
                        ebuild_paths_to_add,
                        ebuild_paths_to_remove,
                        messages,
                        revved_packages,
                        new_package_atoms,
                        reject_self_repo,
                    ]
                    for ebuild in ebuilds
                ]
                parallel.RunTasksInProcessPool(_WorkOnEbuild, inputs)

                if ebuild_paths_to_add:
                    logging.info(
                        "Adding new stable ebuild paths %s in overlay %s.",
                        ebuild_paths_to_add,
                        overlay,
                    )
                    git.RunGit(overlay, ["add"] + list(ebuild_paths_to_add))

                if ebuild_paths_to_remove:
                    logging.info(
                        "Removing old ebuild paths %s in overlay %s.",
                        ebuild_paths_to_remove,
                        overlay,
                    )
                    git.RunGit(
                        overlay, ["rm", "-f"] + list(ebuild_paths_to_remove)
                    )

                if messages:
                    portage_util.EBuild.CommitChange(
                        "\n\n".join(messages), overlay
                    )


def _WorkOnEbuild(
    overlay,
    ebuild,
    manifest,
    options,
    ebuild_paths_to_add,
    ebuild_paths_to_remove,
    messages,
    revved_packages,
    new_package_atoms,
    reject_self_repo=True,
) -> None:
    """Work on a single ebuild.

    Args:
        overlay: The overlay where the ebuild belongs to.
        ebuild: The ebuild to work on.
        manifest: The manifest of the given source root.
        options: The options object returned by the argument parser.
        ebuild_paths_to_add: New stable ebuild paths to add to git.
        ebuild_paths_to_remove: Old ebuild paths to remove from git.
        messages: A share list of commit messages.
        revved_packages: A shared list of revved packages.
        new_package_atoms: A shared list of new package atoms.
        reject_self_repo: Whether to abort if the ebuild lives in the same git
            repo as it is tracking for uprevs.
    """
    if options.verbose:
        logging.info(
            "Working on %s, info %s", ebuild.package, ebuild.cros_workon_vars
        )
    if not ebuild.cros_workon_vars:
        logging.warning(
            "%s: unable to parse workon settings", ebuild.ebuild_path
        )

    try:
        result = ebuild.RevWorkOnEBuild(
            os.path.join(options.buildroot, "src"),
            manifest,
            reject_self_repo=reject_self_repo,
        )
        if result:
            new_package, ebuild_path_to_add, ebuild_path_to_remove = result

            if ebuild_path_to_add:
                ebuild_paths_to_add.append(ebuild_path_to_add)
            if ebuild_path_to_remove:
                ebuild_paths_to_remove.append(ebuild_path_to_remove)

            messages.append(_GIT_COMMIT_MESSAGE % ebuild.package)

            if options.list_revisions:
                info = ebuild.GetSourceInfo(
                    os.path.join(options.buildroot, "src"),
                    manifest,
                    reject_self_repo=reject_self_repo,
                )
                srcdirs = [
                    os.path.join(options.buildroot, "src", srcdir)
                    for srcdir in ebuild.cros_workon_vars.localname
                ]
                old_commit_ids = dict(
                    zip(srcdirs, ebuild.cros_workon_vars.commit.split(","))
                )
                git_log = []
                for srcdir in info.srcdirs:
                    old_commit_id = old_commit_ids.get(srcdir)
                    new_commit_id = ebuild.GetCommitId(srcdir)
                    if not old_commit_id or old_commit_id == new_commit_id:
                        continue

                    logs = git.RunGit(
                        srcdir,
                        [
                            "log",
                            "%s..%s" % (old_commit_id[:8], new_commit_id[:8]),
                            "--pretty=format:%h %<(63,trunc)%s",
                        ],
                    )
                    git_log.append("$ " + logs.cmdstr)
                    git_log.extend(
                        line.strip() for line in logs.stdout.splitlines()
                    )
                if git_log:
                    messages.append("\n".join(git_log))

            revved_packages.append(ebuild.package)
            new_package_atoms.append("=%s" % new_package)
    except portage_util.InvalidUprevSourceError as e:
        logging.error(
            "An error occurred while uprevving %s: %s", ebuild.package, e
        )
        raise
    except portage_util.EbuildVersionError as e:
        logging.warning("Unable to rev %s: %s", ebuild.package, e)
        raise
    except OSError:
        logging.warning(
            "Cannot rev %s\n"
            "Note you will have to go into %s "
            "and reset the git repo yourself.",
            ebuild.package,
            overlay,
        )
        raise
