# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for working with build dirs."""

import filecmp
import logging
from pathlib import Path
import shutil
from typing import Dict, List

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup


_IGNORE_EXTENSIONS = set(
    (
        ".gn",
        ".ninja",
        ".ninja.d",
        ".ninja_deps",
        ".ninja_log",
    )
)


def _has_ignored_extension(filepath: Path) -> bool:
    """Check whether the named file has an extension we want to ignore."""
    full_suffix = "".join(filepath.suffixes)
    return full_suffix in _IGNORE_EXTENSIONS


class BuildDirMerger:
    """Merge build directories of given packages."""

    def __init__(self, setup_data: setup.Setup, result_build_dir: Path) -> None:
        self.setup = setup_data
        self.result_build_dir = result_build_dir

        if not self.result_build_dir.is_dir():
            raise FileNotFoundError(
                f"Result build dir does not exist: {self.result_build_dir}"
            )

    def append(self, new_package: package.Package) -> Dict[str, str]:
        """Copy new_package's build dir to self.result_build_dir.

        Returns:
            A dictionary of conflicting files (same result name, different
            content), mapping file's original name to a result name. The result
            name is composed like {dest_dir}/{package_name}_{filename}.
        """
        source_dest_conflicts: Dict[str, str] = {}

        def copy_file(source: Path, dest: Path) -> None:
            """Copy a single file from source to dest.

            If the named file has an extension named in _IGNORE_EXTENSIONS,
            then it will be ignored.

            If dest already exists (and isn't identical to source), then it will
            be renamed as {package_name}_{original_name} (in the same dir), and
            the mapping will be stored in source_dest_conflicts.

            Raises:
                IsADirectoryError: Source is a directory instead of a file.
            """
            if not source.is_file():
                raise IsADirectoryError(
                    f"Copying directory instead of file: {source}"
                )

            if _has_ignored_extension(source):
                logging.debug(
                    "%s: ignore file with ignored extension: %s",
                    new_package.full_name,
                    source,
                )
                return

            if dest.exists() and not filecmp.cmp(source, dest):
                new_basename = f"{new_package.ebuild.pkgname}_{dest.name}"
                dest = dest.parent / new_basename
                logging.debug(
                    "%s: Copying conflicting file with package prefix: "
                    "%s to %s",
                    new_package.full_name,
                    source,
                    dest,
                )
                source_dest_conflicts[str(source)] = str(dest)
            shutil.copy2(source, dest)

        def copy_dir(source: Path, dest: Path) -> None:
            """Recursively copy a directory from source to dest.

            Raises:
                NotADirectoryError: Source is a file instead of a directory.
            """
            if not source.is_dir():
                raise NotADirectoryError(
                    f"Copying file instead of directory: {source}"
                )

            for source_child in source.resolve().iterdir():
                dest_child = dest / source_child.name
                if source_child.is_dir():
                    dest_child.mkdir(exist_ok=True)
                    copy_dir(source_child, dest_child)
                elif source_child.is_file():
                    copy_file(source_child, dest_child)
                else:
                    logging.debug(
                        "%s: ignoring: %s (not valid file nor dir)",
                        new_package.full_name,
                        source_child,
                    )

        copy_dir(Path(new_package.build_dir), self.result_build_dir)
        return source_dest_conflicts


class BuildDirGenerator:
    """Helper class that merges build directories of given packages."""

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data

    def _prepare_dir(self, result_build_dir: Path) -> None:
        """Create a new result_build_dir, clobbering any that already exist."""
        if result_build_dir.is_dir():
            logging.warning("Removing existing build dir: %s", result_build_dir)
            shutil.rmtree(result_build_dir)

        result_build_dir.mkdir(parents=True)
        logging.debug("Build dir created: %s", result_build_dir)

    def generate(
        self, packages: List[package.Package], result_build_dir: Path
    ) -> Dict[str, str]:
        """Generate a common result dir containing the packages' artifacts.

        Returns:
            A dictionary of conflicting files (same result name, different
            content) mapping file's original name to a result name. The result
            name is composed like {dest_dir}/{package_name}_{filename}.
        """
        if not result_build_dir:
            raise ValueError(result_build_dir)

        self._prepare_dir(result_build_dir)

        merger = BuildDirMerger(self.setup, Path(result_build_dir))
        source_dest_conflicts: Dict[str, str] = {}
        for pkg in packages:
            source_dest_conflicts.update(merger.append(pkg))
            logging.debug(
                "Added %s to result build dir: %s",
                pkg.full_name,
                pkg.build_dir,
            )

        return source_dest_conflicts
