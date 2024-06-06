# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Python API for `cros query`."""

from __future__ import annotations

import abc
import dataclasses
import enum
import functools
import logging
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    TYPE_CHECKING,
    Union,
)

from chromite.lib import constants
from chromite.lib import git
from chromite.lib import portage_util
from chromite.lib.parser import package_info
from chromite.utils import key_value_store
from chromite.utils.parser import make_defaults
from chromite.utils.parser import portage_md5_cache
from chromite.utils.parser import portage_profile_conf


if TYPE_CHECKING:
    import os


# We use docstrings in this file frequently for property documentation, which
# doesn't follow the traditional format of leaving the second line blank used
# with traditional functions/methods.
# pylint: disable=docstring-second-line-blank


class Stability(enum.Enum):
    """Enumeration for package stability.

    UNSPECIFIED: The stability for this architecture was not listed in KEYWORDS.
    STABLE: The package is well tested on this architecture.
    UNSTABLE: The package may not have complete testing on this architecture.
    BAD: The package has known issues with this architecture.
    """

    UNSPECIFIED = enum.auto()
    STABLE = enum.auto()
    UNSTABLE = enum.auto()
    BAD = enum.auto()


class QueryTarget(abc.ABC):
    """Abstract base class for all query targets."""

    @classmethod
    @abc.abstractmethod
    def find_all(
        cls,
        board: Optional[str] = None,
        overlays: str = constants.BOTH_OVERLAYS,
    ) -> Iterator[QueryTarget]:
        """Find all instances of this target.

        Args:
            board: Limit results to only those relevant to a named
                board.
            overlays: Limit overlays to the specified type.

        Yields:
            Instances of this class.
        """

    def tree(self) -> Iterator[QueryTarget]:
        """Yield any relevant children for the tree-view from the CLI."""
        yield from ()


@dataclasses.dataclass(frozen=True)
class Overlay(QueryTarget):
    """An overlay, e.g., src/third_party/chromiumos-overlay."""

    path: Path

    @classmethod
    def find_all(
        cls,
        board: Optional[str] = None,
        overlays: str = constants.BOTH_OVERLAYS,
    ) -> Iterator[Overlay]:
        try:
            for overlay_path in portage_util.FindOverlays(
                overlays, board=board
            ):
                yield cls(Path(overlay_path))
        except portage_util.MissingOverlayError:
            assert board
            logging.debug("No overlays found for board=%s", board)

    def tree(self) -> Iterator[Overlay]:
        yield from self.parents

    @functools.cached_property
    def layout_conf(self) -> Dict[str, str]:
        """The layout.conf variables."""
        return key_value_store.LoadFile(
            self.path / "metadata" / "layout.conf", ignore_missing=True
        )

    @functools.cached_property
    def parents(self) -> List[Overlay]:
        """The Portage masters of this overlay.  Note the COIL rename."""
        all_overlays = _get_all_overlays_by_name()
        parents = []
        for name in self.layout_conf.get("masters", "").split():
            if name:
                parents.append(all_overlays[name])
        return parents

    @functools.cached_property
    def name(self) -> str:
        """The repo-name in metadata/layout.conf."""
        return portage_util.GetOverlayName(self.path) or ""

    @property
    def is_private(self) -> bool:
        """True if the overlay appears to be private, false otherwise."""
        return self.name.endswith("-private")

    @property
    def board_name(self) -> Optional[str]:
        """If this overlay is a top-level overlay for a board, the name of that
        board.  Otherwise, this is None.
        """
        if not self.path.name.startswith("overlay-"):
            return None
        if self.is_private:
            board_name, _, _ = self.name.rpartition("-")
            return board_name
        return self.name

    @property
    def profiles_dir(self) -> Path:
        """The profiles directory for this overlay."""
        return self.path / "profiles"

    @property
    def metadata_dir(self) -> Path:
        """The metadata directory for this overlay."""
        return self.path / "metadata"

    @property
    def md5_cache_dir(self) -> Path:
        """The md5-cache directory for this overlay."""
        return self.metadata_dir / "md5-cache"

    @functools.cached_property
    def profiles(self) -> List[Profile]:
        """A list of all profiles defined in this overlay."""
        if not self.profiles_dir.is_dir():
            return []

        def _scan_profiles(path: Path) -> Iterator[Profile]:
            is_profile = False
            for ent in path.iterdir():
                if ent.is_dir():
                    yield from _scan_profiles(ent)
                elif ent.is_file():
                    if ent.name in (
                        "parent",
                        "eapi",
                        "deprecated",
                        "make.defaults",
                        "packages",
                        "packages.build",
                        "packages.mask",
                        "package.provided",
                        "package.use",
                        "use.mask",
                        "use.force",
                        "use.stable.mask",
                        "use.stable.force",
                        "package.use.mask",
                        "package.use.force",
                        "package.use.stable.mask",
                        "package.use",
                    ):
                        is_profile = True
            if is_profile:
                yield Profile(
                    str(path.relative_to(self.profiles_dir)), path, self
                )

        return list(_scan_profiles(self.profiles_dir))

    def get_profile(
        self, name: Union[str, "os.PathLike[str]"]
    ) -> Optional[Profile]:
        """Get a specific profile by name.

        Args:
            name: The name of the profile (e.g., "base").

        Returns:
            The Profile object with this name, or None if this profile does not
            exist.
        """
        profile_dir = self.path / "profiles" / name
        if profile_dir.is_dir():
            return Profile(str(name), profile_dir, self)
        return None

    @functools.cached_property
    def ebuilds(self) -> List[Ebuild]:
        """A list of all ebuilds in this overlay."""
        ebuilds = []
        for ebuild_path in self.path.glob("*/*/*.ebuild"):
            ebuilds.append(Ebuild(ebuild_file=ebuild_path, overlay=self))
        return ebuilds

    @functools.cached_property
    def make_conf_vars(self) -> Dict[str, str]:
        """The variables defined in make.conf."""
        make_conf_path = self.path / "make.conf"
        if make_conf_path.is_file():
            contents = make_conf_path.read_text(encoding="utf-8")
            return make_defaults.parse(contents)
        return {}

    def __repr__(self) -> str:
        return str(self.path)


