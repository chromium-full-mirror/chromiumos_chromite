# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for working with build dirs."""

import logging
from pathlib import Path
import shutil
from typing import Dict, List

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup


_IGNORE_EXTENSIONS = [
    ".gn",
    ".ninja",
    ".ninja.d",
    ".ninja_deps",
    ".ninja_log",
]


class _BuildDirMerger:
    """Merge build directories of given packages."""

    def __init__(self, setup_data: setup.Setup, result_build_dir):
        self.setup = setup_data
        self.result_build_dir = result_build_dir

        if not self.result_build_dir.is_dir():
            raise FileNotFoundError(
                f"Result build dir does not exist: {self.result_build_dir}"
            )

    def append(self, new_package: package.Package) -> Dict[Path, Path]:
        """Add |new_package|'s build dir to result one.

        Returns:
            A dictionary of conflicting files (same result name, different
            content), mapping the original filepath to the result filepath. The
            result path is composed like:
                {dest_dir}/{package_name}_{original_name}
        """
        source_dest_conflicts: Dict[Path, Path] = {}

        def copy_file(source: Path, dest: Path) -> None:
            if not source.is_file():
                raise IsADirectoryError(
                    f"Copying directory instead of file: {source}"
                )

            if "".join(source.suffixes) in _IGNORE_EXTENSIONS:
                logging.debug(
                    "%s: ignore file: %s", new_package.full_name, source
                )
                return

            if dest.exists() and not source.samefile(dest):
                new_basename = f"{new_package.package_info.name}_{dest.name}"
                dest = dest.parent / new_basename
                logging.debug(
                    "%s: Copying conflicting file with package prefix: "
                    "%s to %s",
                    new_package.full_name,
                    source,
                    dest,
                )
                source_dest_conflicts[source] = dest
            shutil.copy2(source, dest)

        def copy_dir(source: Path, dest: Path) -> None:
            if not source.is_dir():
                raise NotADirectoryError(
                    f"Copying file instead of directory: {source}"
                )

            for source_child in source.iterdir():
                dest_child = dest / source_child.name

                if source_child.is_dir():
                    if not dest_child.is_dir():
                        dest_child.mkdir()
                    copy_dir(source_child, dest_child)
                elif source_child.is_file():
                    copy_file(source_child, dest_child)
                else:
                    logging.debug(
                        "%s: ignoring: %s (not valid file nor dir)",
                        new_package.full_name,
                        source_child,
                    )

        copy_dir(new_package.build_dir, self.result_build_dir)
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
    ) -> Dict[Path, Path]:
        """Generate a common result dir containing the packages' artifacts.

        Returns:
            A dictionary of conflicting files (same result name, different
            content), mapping the original filepath to the result filepath. The
            result path is composed like:
                {dest_dir}/{package_name}_{original_name}
        """
        if not result_build_dir:
            raise ValueError(result_build_dir)

        self._prepare_dir(result_build_dir)

        merger = _BuildDirMerger(self.setup, result_build_dir)
        source_dest_conflicts = {}
        for pkg in packages:
            source_dest_conflicts.update(merger.append(pkg))
            logging.debug(
                "Added %s to result build dir: %s",
                pkg.full_name,
                pkg.build_dir,
            )

        return source_dest_conflicts
