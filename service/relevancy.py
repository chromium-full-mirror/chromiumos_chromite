# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implementation of builder relevancy checks using build_query."""

import dataclasses
import functools
import logging
from pathlib import Path
import re
import subprocess
from typing import Callable, Iterable, Iterator, List, Optional, Tuple

from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import relevancy_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_query
from chromite.lib import build_target_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.utils import compat


def _bootimage_enabled(build_target: build_target_lib.BuildTarget) -> bool:
    """Return true if "bootimage" is in use_flags.

    Designed for use with _PATH_RULES below.
    """
    return "bootimage" in build_target.board.use_flags


@functools.lru_cache(maxsize=1)
def _get_chromite_relevant_files() -> List[Path]:
    """Get the set of files in Chromite which are relevant to a CQ build.

    This calls the scripts/get_chromite_relevant_files script.  We subprocess
    in order to get a clean sys.modules for tracking imports.
    """
    result = cros_build_lib.run(
        [constants.CHROMITE_DIR / "scripts" / "get_chromite_relevant_files"],
        stdout=subprocess.PIPE,
        encoding="utf-8",
    )
    return [Path(x.rstrip("\n")) for x in result.stdout.splitlines()]


def _chromite_path_rule(
    _build_target: build_target_lib.BuildTarget,
    chromite_path: str,
) -> bool:
    """Path rule check for chromite relevancy."""
    return Path(chromite_path) in _get_chromite_relevant_files()


# Special rules that can be applied to paths in the tree.  Each regular
# expression (which matches a file path relative to the source checkout)
# can map to a function which determines if the change is relevant).
# The first argument of the callable is the BuildTarget under consideration.
# Regex groups are applied to the remaining arguments of the function.  If
# the function returns true, the path is considered relevant.  If it returns
# false, the path is considered irrelevant.
#
# Returns:
#     True: The change is relevant for this path.
#     False: The change is not relevant for this path.
_PATH_RULES: List[Tuple[str, Callable[..., bool]]] = [
    (r"manifest(?:-internal)?/.*\.xml", lambda _: True),
    (r"chromite/(.*)", _chromite_path_rule),
    (r"src/scripts/.*", lambda _: True),
    (
        r"src/third_party/kernel/v(\d+)\.(\d+)/.*",
        lambda bt, v1, v2: f"kernel-{v1}_{v2}" in bt.board.use_flags,
    ),
    (r"src/third_party/coreboot/.*", _bootimage_enabled),
    (r"src/platform/depthcharge/.*", _bootimage_enabled),
    (
        r"src/third_party/chromiumos-overlay/sys-boot/chromeos-bootimage/.*",
        _bootimage_enabled,
    ),
    (
        r"src/third_party/chromiumos-overlay/sys-boot/coreboot/.*",
        _bootimage_enabled,
    ),
    (
        r"src/third_party/chromiumos-overlay/sys-boot/depthcharge/.*",
        _bootimage_enabled,
    ),
    (
        r"src/third_party/chromiumos-overlay/sys-boot/edk2/.*",
        _bootimage_enabled,
    ),
    (
        r"src/third_party/chromiumos-overlay/sys-boot/libpayload/.*",
        _bootimage_enabled,
    ),
]


@functools.lru_cache(maxsize=len(_PATH_RULES))
def _re(pattern: str) -> "re.Pattern[str]":
    """Lazy & cached regex compiler for _PATH_RULES."""
    return re.compile(pattern)


ReasonPb = relevancy_pb2.GetRelevantBuildTargetsResponse.RelevantTarget.Reason


@dataclasses.dataclass
class Reason:
    """Encapsulates a single reason why a build target is relevant."""

    # The path that triggered relevancy.
    trigger: Path

    def to_proto(self) -> ReasonPb:
        """Convert to proto."""
        return ReasonPb(trigger=relevancy_pb2.Path(path=str(self.trigger)))


@dataclasses.dataclass
class ReasonPathRule(Reason):
    """The target is relevant due to a path rule."""

    # The pattern that triggered the match.
    pattern: str

    def to_proto(self) -> ReasonPb:
        pb = super().to_proto()
        pb.MergeFrom(
            ReasonPb(
                path_rule_affected=ReasonPb.PathRuleAffected(
                    pattern=self.pattern
                ),
            )
        )
        return pb

    def __str__(self) -> str:
        return (
            f"{self.trigger} modified a path which matches {self.pattern}, and "
            f"the function for that pattern considers this change relevant."
        )


