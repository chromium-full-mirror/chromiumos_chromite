# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Structures and functions to help with package_index_cros unit tests."""

import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
import uuid

from chromite.contrib.package_index_cros.lib import conductor
from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import package_sleuth
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import git
from chromite.lib import path_util
from chromite.lib import portage_util


MANIFEST = git.ManifestCheckout.Cached(constants.SOURCE_ROOT)


def _to_ebuild_array(iterable: Iterable[Any]) -> str:
    """Format the iterable as a Bash array that we can use in an ebuild."""
    assert not isinstance(iterable, str)
    quoted = [f'"{x}"' for x in iterable]
    joined = " ".join(quoted)
    return f"({joined})"


def _get_overlay_repo_layout_conf_contents(overlay_dir: Path) -> str:
    """Return suitable contents for an overlay repository's layout.conf.

    This is useful so that portage_util can find our overlays.
    """
    repo_name = _get_overlay_repo_name(overlay_dir)
    masters = _get_overlay_masters(overlay_dir)
    return f"repo-name = {repo_name}\nmasters = {masters}"


def _get_overlay_repo_name(overlay_dir: Path) -> str:
    """Get the "repo-name" value for an overlay repository's layout.conf."""
    dirname = overlay_dir.name
    # "overlay-amd64-generic" -> "amd64-generic"
    m = re.match(r"^overlay-([\w-]+)$", overlay_dir.name)
    if m:
        return m.group(1)
    # "chromiumos-overlay" -> "chromiumos"
    m = re.match(r"^([\w-]+)-overlay$", overlay_dir.name)
    if m:
        return m.group(1)
    raise ValueError(f"Unexpected overlay dirname: {dirname}")


def _get_overlay_masters(overlay_dir: Path) -> str:
    """Get the "masters" value for an overlay repository's layout.conf."""
    # Normally, everything would inherit from portage-stable and eclass-overlay.
    # But we're not setting those up for these tests.
    masters = []
    # chromiumos doesn't inherit chromiumos, but everything else does.
    if overlay_dir.name != "chromiumos-overlay":
        masters.append("chromiumos")
    # someboard-private inherits someboard.
    m = re.match(r"overlay-([\w-]+)-private", overlay_dir.name)
    if m:
        masters.append(m.group(1))
    return " ".join(masters)


def _get_ebuild_contents(
    cros_workon_localnames: Iterable[str],
    cros_workon_projects: Iterable[str],
    cros_workon_commits: Iterable[str],
    cros_workon_subtrees: Iterable[str],
    is_9999_ebuild: bool,
    additional_ebuild_contents: str = "",
) -> str:
    """Return file contents for a package's ebuild."""
    keywords = "~*" if is_9999_ebuild else "*"
    return f"""# Copyright 2024 The ChromiumOS Authors
# Distributed under the terms of the GNU General Public License v2
# Note: this is a fake ebuild made for testing.

EAPI=7

CROS_WORKON_LOCALNAME={_to_ebuild_array(cros_workon_localnames)}
CROS_WORKON_PROJECT={_to_ebuild_array(cros_workon_projects)}
CROS_WORKON_COMMIT={_to_ebuild_array(cros_workon_commits)}
CROS_WORKON_SUBTREE={_to_ebuild_array(cros_workon_subtrees)}

inherit cros-workon

KEYWORDS="{keywords}"

{additional_ebuild_contents}"""