@functools.lru_cache(maxsize=None)
def _get_all_overlays_by_name() -> Dict[str, Overlay]:
    """Get all overlays, in a dictionary by name.

    Returns:
        A dictionary mapping overlay names to the Overlay objects.
    """
    overlays = {}
    for overlay in Overlay.find_all():
        overlays[overlay.name] = overlay
    return overlays


class Profile(QueryTarget):
    """A portage profile, e.g., chromiumos:base."""

    _obj_cache: Dict[Path, Profile] = {}

    def __new__(cls, _name: str, path: Path, _overlay: Overlay) -> Profile:
        # Caching the construction of profiles prevents a re-parse of
        # make.defaults when a profile is inherited multiple times,
        # which provides a significant speed-up during many queries.
        if path not in cls._obj_cache:
            cls._obj_cache[path] = super().__new__(cls)
        return cls._obj_cache[path]

    def __init__(self, name: str, path: Path, overlay: Overlay) -> None:
        self.name = name
        self.path = path
        self.overlay = overlay

    @classmethod
    def find_all(
        cls,
        board: Optional[str] = None,
        overlays: str = constants.BOTH_OVERLAYS,
    ) -> Iterator[Profile]:
        for overlay in Overlay.find_all(board=board, overlays=overlays):
            yield from overlay.profiles

    @functools.cached_property
    def make_defaults_vars(self) -> Dict[str, str]:
        """A dictionary of the raw make.defaults variables."""
        make_defaults_path = self.path / "make.defaults"
        if make_defaults_path.is_file():
            contents = make_defaults_path.read_text(encoding="utf-8")
            return make_defaults.parse(contents)
        return {}

    def resolve_var(
        self, var: str, default: Optional[str] = None
    ) -> Optional[str]:
        """Resolve a variable for this profile, similar to how Portage would.

        Note: this function resolves variables non-incrementally.  For
        incremental variables (e.g., USE, USE_EXPAND, etc), use
        resolve_var_incremental.

        Args:
            var: The variable to resolve.
            default: What to return if the variable is not set.

        Returns:
            The resolved variable.
        """
        if var in self.make_defaults_vars:
            return self.make_defaults_vars[var]
        for profile in reversed(self.parents):
            result = profile.resolve_var(var)
            if result is not None:
                return result
        return default

    def resolve_var_incremental(self, var: str) -> Set[str]:
        """Resolve a variable incrementally, similar to how Portage would.

        This will traverse the profiles depth-first, adding tokens which are not
        prefixed with a dash, and removing those which are.

        Args:
            var: The variable to resolve.

        Returns:
            The resolved variable, as a set of the tokens.
        """
        result: Set[str] = set()

        # portage_testables creates recursive overlays.  We don't technically
        # need to track visited overlays for well-formed overlays.
        visited_overlays: Set[str] = set()

        def _process_tokens(tokens: Iterable[str]) -> None:
            for token in tokens:
                if not token:
                    # Variable was unset, empty, or just whitespace.
                    continue
                if token == "-*":
                    result.clear()
                elif token.startswith("-"):
                    result.discard(token[1:])
                else:
                    result.add(token)

        def _rec_profile(profile: Profile) -> None:
            tokens = profile.make_defaults_vars.get(var, "").split()
            if "-*" not in tokens:
                for parent in profile.parents:
                    _rec_profile(parent)
            _process_tokens(tokens)

        def _rec_overlay(overlay: Overlay) -> None:
            if overlay.name in visited_overlays:
                return
            visited_overlays.add(overlay.name)

            for parent in overlay.parents:
                _rec_overlay(parent)

            tokens = overlay.make_conf_vars.get(var, "").split()
            _process_tokens(tokens)

        _rec_profile(self)
        _rec_overlay(self.overlay)
        return result

    @property
    def arch(self) -> str:
        """The machine architecture of this profile."""
        return self.resolve_var("ARCH") or ""

    def _use_flag_changes(self) -> Tuple[Set[str], Set[str]]:
        """Compute the USE flags changed by this profile.

        Returns:
            A 2-tuple: the set of flags set, and the flags unset.
        """
        flags_set: Set[str] = set()
        flags_unset: Set[str] = set()

        def _process_flag(flag: str, prefix: str = "") -> None:
            flag_set = True
            if not flag:
                return
            if flag.startswith("-"):
                flag = flag[1:]
                flag_set = False
            flag = prefix + flag
            if flag_set:
                flags_unset.discard(flag)
                flags_set.add(flag)
            else:
                flags_unset.add(flag)
                flags_set.discard(flag)

        for flag in self.make_defaults_vars.get("USE", "").split():
            _process_flag(flag)

        use_expand = self.resolve_var_incremental("USE_EXPAND")
        for var in use_expand:
            for val in self.make_defaults_vars.get(var.upper(), "").split():
                _process_flag(val, prefix=f"{var.lower()}_")

        flags_set.update(self.forced_use_flags)
        flags_unset.difference_update(self.forced_use_flags)

        return flags_set, flags_unset

    @property
    def use_flags_set(self) -> Set[str]:
        """A set of what USE flags this profile enables."""
        flags_set, _ = self._use_flag_changes()
        return flags_set

    @property
    def use_flags_unset(self) -> Set[str]:
        """A set of what USE flags this profile disables."""
        _, flags_unset = self._use_flag_changes()
        return flags_unset

    # TODO(b/236161656): Fix.
    # pylint: disable-next=cache-max-size-none
    @functools.lru_cache(maxsize=None)
    def _parse_conf(self, name: str) -> List[List[str]]:
        """Parse a basic conf file, such as parent, use.mask, or use.force."""
        file_path = self.path / name
        if not file_path.is_file():
            return []
        contents = file_path.read_text(encoding="utf-8")
        return list(portage_profile_conf.parse(contents))

    def _resolve_use_conf(self, name: str) -> Set[str]:
        """Resolve a use.mask or use.force file."""
        result: Set[str] = set()

        def _rec(profile: Profile) -> None:
            for parent in profile.parents:
                _rec(parent)
            # pylint: disable=protected-access
            for (flag,) in profile._parse_conf(name):
                if flag.startswith("-"):
                    result.discard(flag[1:])
                else:
                    result.add(flag)

        _rec(self)
        return result

    @property
    def masked_use_flags(self) -> Set[str]:
        """The resolved set of masked USE flags for this profile."""
        return self._resolve_use_conf("use.mask")

    @property
    def forced_use_flags(self) -> Set[str]:
        """The resolved set of forced USE flags for this profile."""
        return self._resolve_use_conf("use.force")

    @property
    def use_flags(self) -> Set[str]:
        """A set of the fully-resolved USE flags for this profile."""
        use_flags = set(self.resolve_var_incremental("USE"))
        use_expand = self.resolve_var_incremental("USE_EXPAND")
        for var in use_expand:
            expansions = self.resolve_var_incremental(var.upper())
            for val in expansions:
                use_flags.add(f"{var.lower()}_{val}")

        use_flags.difference_update(self.masked_use_flags)
        use_flags.update(self.forced_use_flags)

        return use_flags

    @functools.cached_property
    def parents(self) -> List[Profile]:
        """A list of the immediate parent profiles of this profile."""
        parents = []
        for tokens in self._parse_conf("parent"):
            if len(tokens) != 1:
                logging.warning(
                    "Profile %r has invalid parent configuration: %r",
                    self,
                    tokens,
                )
                continue
            if ":" in tokens[0]:
                repo_name, _, profile_name = tokens[0].partition(":")
                overlays = _get_all_overlays_by_name()
                overlay = overlays.get(repo_name)
                if not overlay:
                    logging.warning(
                        "Profile %r has parent %r, but %r isn't an overlay.",
                        self,
                        tokens[0],
                        repo_name,
                    )
                    continue
                profile = overlay.get_profile(profile_name)
            else:
                path = (self.path / Path(tokens[0])).resolve()
                path = path.relative_to(self.overlay.profiles_dir)
                profile = self.overlay.get_profile(path)
            if not profile:
                continue
            parents.append(profile)
        return parents

    def tree(self) -> Iterator[Profile]:
        yield from self.parents

    def __repr__(self) -> str:
        return f"{self.overlay.name}:{self.name}"


