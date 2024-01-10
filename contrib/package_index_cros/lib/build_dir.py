# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for working with build dirs."""

import filecmp
import logging
import os
import shutil
from typing import Dict, List

from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import setup


class _BuildDirMerger:
    """Merge build directories of given packages."""

    g_ignore_extensions = [
        ".gn",
        ".ninja",
        ".ninja.d",
        ".ninja_deps",
        ".ninja_log",
    ]

    def __init__(self, setup_data: setup.Setup, result_build_dir):
        self.setup = setup_data
        self.result_build_dir = result_build_dir

        assert os.path.isdir(
            self.result_build_dir
        ), "Result build dir does not exist"

    def Append(self, new_package: package.Package) -> Dict[str, str]:
        """Add |new_package|'s build dir to result one.

        Returns:
            A dictionary of conflicting files (same result name, different
            content), mapping file's original name to a result name. The result
            name is composed like {dest_dir}/{package_name}_{filename}.
        """
        source_dest_conflicts = {}

        def CopyFile(source: str, dest: str) -> None:
            assert os.path.isfile(source), "Copying directory instead of file"

            if any(
                source.endswith(ext)
                for ext in _BuildDirMerger.g_ignore_extensions
            ):
                logging.debug(
                    "%s: ignore file: %s", new_package.full_name, source
                )
                return

            if os.path.exists(dest) and not filecmp.cmp(source, dest):
                dest = os.path.join(
                    os.path.dirname(dest),
                    f"{new_package.package_info.name}_{os.path.basename(dest)}",
                )
                logging.debug(
                    "%s: Copying conflicting file with package prefix: "
                    "%s to %s",
                    new_package.full_name,
                    source,
                    dest,
                )
                source_dest_conflicts[source] = dest
            shutil.copy2(source, dest)

        def CopyDir(source: str, dest: str) -> None:
            assert os.path.isdir(source), "Copying file instead of directory"

            for item in os.listdir(source):
                source_item = os.path.join(source, item)
                dest_item = os.path.join(dest, item)

                if os.path.isdir(source_item):
                    if not os.path.isdir(dest_item):
                        os.mkdir(dest_item)
                    CopyDir(source_item, dest_item)
                elif os.path.isfile(source_item):
                    CopyFile(source_item, dest_item)
                else:
                    logging.debug(
                        "%s: ignoring: %s (not valid file nor dir)",
                        new_package.full_name,
                        source_item,
                    )

        CopyDir(new_package.build_dir, self.result_build_dir)
        return source_dest_conflicts


class BuildDirGenerator:
    """Helper class that merges build directories of given packages."""

    def __init__(self, setup_data: setup.Setup):
        self.setup = setup_data

    def _PrepareDir(self, result_build_dir: str) -> None:
        """Create a new result_build_dir, clobbering any that already exist."""
        if os.path.isdir(result_build_dir):
            logging.warning("Removing existing build dir: %s", result_build_dir)
            shutil.rmtree(result_build_dir)

        os.makedirs(result_build_dir)
        logging.debug("Build dir created: %s", result_build_dir)

    def Generate(
        self, packages: List[package.Package], result_build_dir: str
    ) -> Dict[str, str]:
        """Generate a common result dir containing the packages' artifacts.

        Returns:
            A dictionary of conflicting files (same result name, different
            content) mapping file's original name to a result name. The result
            name is composed like {dest_dir}/{package_name}_{filename}.
        """
        assert result_build_dir

        self._PrepareDir(result_build_dir)

        merger = _BuildDirMerger(self.setup, result_build_dir)
        source_dest_conflicts = {}
        for pkg in packages:
            source_dest_conflicts.update(merger.Append(pkg))
            logging.debug(
                "Added %s to result build dir: %s",
                pkg.full_name,
                pkg.build_dir,
            )

        return source_dest_conflicts
