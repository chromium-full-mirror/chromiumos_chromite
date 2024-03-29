# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for build_dir.py."""

from pathlib import Path
from typing import List

from chromite.contrib.package_index_cros.lib import build_dir
from chromite.contrib.package_index_cros.lib import setup


class _MockEBuild:
    """Stand-in for portage_util.EBuild for testing."""

    def __init__(self, pkgname: str) -> None:
        self.pkgname = pkgname


class _MockPackage:
    """Stand-in for package.Package for testing."""

    def __init__(self, category: str, name: str, pkg_build_dir: Path) -> None:
        """Mock out just what we need for exercising build_dir.

        Args:
            category: The package category, such as "chromeos-base".
            name: The package name, such as "libbrillo".
            pkg_build_dir: A temporary directory containing build files to copy.
        """
        self.category = category
        self.name = name
        self.full_name = f"{category}/{name}"
        self.ebuild = _MockEBuild(name)
        self.build_dir = pkg_build_dir
        self.build_dir.mkdir(parents=True, exist_ok=True)


def test_copy_packages_into_build_dir(tmp_path: Path) -> None:
    """Make sure we can set up a build_dir that merges several packages."""

    # Arrange setup.Setup
    _setup = setup.Setup("my-cool-build-target")

    # Arrange packages.
    pkg1 = _MockPackage("chromeos-base", "pkg1", tmp_path / "pkg1")
    pkg2 = _MockPackage("chromeos-base", "pkg2", tmp_path / "pkg2")
    packages: List[_MockPackage] = [pkg1, pkg2]

    # Arrange files in packages' build dirs.
    (pkg1.build_dir / "file_from_pkg1").touch()
    (pkg2.build_dir / "file_from_pkg2").touch()

    (pkg1.build_dir / "conflicting_file").touch()
    (pkg2.build_dir / "conflicting_file").touch()
    (pkg2.build_dir / "conflicting_file").write_text("I'm different!")

    (pkg1.build_dir / "dir").mkdir()
    (pkg1.build_dir / "dir" / "inner_file").touch()
    (pkg1.build_dir / "dir" / "nested_dir").mkdir()
    (pkg1.build_dir / "dir" / "nested_dir" / "nested_file").touch()

    (pkg1.build_dir / "ignore_me.gn").touch()
    (pkg1.build_dir / "ignore_me.ninja.d").touch()

    # Generate the merged build_dir.
    result_dir = tmp_path / "result_dir"
    generator = build_dir.BuildDirGenerator(_setup)
    conflicting_files = generator.generate(
        packages, result_dir  # type: ignore[arg-type]
    )

    # Assert that the output looks OK.
    for expected_file in (
        # Should contain files from each package's build_dir.
        "file_from_pkg1",
        "file_from_pkg2",
        # The conflicting_file should be present from pkg1, and renamed for pkg2
        # because pkg1 was listed first in `packages`.
        "conflicting_file",
        "pkg2_conflicting_file",
        # Files nested in dirs should be copied.
        "dir/inner_file",
        "dir/nested_dir/nested_file",
    ):
        assert (result_dir / expected_file).exists()

    for unexpected_file in (
        "ignore_me.gn",
        "ignore_me.ninja.d",
    ):
        assert not (result_dir / unexpected_file).exists()

    assert conflicting_files == {
        str(pkg2.build_dir / "conflicting_file"): str(
            result_dir / "pkg2_conflicting_file"
        )
    }