@dataclasses.dataclass
class ReasonProfile(Reason):
    """The target is relevant as a profile was modified."""

    # The profile that was modified.
    profile: build_query.Profile

    def to_proto(self) -> ReasonPb:
        pb = super().to_proto()
        pb.MergeFrom(
            ReasonPb(
                profile_affected=ReasonPb.ProfileAffected(
                    profile=relevancy_pb2.Path(
                        path=str(
                            self.profile.path.relative_to(constants.SOURCE_ROOT)
                        ),
                    ),
                ),
            )
        )
        return pb

    def __str__(self) -> str:
        return (
            f"{self.trigger} modified profile {self.profile}, a profile in the "
            f"parents of this build target."
        )


@dataclasses.dataclass
class ReasonOverlay(Reason):
    """The target is relevant as an overlay was modified."""

    # The profile that was modified.
    overlay: build_query.Overlay

    def to_proto(self) -> ReasonPb:
        pb = super().to_proto()
        pb.MergeFrom(
            ReasonPb(
                overlay_affected=ReasonPb.OverlayAffected(
                    overlay=relevancy_pb2.Path(
                        path=str(
                            self.overlay.path.relative_to(constants.SOURCE_ROOT)
                        ),
                    ),
                ),
            )
        )
        return pb

    def __str__(self) -> str:
        return (
            f"{self.trigger} modified overlay {self.overlay}, an overlay in "
            f"the parents of this build target."
        )


@dataclasses.dataclass
class ReasonPackage(Reason):
    """The target is relevant as a package was modified."""

    # The profile that was modified.
    ebuild: build_query.Ebuild

    def to_proto(self) -> ReasonPb:
        pb = super().to_proto()
        package_info = common_pb2.PackageInfo()
        controller_util.serialize_package_info(
            self.ebuild.package_info, package_info
        )
        pb.MergeFrom(
            ReasonPb(
                package_affected=ReasonPb.PackageAffected(
                    package_info=package_info,
                    ebuild=relevancy_pb2.Path(
                        path=str(
                            self.ebuild.ebuild_file.relative_to(
                                constants.SOURCE_ROOT
                            )
                        ),
                    ),
                ),
            )
        )
        return pb

    def __str__(self) -> str:
        return (
            f"{self.trigger} modified package {self.ebuild}, used by this "
            f"build target."
        )


def _belongs(
    path: Path, overlays: List[build_query.Overlay]
) -> Iterator[build_query.QueryTarget]:
    """Given a relative source path in the tree, report all belonging objects.

    For a path in the tree, it may "belong" to one or more ebuilds, profiles, or
    overlays which use that source.

    Args:
        path: The relative source path in the tree.
        overlays: A list of all overlays to consider.

    Yields:
        Objects which that source path belongs to.
    """
    logging.debug("Querying belongs for %s", path)

    assert not path.is_absolute()
    path = constants.SOURCE_ROOT / path

    for overlay in overlays:
        if compat.path_is_relative_to(path, overlay.profiles_dir):
            # Iterate through all profiles in this overlay.  We must consider
            # not only the profile which is a parent path of this path, but
            # also any profiles which symlink to this profile, since portage
            # permits profiles to be symlinks.  If the path is relative to the
            # profiles directory but isn't relative to any profile, we consider
            # it an overlay change instead of a profile change.
            is_profile = False
            for profile in overlay.profiles:
                if compat.path_is_relative_to(path, profile.path.resolve()):
                    is_profile = True
                    logging.debug("%s changes profile %s", path, profile)
                    yield profile
            if is_profile:
                return
        for ebuild in overlay.ebuilds:
            if compat.path_is_relative_to(path, ebuild.ebuild_file.parent):
                logging.debug("%s changes ebuild files for %s", path, ebuild)
                yield ebuild
                return

            # We only care about non-manually-upreved unstable cros-workon
            # ebuilds for files that may have changed.
            if (
                ebuild.package_info.version != "9999"
                or not ebuild.is_workon
                or ebuild.is_manually_uprevved
            ):
                continue

            subtrees = [Path(x) for x in ebuild.source_info.subtrees]
            for subtree in subtrees:
                if compat.path_is_relative_to(path, subtree):
                    logging.debug("%s changes a subtree of %s", path, ebuild)
                    yield ebuild
        if compat.path_is_relative_to(path, overlay.path):
            logging.debug("%s is an overlay change for %s", path, overlay)
            yield overlay


