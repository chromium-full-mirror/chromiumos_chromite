# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Regenerate the build metadata cache.

This script runs egencache on all overlays, regenerating the metadata/md5-cache
directory.

Updated overlays are printed as relative paths to the source root on stdout,
one per line.
"""

import contextlib
import os
from pathlib import Path
import sys
from typing import List, Optional, TextIO

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import portage_util
from chromite.utils import key_value_store


def run_egencache(
    repo_name: str,
    repos_conf: Path,
) -> cros_build_lib.CompletedProcess:
    """Execute egencache for repo_name inside the chroot.

    Args:
        repo_name: Name of the repo for the overlay.
        repos_conf: repos.conf file.

    Returns:
        A cros_build_lib.CompletedProcess object.
    """
    return cros_build_lib.run(
        [
            "egencache",
            "--repos-conf",
            repos_conf,
            "--update",
            "--repo",
            repo_name,
            "--jobs",
            str(os.cpu_count()),
        ]
    )


def generate_repos_conf(output: TextIO) -> None:
    """Make a repos.conf file with all overlays for egencache.

    Generate the repositories configuration containing every overlay in the same
    format as repos.conf so egencache can produce an md5-cache for every overlay
    The repositories configuration can be accepted as a string in egencache.

    Args:
        output: A file-like object opened for writing.  The config will be
            written here.
    """
    overlays = portage_util.FindOverlays(constants.BOTH_OVERLAYS)
    for overlay_path in overlays:
        overlay_name = portage_util.GetOverlayName(overlay_path)
        output.write(f"[{overlay_name}]\nlocation = {overlay_path}\n")


def regen_overlay_cache(
    overlay: Path,
    repos_conf: Path,
) -> Optional[Path]:
    """Regenerate the cache of the specified overlay.

    Args:
        overlay: The tree to regenerate the cache for.
        repos_conf: repos.conf file.

    Returns:
        The overlay when there are were changes made changes, or None when there
        were no updates. This is meant to be a simple, parallelism-friendly
        means of identifying which overlays have been changed.
    """
    repo_name = portage_util.GetOverlayName(overlay)
    if not repo_name:
        return None

    layout = key_value_store.LoadFile(
        overlay / "metadata" / "layout.conf",
        ignore_missing=True,
    )
    if layout.get("cache-format") != "md5-dict":
        return None

    # Regen for the whole repo.
    run_egencache(repo_name, repos_conf=repos_conf)

    # If there was nothing new generated, then let's just bail.
    result = git.RunGit(overlay, ["status", "-s", "metadata/"])
    if not result.stdout:
        return None

    return overlay


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--overlay-type",
        choices=[
            constants.PUBLIC_OVERLAYS,
            constants.PRIVATE_OVERLAYS,
            constants.BOTH_OVERLAYS,
        ],
        default=constants.BOTH_OVERLAYS,
        help="Overlay type to update.",
    )
    return parser


def parse_arguments(argv: Optional[List[str]]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()
    return opts


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    commandline.RunInsideChroot()
    opts = parse_arguments(argv)

    with osutils.TempDir() as tempdir:
        repos_conf = Path(tempdir) / "repos.conf"
        with repos_conf.open("w", encoding="utf-8") as f:
            generate_repos_conf(f)

        task_inputs = [
            (Path(x), repos_conf)
            for x in portage_util.FindOverlays(opts.overlay_type)
        ]

        # chromite.lib.parallel is hardwired to mix stderr into stdout.  Send it
        # back to the right place.
        with contextlib.redirect_stdout(sys.stderr):
            results = parallel.RunTasksInProcessPool(
                regen_overlay_cache, task_inputs
            )

    for result in results:
        if result:
            print(result.relative_to(constants.SOURCE_ROOT))
