# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Shared helpers for cros analyzer commands (fix, lint, format)."""

from abc import ABC
import logging
from pathlib import Path
from typing import List

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import git


def _GetFilesFromCommit(commit: str) -> List[str]:
    """Returns ths files changed in the provided git `commit`."""
    return git.RunGit(
        None,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", commit],
    ).stdout.splitlines()[:-1]


class AnalyzerCommand(ABC, command.CliCommand):
    """Shared argument parsing for cros analyzers (fix, lint, format)."""

    use_dryrun_options = True
    # Override base class property to use path filter options.
    use_filter_options = True

    @classmethod
    def AddParser(cls, parser):
        super().AddParser(parser)
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
            "--stdout",
            dest="inplace",
            action="store_false",
            help="Write to stdout",
        )
        parser.add_argument(
            "-i",
            "--inplace",
            default=True,
            action="store_true",
            help="Fix files inplace (default)",
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
        if options.commit and not options.files:
            options.files = _GetFilesFromCommit(options.commit)

        if not options.files:
            # Running with no arguments is allowed to make the repo upload hook
            # simple, but print a warning so that if someone runs this manually
            # they are aware that nothing was changed.
            logging.warning("No files provided.  Doing nothing.")