def _get_belongs_set(
    paths: Iterable[Path],
) -> Iterator[Tuple[Path, build_query.QueryTarget]]:
    """For a set of paths modified in the tree, get the belongs set.

    The belongs set is the set of unique QueryTarget objects that is affected by
    the change.

    Args:
        paths: The list of relative paths modified.

    Yields:
        Tuples containing the Path that created the belong, and a QueryTarget
        object (the belong).
    """
    paths = list(paths)
    assert all(not x.is_absolute() for x in paths)
    all_overlays = list(build_query.Overlay.find_all())

    found_belongs = set()
    for path in paths:
        for belong in _belongs(path, all_overlays):
            type_and_str = (type(belong), str(belong))
            if type_and_str in found_belongs:
                continue
            found_belongs.add(type_and_str)
            yield path, belong


def _profile_contains_profile(
    haystack: build_query.Profile,
    needle: build_query.Profile,
) -> bool:
    """Does a profile contain another profile in its parents (recursively)?

    Args:
        haystack: The profile which might contain the needle.
        needle: The profile to search for in the haystack.

    Returns:
        True if the needle is in the haystack, false otherwise.
    """
    if needle == haystack:
        return True
    for parent in haystack.parents:
        if _profile_contains_profile(parent, needle):
            return True
    return False


def _belong_applies_to_target(
    path: Path,
    belong: build_query.QueryTarget,
    build_target: build_target_lib.BuildTarget,
) -> Optional[Reason]:
    """Does a belong make a build target applicable?

    Args:
        path: A path which resulted in the belong.
        belong: The belong in question.
        build_target: The build target to consider.

    Returns:
        A reason if the build target is applicable, None otherwise.
    """
    if isinstance(belong, build_query.Profile):
        profile = build_target.board.top_level_profile
        if profile and _profile_contains_profile(profile, belong):
            return ReasonProfile(trigger=path, profile=belong)
    if isinstance(belong, build_query.Overlay):
        if belong in build_target.board.overlays:
            return ReasonOverlay(trigger=path, overlay=belong)
    if isinstance(belong, build_query.Ebuild):
        # Eventually, we can implement depgraph logic for this.  For now, we
        # just consider ebuild presence in one of the boards overlays.
        if belong.overlay in build_target.board.overlays:
            return ReasonPackage(trigger=path, ebuild=belong)
    return None


def get_relevant_build_targets(
    considered: Iterable[build_target_lib.BuildTarget],
    paths: Iterable[Path],
) -> Iterator[Tuple[build_target_lib.BuildTarget, Reason]]:
    """Get the relevant build targets for a change.

    Args:
        considered: All build targets to consider.
        paths: All modified paths, relative to the source root.

    Yields:
        Tuples for each relevant build target, containing the target and the
        reason.
    """
    considered = list(considered)

    # Path rules are evaluated first, prior to considering any belongs.  Build
    # targets matched by a path rule are not considered when looking at belongs.
    paths = set(paths)
    considered = set(considered)
    for path in list(paths):
        for pattern, func in _PATH_RULES:
            match = _re(pattern).fullmatch(str(path))
            if match:
                # If a path matches any path rule, that means we shouldn't
                # consider the regular belongs logic for that path.  We discard
                # it from the path set.
                paths.discard(path)

                logging.debug(
                    "Using path rule %s to evaluate relevancy for %s",
                    pattern,
                    path,
                )

                for build_target in list(considered):
                    result = func(build_target, *match.groups())
                    if result:
                        logging.debug(
                            "%s is applicable to %s by path rule %s",
                            path,
                            build_target,
                            pattern,
                        )
                        considered.discard(build_target)
                        yield build_target, ReasonPathRule(
                            trigger=path, pattern=pattern
                        )

                # Once any path rule matches a path, we shall consider no more
                # path rules for that path.
                break

    # If no build targets or no paths remain to consider after applying path
    # rules, don't bother computing the belongs set.
    if not considered or not paths:
        return

    belongs = list(_get_belongs_set(paths))

    for build_target in considered:
        for path, belong in belongs:
            reason = _belong_applies_to_target(path, belong, build_target)
            if reason:
                logging.debug("%s is applicable for %s", belong, build_target)
                yield build_target, reason
                break
