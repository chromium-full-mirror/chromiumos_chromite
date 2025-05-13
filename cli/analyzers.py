# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Shared helpers for cros analyzer commands (fix, lint, format)."""

import logging
import os
from pathlib import Path
from typing import List

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import git
from chromite.lib import path_util
from chromite.utils import path_filter


def GetFilesFromCommit(commit: str) -> List[str]:
    """Returns files changed in the provided git `commit` as absolute paths."""
    repo_root_path = git.FindGitTopLevel(None)
    files_in_repo = git.RunGit(
        repo_root_path,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", commit],
    ).stdout.splitlines()
    return [os.path.join(repo_root_path, p) for p in files_in_repo]


def HasUncommittedChanges(files: List[str]) -> bool:
    """Returns whether there are uncommitted changes on any of the `files`.

    `files` can be absolute or relative to the current working directory. If a
    file is passed that is outside the git repository corresponding to the
    current working directory, an exception will be thrown.
    """
    working_status = git.RunGit(
        None, ["status", "--porcelain=v1", *files]
    ).stdout.splitlines()
    if working_status:
        logging.warning("%s", "\n".join(working_status))
    return bool(working_status)


class AnalyzerCommand(command.CliCommand):
    """Shared argument parsing for cros analyzers (fix, lint, format)."""

    # Additional aliases to offer for the "--inplace" option.
    inplace_option_aliases = []

    # Whether to include options that only make sense for analyzers that can
    # modify the files being checked.
    can_modify_files = False

    # CliCommand overrides.
    use_filter_options = True
    use_jobs_options = True

    @classmethod
    def AddParser(cls, parser) -> None:
        super().AddParser(parser)
        if cls.can_modify_files:
            parser.add_argument(
                "--check",
                dest="dryrun",
                action="store_true",
                help="Display files with errors & exit non-zero",
            )
            parser.add_argument(
                "--diff",
                action="store_true",
                help="Display diff instead of fixed content",
            )
            parser.add_argument(
                *(["-i", "--inplace"] + cls.inplace_option_aliases),
                dest="inplace",
                default=None,
                action="store_true",
                help="Fix files inplace (default)",
            )
            # NB: This must come after --inplace due to dest= being the same,
            # and so --inplace's default= is used.
            parser.add_argument(
                "--stdout",
                dest="inplace",
                action="store_false",
                help="Write to stdout",
            )

        parser.add_argument(
            "--commit",
            type=str,
            help=(
                "Use files from git commit instead of on disk. If no files are"
                " provided, the list will be obtained from git diff-tree."
            ),
        )
        parser.add_argument(
            "--head",
            "--HEAD",
            dest="commit",
            action="store_const",
            const="HEAD",
            help="Alias for --commit HEAD.",
        )
        parser.add_argument(
            "files",
            nargs="*",
            type=Path,
            help=(
                "Files to fix. Directories will be expanded, and if in a git"
                " repository, the .gitignore will be respected."
            ),
        )

    @classmethod
    def ProcessOptions(
        cls,
        parser: commandline.ArgumentParser,
        options: commandline.ArgumentNamespace,
    ) -> None:
        """Validate & post-process options before freezing."""
        if cls.can_modify_files:
            if cls.use_dryrun_options and options.dryrun:
                if options.inplace:
                    # A dry-run should never alter files in-place.
                    logging.warning("Ignoring inplace option for dry-run.")
                options.inplace = False
            if options.inplace is None:
                options.inplace = True

        # Whether a committed change is being analyzed. Note "pre-submit" is a
        # special commit passed by `pre-upload.py --pre-submit` asking to check
        # changes only staged for a commit, but not yet committed.
        is_committed = options.commit and options.commit != "pre-submit"

        if is_committed and not options.files:
            options.files = GetFilesFromCommit(options.commit)

        if cls.can_modify_files and is_committed and options.inplace:
            # If a commit is provided, bail when using inplace if any of the
            # files have uncommitted changes. This is because the input to the
            # analyzer will not consider any working state changes, so they will
            # likely be lost. In future this may be supported by attempting to
            # stash and rebase changes. See also b/290714959.
            if HasUncommittedChanges(options.files):
                parser.error("In-place may clobber uncommitted changes.")

        # Hack "pre-submit" to "HEAD" when being run by repohooks/pre-upload.py
        # --pre-submit.  We should drop support for this once we merge repohooks
        # into `cros` with proper preupload/presubmit.
        if options.commit == "pre-submit":
            options.commit = "HEAD"

        # Ignore generated files.  Some tools can do this for us, but not all,
        # and it'd be faster if we just never spawned the tools in the first
        # place.  Prepend the exclude rules so a more general filter like
        # `--include "*.py"` won't include them.
        # TODO(build): Move to a centralized configuration somewhere.
        options.filter.rules[:0] = (
            # Compiled python protobuf bindings.
            path_filter.exclude("*_pb2.py"),
            path_filter.exclude("*_pb2_grpc.py"),
            # Vendored third-party code.
            path_filter.exclude("*third_party/*.py"),
        )

    def discover_paths(self):
        """Find all the paths we are to process based on CLI options."""
        commit = self.options.commit

        # Ignore symlinks.
        files = []
        syms = []
        if commit:
            for f in git.LsTree(None, commit, self.options.files):
                if f.is_symlink:
                    syms.append(f.name)
                else:
                    files.append(f.name)
        else:
            for f in path_util.ExpandDirectories(self.options.files):
                if f.is_symlink():
                    syms.append(f)
                else:
                    files.append(f)
        if syms:
            logging.info("Ignoring symlinks: %s", syms)
        if not files:
            # Running with no arguments is allowed to make the repo upload hook
            # simple, but print a warning so that if someone runs this manually
            # they are aware that nothing happened.
            logging.warning("No files found to process.  Doing nothing.")
            return files

        files = self.options.filter.filter(files)
        if not files:
            logging.warning("All files are excluded.  Doing nothing.")
        return files
