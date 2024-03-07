# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for package.py."""

import os
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import git
from chromite.lib import portage_util


MANIFEST = git.ManifestCheckout.Cached(constants.SOURCE_ROOT)


def test_package_support_enum() -> None:
    """Tests for PackageSupport.is_supported() and .is_unsupported()."""
    for package_support, expect_supported in (
        (package.PackageSupport.SUPPORTED, True),
        (package.PackageSupport.NO_LOCAL_SOURCE, False),
        (package.PackageSupport.NO_GN_BUILD, False),
        (package.PackageSupport.TEMP_NO_SUPPORT, False),
    ):
        assert package_support.is_supported() == expect_supported
        assert package_support.is_unsupported() != expect_supported


def _to_ebuild_array(iterable: Iterable[Any]) -> str:
    """Format the iterable as a Bash array that we can use in an ebuild."""
    assert not isinstance(iterable, str)
    quoted = [f'"{x}"' for x in iterable]
    joined = " ".join(quoted)
    return f"({joined})"


class _PackageTestCase(cros_test_lib.MockTempDirTestCase):
    """Abstract parent class for tests that require mock packages."""

    def setUp(self) -> None:
        self.source_root = Path(self.tempdir) / "chromiumos"
        self.PatchObject(
            constants, "_FindSourceRoot", return_value=self.source_root
        )

        self.src_dir = self.source_root / "src"
        self.overlay_dir = self.src_dir / "third_party" / "chromiumos-overlay"
        self.setup = setup.Setup("amd64-generic")
        self.setup.src_dir = self.src_dir

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
        category: str = "chromeos-base",
        package_name: str = "my-package",
        stable_version: str = "1.0.0-r1",
        cros_workon_localnames: Tuple[str] = ("platform2",),
        cros_workon_projects: Tuple[str] = ("chromiumos/platform2",),
        cros_workon_commits: Tuple[str] = ("deadb33f",),
        cros_workon_subtrees: Tuple[str] = ("common-mk some-source-dir .gn ",),
        additional_ebuild_contents: str = "",
    ) -> Path:
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
        unstable_ebuild_name = f"{package_name}-9999.ebuild"
        for ebuild_filename in (stable_ebuild_name, unstable_ebuild_name):
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


class GetPackageSupportTestCase(_PackageTestCase):
    """Tests for get_package_support()."""

    def test_supported_package(self) -> None:
        ebuild = self._create_ebuild()
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support.is_supported()
        assert package_support == package.PackageSupport.SUPPORTED

    def test_virtual_package(self) -> None:
        """Make sure virtual packages are always supported."""
        ebuild = self._create_ebuild(
            category="virtual",
            # No GN build should mean no support.
            cros_workon_subtrees=("no", "gn", "build"),
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support.is_supported()
        assert package_support == package.PackageSupport.SUPPORTED

    def test_no_gn_subtrees(self) -> None:
        """Make sure we cna't build packages where no subtrees use GN."""
        ebuild = self._create_ebuild(
            cros_workon_subtrees=("common-mk some-source-dir",),
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support == package.PackageSupport.NO_GN_BUILD
        assert package_support.is_unsupported()

    def test_some_gn_subtrees(self) -> None:
        """Make sure we can build packages where only some subtrees use GN."""
        ebuild = self._create_ebuild(
            cros_workon_localnames=("platform2", "another_project"),
            cros_workon_projects=("chromiumos/platform2", "some/other/project"),
            cros_workon_commits=("deadb33f", "f33bdaed"),
            cros_workon_subtrees=("this one uses gn .gn", "this one doesn't"),
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support.is_supported()
        assert package_support == package.PackageSupport.SUPPORTED

    def test_with_rust_subdir(self) -> None:
        """Make sure we don't support packages that use Rust."""
        ebuild = self._create_ebuild(
            additional_ebuild_contents='CROS_RUST_SUBDIR="foobar"',
        )
        package_support = package.get_package_support(ebuild, self.setup)
        assert package_support == package.PackageSupport.NO_GN_BUILD
        assert package_support.is_unsupported()