class TestCase(cros_test_lib.MockTempDirTestCase):
    """Abstract parent class for tests that require mock packages."""

    @property
    def cros_sdk(self) -> cros_sdk.CrosSdk:
        """Return a cros_sdk.CrosSdk object for testing."""
        return cros_sdk.CrosSdk(self.setup)

    @property
    def path_handler(self) -> path_handler.PathHandler:
        """Return a PathHandler we can use for testing."""
        return path_handler.PathHandler(self.setup)

    @property
    def package_sleuth(self) -> package_sleuth.PackageSleuth:
        """Return a PackageSleuth object for testing."""
        return package_sleuth.PackageSleuth(self.setup)

    @property
    def conductor(self) -> conductor.Conductor:
        """Return a Conductor object for testing."""
        return conductor.Conductor(self.setup)

    def touch(self, path: str) -> None:
        """Make a file and its parents."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()

    def setUp(self) -> None:
        # This script should generally run outside the chroot.
        # This matters for path manipulation.
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.build_target = "amd64-generic"
        self.source_root = Path(self.tempdir) / "chromiumos"
        self.source_root.mkdir()
        self.PatchObject(git.ManifestCheckout, "Cached", return_value=MANIFEST)
        self.PatchObject(
            constants, "_FindSourceRoot", return_value=self.source_root
        )
        self.PatchObject(
            path_util,
            "DetermineCheckout",
            return_value=path_util.CheckoutInfo(
                type=path_util.CheckoutType.REPO,
                root=str(self.source_root),
                chrome_src_dir=None,
            ),
        )
        self.setup = setup.Setup(
            self.build_target,
            chroot_dir=str(self.tempdir / "chroot"),
            chroot_out_dir=str(self.tempdir / "out"),
        )
        os.makedirs(self.setup.board_dir)

        # self._mock_paths_to_checkouts will hold return values for
        # Manifest.FindCheckoutFromPath(). We'll populate it as we create
        # ebuilds.
        self._mock_paths_to_checkouts: Dict[str, git.ProjectCheckout] = {}
        self._setup_overlays()

        def _FindCheckoutFromPath(
            path: str, strict: bool = True
        ) -> git.ProjectCheckout:
            del strict  # Unused.
            original_path = path
            while path != "/":
                if path in self._mock_paths_to_checkouts:
                    return self._mock_paths_to_checkouts[path]
                path = os.path.dirname(path)
            raise ValueError(
                f"Path {original_path} not found in mock checkouts: "
                f"{self._mock_paths_to_checkouts}"
            )

        self.PatchObject(
            MANIFEST, "FindCheckoutFromPath", side_effect=_FindCheckoutFromPath
        )

    @property
    def chromiumos_overlay_dir(self) -> Path:
        """Return the path to the checkout's chromiumos-overlay repo."""
        return self.source_root / "src" / "third_party" / "chromiumos-overlay"

    @property
    def public_board_overlay_dir(self) -> Path:
        """Return the path to the board-specific public overlay repo."""
        return (
            self.source_root
            / "src"
            / "overlays"
            / f"overlay-{self.build_target}"
        )

    @property
    def private_board_overlay_dir(self) -> Path:
        """Return the path to the board-specific private overlay repo."""
        return (
            self.source_root
            / "src"
            / "private-overlays"
            / f"overlay-{self.build_target}-private"
        )

    @property
    def _all_overlay_dirs(self) -> Tuple[Path]:
        """Return a list of all overlay repos the checkout uses."""
        return (
            self.chromiumos_overlay_dir,
            self.private_board_overlay_dir,
            # Even if we're not using public_board_overlay_dir, it needs to
            # exist if private_board_overlay_dir exists, or else portage_util
            # will raise an error.
            self.public_board_overlay_dir,
        )

    def _setup_overlays(self) -> None:
        """Create overlay dirs and make sure we can find them."""
        for overlay_dir in self._all_overlay_dirs:
            overlay_dir.mkdir(parents=True)
            layout_conf_file = overlay_dir / "metadata" / "layout.conf"
            self.touch(layout_conf_file)
            repo_name = _get_overlay_repo_name(overlay_dir)
            layout_conf_file.write_text(
                _get_overlay_repo_layout_conf_contents(overlay_dir)
            )
            self._mock_paths_to_checkouts[str(overlay_dir)] = {
                "name": f"chromiumos/overlays/{repo_name}",
                "local_path": str(overlay_dir.relative_to(self.source_root)),
            }

    def _create_ebuild(
        self,
        package_name: str = "my-package",
        category: str = "chromeos-base",
        stable_version: str = "1.0.0-r1",
        cros_workon_localnames: Tuple[str] = ("platform2",),
        cros_workon_projects: Tuple[str] = ("chromiumos/platform2",),
        cros_workon_commits: Tuple[str] = ("deadb33f",),
        cros_workon_subtrees: Tuple[str] = ("common-mk some-source-dir .gn",),
        additional_ebuild_contents: str = "",
        create_9999_ebuild: bool = True,
        private: bool = False,
    ) -> portage_util.EBuild:
        """Create an ebuild we can use to set up a Package.

        Args:
            category: The package category, such as "chromeos-base".
            package_name: The package name, such as "my-package".
            stable_version: The ebuild's stable (i.e., not 9999) version.
            cros_workon_localnames: Mock cros_workon value for the ebuild.
            cros_workon_projects: Mock cros_workon value for the ebuild.
            cros_workon_commits: Mock cros_workon value for the ebuild.
            cros_workon_subtrees: Mock cros_workon value for the ebuild.
            additional_ebuild_contents: Any thing else to add to the ebuild.
            create_9999_ebuild: If True, also create a -9999 (unstable) ebuild.
            private: If True, create the ebuild in the private overlay dir.
                Otherwise, create it in the chromiumos-overlay dir.

        Returns:
            The EBuild for newly created stable .ebuild file.

        Raises:
            FileExistsError: If the mock ebuild has already been created.
        """
        overlay_dir = (
            self.private_board_overlay_dir
            if private
            else self.chromiumos_overlay_dir
        )
        ebuild_dir = overlay_dir / category / package_name
        ebuild_dir.mkdir(parents=True)

        for ebuild_version in [stable_version, "9999"]:
            is_9999_ebuild = ebuild_version == "9999"
            if is_9999_ebuild and not create_9999_ebuild:
                continue
            ebuild_filename = f"{package_name}-{ebuild_version}.ebuild"
            ebuild_path = ebuild_dir / ebuild_filename
            ebuild_path.touch()
            ebuild_contents = _get_ebuild_contents(
                cros_workon_localnames,
                cros_workon_projects,
                cros_workon_commits,
                cros_workon_subtrees,
                is_9999_ebuild=is_9999_ebuild,
                additional_ebuild_contents=additional_ebuild_contents,
            )
            ebuild_path.write_text(ebuild_contents)
        stable_ebuild_name = f"{package_name}-{stable_version}.ebuild"
        ebuild = portage_util.EBuild(str(ebuild_dir / stable_ebuild_name))

        for project, localname in zip(
            cros_workon_projects, cros_workon_localnames
        ):
            # Non-CrOS packages have their source in third_party/.
            if category in ("chromeos-base", "brillo-base"):
                subdir = ""
            else:
                subdir = "third_party"
            source_path = self.source_root / "src" / subdir / localname
            source_path.mkdir(parents=True, exist_ok=True)
            self._mock_paths_to_checkouts[
                str(source_path)
            ] = git.ProjectCheckout({"name": project, "local_path": localname})
        return ebuild

    def new_package(  # pylint: disable=docstring-misnamed-args
        self,
        src_dir_matches: Optional[List[package.TempActualDichotomy]] = None,
        dependencies: Optional[List[package.PackageDependency]] = None,
        **create_ebuild_kwargs: Any,
    ) -> package.Package:
        """Create a Package we can use for testing."""
        ebuild = self._create_ebuild(**create_ebuild_kwargs)
        pkg = package.Package(self.setup, ebuild, deps=dependencies)

        temp_dir = os.path.join(
            self.setup.board_dir,
            "tmp/portage",
            pkg.ebuild.category,
            f"{pkg.ebuild.pkgname}-{pkg.ebuild.version_no_rev}",
            "work",
        )
        # Since some paths might be reused by multiple packages, it's OK if they
        # already exist.
        Path(temp_dir).mkdir(parents=True, exist_ok=True)
        build_dir = os.path.join(
            self.setup.board_dir,
            "var/cache/portage",
            pkg.ebuild.category,
            pkg.ebuild.pkgname,
            "out/Default",
        )
        self.touch(os.path.join(build_dir, "args.gn"))

        with self.PatchObject(
            package.Package,
            "_get_source_dirs_to_temp_source_dirs_map",
            return_value=src_dir_matches or [],
        ):
            pkg.initialize()

        return pkg

    def add_src_dir_match(
        self,
        pkg: package.Package,
        temp_path: str,
        *,
        actual_path: Optional[str] = None,
        make_actual_dir: bool = False,
    ) -> package.TempActualDichotomy:
        """Set a src_dir_match in the given package's temp dirs.

        Args:
            pkg: The package to modify.
            temp_path: Relative path within the package's temp_dir to
                use as the src_dir_match's temp source dir.
            actual_path: Relative path within the test case's temp dir (NOTE:
                not the package's temp_dir!) to use as the src_dir_match's
                actual dir. If None, a random dirname will be used.
            make_actual_dir: If True, create the actual_path as a dir.

        Returns:
            The TempActualDichotomy that was created.
        """
        assert not os.path.isabs(temp_path)
        if actual_path:
            assert not os.path.isabs(actual_path)
        dichotomy = package.TempActualDichotomy(
            temp=os.path.join(pkg.temp_dir, temp_path),
            actual=str(self.tempdir / (actual_path or str(uuid.uuid4()))),
        )
        if make_actual_dir:
            os.makedirs(dichotomy.actual)
        # pylint: disable-next=protected-access
        pkg._src_dir_matches.append(dichotomy)
        return dichotomy
