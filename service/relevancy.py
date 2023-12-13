# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implementation of builder relevancy checks using build_query."""

import dataclasses
import logging
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple

from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import relevancy_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_query
from chromite.lib import build_target_lib
from chromite.lib import constants
from chromite.utils import compat


# A list of paths in the tree that "belongs to everything" (i.e., we want to
# consider all build targets relevant for).
_BELONGS_ALL = [
    Path("chromite"),
    Path("src/scripts"),
    Path("manifest"),
    Path("manifest-internal"),
]


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
class ReasonFundamental(Reason):
    """The target is relevant as a path is in _BELONGS_ALL."""

    # The subtree from _BELONGS_ALL.
    subtree: Path

    def to_proto(self) -> ReasonPb:
        pb = super().to_proto()
        pb.MergeFrom(
            ReasonPb(
                build_tool_affected=ReasonPb.BuildToolAffected(
                    subtree=relevancy_pb2.Path(path=str(self.subtree)),
                ),
            )
        )
        return pb

    def __str__(self) -> str:
        return (
            f"{self.trigger} modified a path under {self.subtree}, which is "
            f"considered to be a fundamental path that affects all targets."
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
        if (
            compat.path_is_relative_to(path, overlay.profiles_dir)
            and path.parent != overlay.profiles_dir
        ):
            logging.debug("%s is a profile", path)
            profile_path = path.parent.relative_to(overlay.profiles_dir)
            # Profiles may contain directories.  See PMS: PROFILE-FILE-DIRS.
            if profile_path.name.startswith(
                "package."
            ) or profile_path.name.startswith("use."):
                profile_path = profile_path.parent
            profile = overlay.get_profile(profile_path)
            if profile:
                yield profile
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
    paths = list(paths)

    for path in paths:
        for subtree in _BELONGS_ALL:
            if compat.path_is_relative_to(path, subtree):
                reason_fundamental = ReasonFundamental(
                    trigger=path, subtree=subtree
                )
                for build_target in considered:
                    yield build_target, reason_fundamental
                return

    belongs = list(_get_belongs_set(paths))

    for build_target in considered:
        for path, belong in belongs:
            reason = _belong_applies_to_target(path, belong, build_target)
            if reason:
                logging.debug("%s is applicable for %s", belong, build_target)
                yield build_target, reason
                break