class Ebuild(QueryTarget):
    """An ebuild, fully qualified by ebuild file.

    Note: This implementation relies on the md5-cache files, which are updated
    by a builder every 30 minutes.  Thus, if you've made changes locally, they
    may not be reflected in the query immediately.  Run egencache in the overlay
    to regenerate these cache files manually, should you require it.
    """

    ebuild_file: Path
    overlay: Overlay

    def __init__(self, ebuild_file: Path, overlay: Overlay) -> None:
        self.ebuild_file = ebuild_file
        self.overlay = overlay
        self._md5_cache = None

    @classmethod
    def find_all(
        cls,
        board: Optional[str] = None,
        overlays: str = constants.BOTH_OVERLAYS,
    ) -> Iterator[Ebuild]:
        for overlay in Overlay.find_all(board=board, overlays=overlays):
            yield from overlay.ebuilds

    @functools.cached_property
    def package_info(self) -> package_info.PackageInfo:
        """The PackageInfo for this ebuild."""
        return package_info.parse(self.ebuild_file)

    @functools.cached_property
    def portage_ebuild(self) -> portage_util.EBuild:
        """Get the portage_util.EBuild corresponding to this ebuild.

        Note this object is significantly less ergonomic to work with than a
        build_query.Ebuild.
        """
        return portage_util.EBuild(str(self.ebuild_file))

    @functools.cached_property
    def source_info(self) -> portage_util.SourceInfo:
        """The SourceInfo for this ebuild."""
        return self.portage_ebuild.GetSourceInfo(
            constants.SOURCE_ROOT / "src",
            git.ManifestCheckout.Cached(constants.SOURCE_ROOT),
        )

    @property
    def is_workon(self) -> bool:
        """True if this is a cros-workon ebuild."""
        return self.portage_ebuild.is_workon

    @property
    def is_manually_uprevved(self) -> bool:
        """True if this ebuild sets `CROS_WORKON_MANUAL_UPREV`."""
        return self.portage_ebuild.is_manually_uprevved

    @property
    def md5_cache_file(self) -> Path:
        """The path to the md5-cache file for this ebuild."""
        return self.overlay.md5_cache_dir / self.package_info.cpvr

    @functools.cached_property
    def md5_cache(self) -> portage_md5_cache.Md5Cache:
        """The raw variables from the md5-cache file."""
        return portage_md5_cache.Md5Cache(path=self.md5_cache_file)

    @property
    def eapi(self) -> int:
        """The EAPI for the package."""
        return self.md5_cache.eapi

    @property
    def iuse(self) -> Set[str]:
        """A set of the flags in IUSE."""
        return self.md5_cache.iuse

    @property
    def iuse_default(self) -> Set[str]:
        """A set of the flags enabled by default in IUSE."""
        return self.md5_cache.iuse_default

    @property
    def eclasses(self) -> List[str]:
        """A list of the eclasses inherited by this package and its eclasses."""
        return [x.name for x in self.md5_cache.eclasses]

    @property
    def keywords(self) -> List[str]:
        """The KEYWORDS of this package."""
        return self.md5_cache.keywords

    def get_stability(self, arch: str) -> Stability:
        """Get the stability of this package on a given architecture.

        Args:
            arch: The architecture to consider for stability.

        Returns:
            The stability on this architecture.
        """
        stability = Stability.UNSPECIFIED
        for keyword in self.keywords:
            stability = {
                arch: Stability.STABLE,
                "*": Stability.STABLE,
                f"~{arch}": Stability.UNSTABLE,
                "~*": Stability.UNSTABLE,
                f"-{arch}": Stability.BAD,
                "-*": Stability.BAD,
            }.get(keyword, stability)
        return stability

    def __repr__(self) -> str:
        return f"{self.package_info.cpvr}::{self.overlay.name}"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Ebuild):
            return False
        return self.ebuild_file == other.ebuild_file


