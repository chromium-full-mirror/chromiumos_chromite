# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Detect unused packages in the tree so we can delete them."""

import collections
import dataclasses
import logging
import os
from pathlib import Path
import re
from typing import Dict, Iterator, List, Optional, Set

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import portage_util
from chromite.lib.parser import package_info
from chromite.utils.parser import pms_dependency
from chromite.utils.parser import portage_md5_cache


# Packages we know are actually used even if nothing depends on them.
KNOWN_PACKAGES = (
    "chromeos-base/codelab",
    "chromeos-base/sandboxing-codelab",
    "sys-libs/newlib",
    "virtual/target-sdk-implicit-system",
    "virtual/target-sdk-post-cross",
    "virtual/target-sdk-subtools",
    constants.TARGET_SDK,
    constants.TARGET_SDK_BROOT,
) + constants.ALL_TARGET_PACKAGES


# Always ignore packages in these categories.
IGNORE_CATEGORIES = {
    # Once added, we never remove.
    "acct-group",
    "acct-user",
    # Used by unittests/etc...
    "build-test",
    # Ton of DLC in here.
    "chromeos-borealis",
}


@dataclasses.dataclass()
class PackageData:
    """Various package data we care about."""

    # The full depgraph, including versions, USE constraints, etc...
    deps: pms_dependency.RootNode = dataclasses.field(
        default_factory=pms_dependency.RootNode
    )
    # All possible deps flattened into just $CATEGORY/$PN.
    flat_deps: Set[str] = dataclasses.field(default_factory=set)
    # The overlay where this package lives.
    overlays: Set[str] = dataclasses.field(default_factory=set)


def process_overlay(
    overlay: Path,
    pkgs: Dict[str, PackageData],
    ignore_category: Optional[Set[str]] = None,
) -> None:
    """Process |overlay|."""
    logging.debug("%s: checking", overlay.name)
    if ignore_category is None:
        ignore_category = set()

    # Walk all the cache files.
    for cache_file in (overlay / "metadata" / "md5-cache").glob("*/*"):
        category = cache_file.parent.name
        package_name = cache_file.name
        if category in ignore_category:
            continue
        cache = portage_md5_cache.Md5Cache(path=cache_file)
        info = package_info.parse(f"{category}/{package_name}")
        data = pkgs.setdefault(info.cp, PackageData())
        data.deps += (
            cache.depend + cache.bdepend + cache.pdepend + cache.rdepend
        )
        data.overlays.add(overlay.name)


def flatten_deps(
    pkgs: Dict[str, PackageData], ignore_use: Optional[Set[str]] = None
) -> None:
    """Flatten deps list for faster calculations later."""

    def _walk_node(
        node: pms_dependency.RootNode,
    ) -> Iterator[pms_dependency.Node]:
        for child in node.children:
            # Filter out test-only deps.
            if (
                isinstance(child, pms_dependency.UseNode)
                and child.flag in ignore_use
            ):
                pass
            if isinstance(child, pms_dependency.RootNode):
                yield from _walk_node(child)
            else:
                yield child

    stripper = re.compile(r"^[<>!=~]*(.+?)([:*[].*)?$")
    if ignore_use is None:
        ignore_use = set()

    # Walk the package's dependencies to flatten & filter unknown.
    for data in pkgs.values():
        for node in _walk_node(data.deps):
            m = stripper.match(node.name)
            assert m, node.name
            cpv = package_info.parse(m.group(1))
            assert cpv, f"{node.name} -> {m.group(1)}"
            if cpv.cp in pkgs:
                data.flat_deps.add(cpv.cp)
            # This has too many false positives on USE gated deps that we do
            # not import from Gentoo.
            # else:
            #    logging.warning("%s: broken dep on %s", data.cp, cpv.cp)


def compute_orphaned(
    pkgs: Dict[str, PackageData],
    known_pkgs: Optional[Set[str]] = None,
    ignore_pkgs: Optional[Set[str]] = None,
) -> Dict[str, PackageData]:
    """Find orphaned packages."""

    if known_pkgs is None:
        known_pkgs = set()
    if ignore_pkgs is None:
        ignore_pkgs = set()
    reverse_deps = collections.defaultdict(bool)

    # Walk the package's dependencies to count reverse depends.
    for pkg, data in pkgs.items():
        if pkg in ignore_pkgs:
            continue
        for dep in data.flat_deps:
            reverse_deps[dep] = True

    # Add synthetic deps for known packages used elsewhere (e.g. chromite).
    for pkg in known_pkgs:
        reverse_deps[pkg] = True

    # Print out all packages that don't have any users.
    return dict((k, v) for k, v in pkgs.items() if not reverse_deps[k])


def get_parser() -> commandline.ArgumentParser:
    """Get CLI parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ignore-category",
        action="split_extend",
        default=IGNORE_CATEGORIES,
        metavar="CATEGORY",
        help="CATEGORY's to filter out (default: %(default)s)",
    )
    parser.add_argument(
        "--ignore-package",
        action="split_extend",
        default=KNOWN_PACKAGES,
        metavar="PKG",
        help="Package's ($CATEGORY/$PN) to filter out (default: %(default)s)",
    )
    parser.add_argument(
        "--ignore-use",
        action="split_extend",
        metavar="USE",
        help="USE flags to filter out (default: ['test'])",
    )
    parser.add_argument(
        "--overlays",
        action="split_extend",
        help="Which overlays to analyze (default: all)",
    )
    return parser


def parse_args(argv: Optional[List[str]]) -> commandline.ArgumentParser:
    """Parse command-line args."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    if not opts.ignore_use:
        opts.ignore_use = ["test"]
    if not opts.overlays:
        opts.overlays = portage_util.FindOverlays(constants.BOTH_OVERLAYS)
    opts.overlays = {os.path.basename(x) for x in opts.overlays}
    opts.ignore_category = set(opts.ignore_category)
    opts.ignore_package = set(opts.ignore_package)
    opts.ignore_use = set(opts.ignore_use)
    opts.Freeze()
    return opts


def main(argv: Optional[List[str]]) -> Optional[int]:
    """The main entry point for scripts."""
    opts = parse_args(argv)

    logging.debug("Checking overlays: %s", " ".join(sorted(opts.overlays)))
    logging.debug("Ignoring USE flags: %s", " ".join(sorted(opts.ignore_use)))
    logging.debug(
        "Ignoring categories: %s", " ".join(sorted(opts.ignore_category))
    )

    # Load all the cache files from all overlays.
    pkgs = {}
    for overlay in (
        Path(x) for x in portage_util.FindOverlays(constants.BOTH_OVERLAYS)
    ):
        process_overlay(overlay, pkgs, opts.ignore_category)

    # Flatten the deps for easier reverse computation.
    flatten_deps(pkgs, opts.ignore_use)

    def _prune_deeper(ignore_pkgs, level=0):
        new_orphaned = (
            set(compute_orphaned(pkgs, opts.ignore_package, ignore_pkgs))
            - orphaned_pkgs
            - ignore_pkgs
        )
        if new_orphaned:
            print("  " * level, "`--", *list(new_orphaned))
            _prune_deeper(ignore_pkgs | new_orphaned, level + 1)

    # Calculate all the packages that no one depends on.
    orphaned = compute_orphaned(pkgs, opts.ignore_package)
    orphaned_pkgs = set(orphaned)
    for pkg, data in sorted(orphaned.items()):
        if not data.overlays & opts.overlays:
            continue
        print(pkg, *sorted(data.overlays))

        # If this package were dropped, would that orphan any others?
        _prune_deeper({pkg})
