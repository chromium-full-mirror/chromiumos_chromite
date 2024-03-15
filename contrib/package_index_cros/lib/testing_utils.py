# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Structures and functions to help with package_index_cros unit tests."""

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import uuid

from chromite.contrib.package_index_cros.lib import package
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


class TestCase(cros_test_lib.MockTempDirTestCase):
    """Abstract parent class for tests that require mock packages."""

    @property
    def path_handler(self) -> path_handler.PathHandler:
        """Return a PathHandler we can use for testing."""
        return path_handler.PathHandler(self.setup)

    def touch(self, path: str) -> None:
        """Make a file and its parents."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()

    def setUp(self) -> None:
        # This script should generally run outside the chroot.
        # This matters for path manipulation.
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

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

        self.src_dir = self.source_root / "src"
        self.overlay_dir = self.src_dir / "third_party" / "chromiumos-overlay"
        self.setup = setup.Setup(
            "amd64-generic",
            chroot_dir=str(self.tempdir / "chroot"),
            chroot_out_dir=str(self.tempdir / "out"),
        )
        os.makedirs(self.setup.board_dir)

        # self._mock_paths_to_checkouts will hold return values for
        # Manifest.FindCheckoutFromPath(). We'll populate it as we create
        # ebuilds.
        self._mock_paths_to_checkouts: Dict[str, git.ProjectCheckout] = {
            str(self.overlay_dir): {
                "name": "chromiumos/overlays/chromiumos-overlay",
                "local_path": "src/third_party/chromiumos-overlay",
            },
        }

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

        Returns:
            The newly created Ebuild file.

        Raises:
            FileExistsError: If the mock ebuild has already been created.
        """
        ebuild_contents = f"""# Copyright 2024 The ChromiumOS Authors
# Distributed under the terms of the GNU General Public License v2
# Note: this is a fake ebuild made for testing.

EAPI=7

CROS_WORKON_LOCALNAME={_to_ebuild_array(cros_workon_localnames)}
CROS_WORKON_PROJECT={_to_ebuild_array(cros_workon_projects)}
CROS_WORKON_COMMIT={_to_ebuild_array(cros_workon_commits)}
CROS_WORKON_SUBTREE={_to_ebuild_array(cros_workon_subtrees)}

{additional_ebuild_contents}"""

        ebuild_dir = self.overlay_dir / category / package_name
        ebuild_dir.mkdir(parents=True)

        stable_ebuild_name = f"{package_name}-{stable_version}.ebuild"
        ebuild_files_to_make = [stable_ebuild_name]
        if create_9999_ebuild:
            ebuild_files_to_make.append(f"{package_name}-9999.ebuild")
        for ebuild_filename in ebuild_files_to_make:
            ebuild_path = ebuild_dir / ebuild_filename
            ebuild_path.touch()
            ebuild_path.write_text(ebuild_contents)
        ebuild = portage_util.EBuild(str(ebuild_dir / stable_ebuild_name))

        for project, localname in zip(
            cros_workon_projects, cros_workon_localnames
        ):
            # Non-CrOS packages have their source in third_party/.
            if category in ("chromeos-base", "brillo-base"):
                subdir = ""
            else:
                subdir = "third_party"
            source_path = self.src_dir / subdir / localname
            source_path.mkdir(parents=True, exist_ok=True)
            self._mock_paths_to_checkouts[
                str(source_path)
            ] = git.ProjectCheckout({"name": project, "local_path": localname})
        return ebuild

    def new_package(  # pylint: disable=docstring-misnamed-args
        self,
        src_dir_matches: Optional[List[package.TempActualDichotomy]] = None,
        **create_ebuild_kwargs: Any,
    ) -> package.Package:
        """Create a Package we can use for testing."""
        ebuild = self._create_ebuild(**create_ebuild_kwargs)
        pkg = package.Package(self.setup, ebuild)

        temp_dir = os.path.join(
            self.setup.board_dir,
            "tmp/portage",
            pkg.package_info.category,
            f"{pkg.package_info.name}-{pkg.package_info.version}",
            "work",
        )
        Path(temp_dir).mkdir(parents=True)

        build_dir = os.path.join(
            self.setup.board_dir,
            "var/cache/portage",
            pkg.package_info.category,
            pkg.package_info.name,
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
            actual=str(self.source_root / (actual_path or str(uuid.uuid4()))),
        )
        if make_actual_dir:
            os.makedirs(dichotomy.actual)
        # pylint: disable-next=protected-access
        pkg._src_dir_matches.append(dichotomy)
        return dichotomy