@dataclasses.dataclass(frozen=True)
class Board(QueryTarget):
    """A board, as in what would be passed to setup_board."""

    name: str
    private_overlay: Optional[Overlay] = None
    public_overlay: Optional[Overlay] = None
    profile: str = "base"

    @classmethod
    def find_all(
        cls,
        board: Optional[str] = None,
        overlays: str = constants.BOTH_OVERLAYS,
    ) -> Iterator[Board]:
        boards = {}

        for overlay in Overlay.find_all(board=board, overlays=overlays):
            board_name = overlay.board_name
            if not board_name:
                continue
            if board_name not in boards:
                boards[board_name] = Board(board_name)
            if overlay.is_private:
                boards[board_name] = dataclasses.replace(
                    boards[board_name], private_overlay=overlay
                )
            else:
                boards[board_name] = dataclasses.replace(
                    boards[board_name], public_overlay=overlay
                )

        yield from boards.values()

    @classmethod
    def get(cls, name: str, profile: str = "base") -> Board:
        """Convenience function to get a board by name.

        Args:
            name: The board name.
            profile: The profile for the board.

        Returns:
            The corresponding Board object.

        Raises:
            ValueError: when the board does not exist.
        """
        boards = [x for x in cls.find_all(board=name) if x.name == name]
        if not boards:
            raise ValueError(f"No such board: {name}")
        assert len(boards) == 1
        return dataclasses.replace(boards[0], profile=profile)

    @property
    def top_level_overlay(self) -> Optional[Overlay]:
        """The top-level overlay for this board."""
        return self.private_overlay or self.public_overlay

    @property
    def overlays(self) -> Iterator[Overlay]:
        """All overlays accessible to this board."""
        all_overlays = _get_all_overlays_by_name()

        for overlay_path in portage_util.FindOverlays(
            constants.BOTH_OVERLAYS, board=self.name
        ):
            yield all_overlays[portage_util.GetOverlayName(overlay_path)]

    @property
    def top_level_profile(self) -> Optional[Profile]:
        """The top-level profile for this board."""
        for overlay in (self.private_overlay, self.public_overlay):
            if not overlay:
                continue
            profile = overlay.get_profile(self.profile)
            if profile:
                return profile
        return None

    def tree(self) -> Iterator[Profile]:
        if self.top_level_profile:
            yield self.top_level_profile

    @property
    def use_flags(self) -> Set[str]:
        """The fully-evaluated USE flags for this board."""
        result = {f"board_use_{self.name}"}
        if self.top_level_profile:
            result.update(self.top_level_profile.use_flags)
        return result

    @property
    def arch(self) -> Optional[str]:
        """The machine architecture of this board."""
        if self.top_level_profile:
            return self.top_level_profile.arch
        return None

    @property
    def is_variant(self) -> bool:
        """True if this board has another board's top level overlay in its
        overlays parents.
        """
        if self.top_level_overlay:
            for overlay in self.top_level_overlay.parents:
                if overlay.board_name and overlay.board_name != self.name:
                    return True
        return False

    def __repr__(self) -> str:
        result = self.name
        if self.profile != "base":
            result += f":{self.profile}"
        return result


