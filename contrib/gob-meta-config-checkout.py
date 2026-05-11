#!/usr/bin/env python3
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Generate tree for working with refs/meta/config.

# To checkout refs/meta/config for all projects in the chromium GoB:
$ ./gob-meta-config-checkout.py --output ~/src/gob/chromium chromium

Rerunning the command on an existing output will refresh & update new projects.
"""

import argparse
import configparser
import contextlib
import errno
import functools
import io
import multiprocessing
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Callable, Iterable
import urllib.request


assert sys.version_info >= (3, 11), "Python 3.11+ required"


# Terminal escape sequence to erase the current line after the cursor.
CSI_ERASE_LINE_AFTER = "\x1b[K"


def print_status(msg: str, *args, **kwargs) -> None:
    """Print a status message with terminal status lines."""
    if "flush" not in kwargs and kwargs.get("end") == "":
        kwargs["flush"] = True
    print(f"\r{msg} {CSI_ERASE_LINE_AFTER}", *args, **kwargs)


class GitConfig:
    """Access to .git/config settings."""

    def __init__(self, path: Path) -> None:
        self.path = path / ".git" / "config"
        self.config = configparser.ConfigParser()
        self.read()

    def read(self) -> None:
        if self.path.exists():
            self.config.read(self.path)

    @staticmethod
    def key_to_section_option(key: str) -> tuple[str, str]:
        section, option = key.split(".", 1)
        if section in {"remote", "branch"}:
            qual, option = option.split(".", 1)
            section = f'{section} "{qual}"'
        return (section, option)

    def get(self, key: str):
        return self.config.get(*self.key_to_section_option(key))

    def set(self, key: str, value: str) -> None:
        run(["git", "config", key, value], cwd=self.path.parent)
        self.read()

    def exists(self, key: str) -> bool:
        return self.config.has_option(*self.key_to_section_option(key))

    def setdefault(self, key: str, value: str) -> None:
        if not self.exists(key):
            self.set(key, value)


def run(cmd: list[str], auto_output=True, **kwargs):
    """Hook around subprocess.run for logging."""
    cwd = kwargs.get("cwd")
    assert cwd is not None, f"{cmd} missing cwd="
    # print(cmd, f'cwd={cwd}', flush=True)
    kwargs.setdefault("check", True)
    if "capture_output" not in kwargs:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.STDOUT)
    kwargs.setdefault("encoding", "utf-8")
    ret = subprocess.run(cmd, **kwargs)  # pylint: disable=subprocess-run-check
    if auto_output and not kwargs.get("capture_output"):
        output = ret.stdout.strip()
        if output and "using GSLB fallback backend" not in output:
            print(output)
    return ret


def get_hook_commit_msg(opts: argparse.Namespace) -> Path:
    """Get a cache of the commit-msg hook."""
    commit_msg = opts.output / ".commit-msg"
    if not commit_msg.exists():
        opts.output.mkdir(0o755, exist_ok=True)
        with urllib.request.urlopen(
            "https://gerrit-review.googlesource.com/tools/hooks/commit-msg"
        ) as response:
            commit_msg.write_bytes(response.read())
        commit_msg.chmod(0o755)
    return commit_msg


def create_repo(opts: argparse.Namespace, repo: Path) -> None:
    """Initialize |repo|."""
    path = opts.output / repo
    gitdir = path / ".git"
    hooks = gitdir / "hooks"
    commit_msg = hooks / "commit-msg"

    # Only run the init steps once.
    if commit_msg.exists():
        # Automatically rebase as it's common for commits to be merged and get
        # a different commit id.
        try:
            run(["git", "pull", "-q", "--rebase"], cwd=path, auto_output=False)
        except subprocess.CalledProcessError:
            run(
                ["git", "rebase", "--abort"],
                cwd=path,
                auto_output=False,
                check=False,
            )
            # This is a reserved project that no one really gets access to.
            if str(repo) != "All-Users":
                raise
        return

    path.mkdir(parents=True, exist_ok=True)
    if not gitdir.exists():
        run(["git", "init", "-q", path], cwd=path)
    for hook in hooks.glob("*.sample"):
        hook.unlink()
    config = GitConfig(path)
    uri = f"rpc://{opts.gob}/{repo}"
    if not config.exists("remote.origin.url"):
        run(["git", "remote", "add", "origin", uri], cwd=path)
    config.set(
        "remote.origin.fetch",
        "+refs/meta/config:refs/remotes/origin/meta-config",
    )
    config.set("remote.origin.push", "HEAD:refs/meta/config")
    if not config.exists("remote.review.url"):
        config.set("remote.review.url", uri)
    if not config.exists("remote.review.push"):
        config.set("remote.review.push", "HEAD:refs/for/refs/meta/config")

    orphan = False
    result = run(
        ["git", "rev-parse", "remotes/origin/meta-config"],
        cwd=path,
        check=False,
        auto_output=False,
    )
    if result.returncode:
        if result.returncode != 128:
            result.check_returncode()

        # If it doesn't exist in the remote, the project might not have been
        # initialized by Gerrit.
        result = run(
            ["git", "fetch", "-q", "origin"],
            cwd=path,
            check=False,
            auto_output=False,
        )
        if result.returncode:
            if result.returncode != 128:
                result.check_returncode()

            # Remote doesn't exist yet, so we have to fake it.
            orphan = True

    cmd = ["git", "checkout", "-q"]
    if orphan:
        cmd += ["--orphan", "meta-config"]
        run(["git", "config", "branch.meta-config.remote", "origin"], cwd=path)
        run(
            ["git", "config", "branch.meta-config.merge", "refs/meta/config"],
            cwd=path,
        )
    else:
        cmd += ["-b", "meta-config", "remotes/origin/meta-config"]
    run(cmd, cwd=path)

    # Do this last as a marker that we finished initializing.
    if not commit_msg.exists():
        commit_msg.symlink_to(get_hook_commit_msg(opts))


def check_repo(opts: argparse.Namespace, repo: Path) -> None:
    """Check the current |repo| status."""
    path = opts.output / repo
    gitdir = path / ".git"

    if not gitdir.is_dir():
        return

    result = run(["git", "status", "--short"], cwd=path, capture_output=True)
    for line in result.stdout.splitlines():
        if line.startswith("??") and line.endswith("/"):
            continue
        print(line)
    result = run(
        ["git", "rev-list", "--count", "origin/meta-config..HEAD"],
        cwd=path,
        capture_output=True,
    )
    if result.stdout.strip() != "0":
        run(["git", "branch", "--verbose"], cwd=path)


def capture_output(func: Callable, repo: Path):
    output = io.StringIO()
    with contextlib.redirect_stderr(sys.stdout):
        with contextlib.redirect_stdout(output):
            try:
                func(repo)
            except subprocess.CalledProcessError as e:
                output.write(f"\n{repo}: {e.cmd}={e.returncode}: {e.stdout}")
            except Exception as e:
                output.write(f"\n{repo}: Exception: {e}")
    return (repo, output.getvalue())


def cleanup_old_projects(
    opts: argparse.Namespace, live_repos: set[Path]
) -> None:
    """Prune old projects that have been archived or deleted from the host."""
    local_repos = set(
        x.relative_to(opts.output).parent for x in opts.output.glob("**/.git/")
    )
    # We run in reverse to clear subdirs before parents.
    old_repos = sorted(local_repos - live_repos, reverse=True)
    num_repos = len(old_repos)
    for i, repo in enumerate(old_repos, start=1):
        print_status(
            f"[{i}/{num_repos}] Removing old {repo}",
            end="",
        )
        root = opts.output / repo

        # We can't delete the tree entirely as it might have nested projects.
        # List the files to remove manually instead.
        result = subprocess.run(
            ["git", "ls-tree", "--name-only", "-r", "-z", "HEAD"],
            cwd=root,
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

        # Not all git trees are initialized with content.
        if result.returncode == 0:
            # Strip off trailing NULs to avoid "" entries.
            paths = result.stdout.strip("\0").split("\0")
        elif result.returncode == 128:
            paths = []
        else:
            result.check_returncode()

        for path in paths:
            (root / path).unlink(missing_ok=True)
        shutil.rmtree(root / ".git")

        # Prune empty dirs in case this archived project was in an unique tree.
        while True:
            try:
                root.rmdir()
            except OSError as e:
                if e.errno != errno.ENOTEMPTY:
                    raise
                break
            root = root.parent


def get_repos(gob: str) -> Iterable[Path]:
    """Get all the repos on this host."""
    result = run(
        ["gob-ctl", "list", gob], cwd="/", encoding="utf-8", capture_output=True
    )
    # Pull out lines like:
    #  repo: "chromium/chromiumos/platform2"
    REPO_RE = re.compile('^ *repo: *"(.*)"')
    for line in result.stdout.splitlines():
        m = REPO_RE.match(line)
        if m:
            repo = m.group(1)
            assert repo.startswith(f"{gob}/")
            yield Path(repo[len(gob) + 1 :])


def get_parser() -> argparse.ArgumentParser:
    """Get CLI parser."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=min(8, multiprocessing.cpu_count()),
        help="Number of jobs to run in parallel (default: %(default)s)",
    )
    parser.add_argument(
        "--filter",
        default=".*",
        help="Only process repos matching this regex",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show git status instead of updating",
    )
    parser.add_argument(
        "--output", type=Path, help="The root directory to write to"
    )
    parser.add_argument("gob", help="The GoB hostname")
    return parser


def main(argv) -> None:
    """The main entry point for scripts."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    if not opts.output:
        opts.output = Path.cwd() / opts.gob

    print_status("Gathering project list ...", end="")
    live_repos = set(get_repos(opts.gob))

    print_status("Cleaning old projects ...", end="")
    cleanup_old_projects(opts, live_repos)

    # Cache the hook once.
    print_status("Caching commit-msg hook ...", end="")
    get_hook_commit_msg(opts)

    if opts.status:
        func = functools.partial(check_repo, opts)
    else:
        func = functools.partial(create_repo, opts)

    # Prioritize missing projects.
    all_repos = {x for x in live_repos if re.fullmatch(opts.filter, str(x))}
    missing_repos = {x for x in all_repos if not (opts.output / x).is_dir()}
    repos = sorted(missing_repos) + sorted(all_repos - missing_repos)

    capture = functools.partial(capture_output, func)
    with multiprocessing.Pool(opts.jobs) as pool:
        finished = 0
        num_repos = len(repos)
        for repo, output in pool.imap_unordered(capture, repos):
            finished += 1
            print_status(
                f"[{finished}/{num_repos}] {repo}",
                output,
                end="\n" if output else "",
            )
    print()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