class Query:
    """The Python-level interface for cros query.

    For example:

        board = Query(Board).filter(lambda board: board.name == "volteer").one()
    """

    _filters: List[Callable[[QueryTarget], bool]]

    def __init__(
        self,
        target: Type[QueryTarget],
        board: Optional[str] = None,
        overlays: str = constants.BOTH_OVERLAYS,
    ) -> None:
        self._filters = []
        self._iter = target.find_all(board=board, overlays=overlays)
        self._consumed = False

    def filter(self, func: Callable[[QueryTarget], bool]) -> Query:
        """Add a filter to the results."""
        if self._consumed:
            raise RuntimeError("Filters cannot be added after consumption.")
        self._filters.append(func)
        return self

    def __iter__(self) -> Iterator[QueryTarget]:
        """Iterate through all results."""
        if self._consumed:
            raise RuntimeError("Query iterator has already been consumed.")
        self._consumed = True
        for result in self._iter:
            if all(x(result) for x in self._filters):
                yield result

    def one(self) -> QueryTarget:
        """Assert there is exactly one result and return it."""
        iterator = iter(self)
        result = next(iterator)
        try:
            next(iterator)
        except StopIteration:
            return result
        raise ValueError("Query returned multiple results.")

    def one_or_none(self) -> Optional[QueryTarget]:
        """Return the result if there's exactly one, or None if zero."""
        try:
            return self.one()
        except StopIteration:
            return None

    def all(self) -> List[QueryTarget]:
        """Return all results in a list."""
        return list(self)
