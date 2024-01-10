# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to handle GN targets."""

import filecmp
import json
import os
from typing import Any, Callable, Dict, List, Optional

from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import logger
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import setup


class TargetPathException(package.PackagePathException):
    """Exception to indicate failure while resolving paths for target."""


class GnTargetsMergeException(Exception):
    """Exception to indicate failure while merging gn targets."""


class GnTargets:
    """Responsible for fixing targets."""

    # Extensions of files that most likely generated and not exist.
    g_ignorable_extensions = [".typemap"]

    def __init__(
        self,
        data: Dict[str, Any],
        pkg: package.Package,
        setup_data: setup.Setup,
        *,
        result_build_dir: str = None,
        file_conflicts: Optional[Dict] = None,
    ):
        """Construct a new GnTargets instance.

        Args:
            data: Loaded JSON from gn_targets.json for |pkg|.
            pkg: The package to work with.
            setup_data: Setup data (board, dirs, etc).
            result_build_dir: Path to the result build dir, simulating a single
                result package.
            file_conflicts: Map of {original_artifact_path: result_path}, where
                original_artifact_path is an original build artifact in the
                chroot dir that conflicts between packages, and result_path is
                the corresponding artifact in |result_build_dir|.
        """
        self.data = data
        self.package = pkg
        self.setup = setup_data
        self.fields_to_resolve = {
            "args": GnTargets._FixArgsField,
            "cflags": GnTargets._FixArgList,
            "cflags_c": GnTargets._FixArgList,
            "cflags_cc": GnTargets._FixArgList,
            "include_dirs": GnTargets._FixPathList,
            "inputs": GnTargets._FixInputsField,
            "ldflags": GnTargets._FixArgList,
            "lib_dirs": GnTargets._FixPathList,
            "output_patterns": GnTargets._FixOutputPatternsField,
            "outputs": GnTargets._FixOutputsField,
            "response_file_contents": GnTargets._FixPathList,
            "sources": GnTargets._FixSourcesField,
            "script": GnTargets._FixScriptField,
        }
        self.path_handler = path_handler.PathHandler(self.setup)
        if result_build_dir:
            self.build_dir = result_build_dir
        else:
            self.build_dir = self.package.build_dir

        self.file_conflicts = file_conflicts or {}

    def Fix(self) -> "GnTargets":
        """Go through targets and their fields, fix what you can."""

        for target in self.data:
            for field in self.data[target]:
                if field in self.fields_to_resolve:
                    self.data[target][field] = self.fields_to_resolve[field](
                        self, self.data[target][field]
                    )
        return self

    def _FixScriptField(self, script_file: str) -> str:
        """Fix the script filepath.

        Ensure that the script file exists and is the same as |script_file|.

        Raises:
            TargetPathException: Actual script file not found.
            TargetPathException: Temp and actual script files have different
                data.
        """
        temp_script_file, actual_script_file = self.path_handler.FixPath(
            script_file, self.package, conflicting_paths=self.file_conflicts
        )
        if temp_script_file == actual_script_file:
            return actual_script_file

        if not filecmp.cmp(temp_script_file, actual_script_file):
            if self.package.is_highly_volatile:
                logger.g_logger.debug(
                    "%s: Temp and actual scripts differ. "
                    "Possibly patches: %s vs %s",
                    self.package.full_name,
                    temp_script_file,
                    actual_script_file,
                )
            else:
                raise TargetPathException(
                    self.package,
                    "Temp and actual scripts differ",
                    temp_script_file,
                    actual_script_file,
                )

        return actual_script_file

    def _FixArgsField(self, args_list: List[str]) -> List[str]:
        return self._FixArgList(args_list)

    def _FixSourcesField(self, path_list: List[str]) -> List[str]:
        return self._FixPathList(path_list)

    def _FixInputsField(self, path_list: List[str]) -> List[str]:
        return self._FixPathList(path_list)

    def _FixOutputsField(self, path_list: List[str]) -> List[str]:
        return self._FixPathList(path_list)

    def _FixOutputPatternsField(self, pattern_list: List[str]) -> List[str]:
        # File name is not actual file, but some pattern. Let's fix its
        # directory instead.
        fixed_pattern_dirs = self._FixPathList(
            [os.path.dirname(p) for p in pattern_list]
        )
        return [
            os.path.join(dir, os.path.basename(pattern))
            for dir, pattern in zip(fixed_pattern_dirs, pattern_list)
        ]

    def _FixPathList(self, path_list: List[str]) -> List[str]:
        return [self._FixPath(path).actual for path in path_list]

    def _FixArgList(self, args_list: List[str]) -> List[str]:
        """Fix paths in arguments. Ignores all misses."""

        # Split each argument in the list by comma, then by colon, then by
        # whitespace. Fix split argument separately, then join them back to get
        # fixed actual arg.
        def FixWithSeparator(
            arg: str, separator: str, fixer: Callable[[str], str]
        ):
            fixed_split_args = [
                fixer(split_arg) for split_arg in arg.split(separator)
            ]
            return separator.join(fixed_split_args)

        def FixWhiteSpaceSeparator(arg: str) -> str:
            return FixWithSeparator(arg, " ", self._FixArg)

        def FixWithColonSeparator(arg: str) -> str:
            return FixWithSeparator(arg, ":", FixWhiteSpaceSeparator)

        def FixWithCommaSeparator(arg: str) -> str:
            return FixWithSeparator(arg, ",", FixWithColonSeparator)

        actual_arg_list = []
        for arg in args_list:
            actual_arg_list.append(FixWithCommaSeparator(arg))

        return actual_arg_list

    def _FixArg(self, arg: str) -> str:
        def Fixer(chroot_path):
            return self._FixPath(chroot_path).actual

        arg_prefix, actual_path = path_handler.PathHandler.FixPathInArgument(
            arg, Fixer
        )
        return arg_prefix + actual_path

    def _FixPath(self, chroot_path: str) -> path_handler.FixedPath:
        """Wrap |FixPathWithIgnores|, and move build_dir to the result dir."""
        fixed_path = self.path_handler.FixPathWithIgnores(
            chroot_path,
            self.package,
            conflicting_paths=self.file_conflicts,
            ignore_highly_volatile=True,
            ignore_generated=True,
            ignore_stable=True,
            ignorable_dirs=self.setup.ignorable_dirs,
            ignorable_extensions=GnTargets.g_ignorable_extensions,
        )

        if fixed_path.actual.startswith(self.package.build_dir):
            return path_handler.FixedPath(
                fixed_path.original,
                path_handler.PathHandler.MovePath(
                    fixed_path.actual, self.package.build_dir, self.build_dir
                ),
            )
        return fixed_path


class GnTargetsMerger:
    """Responsible for merging targets."""

    def __init__(self):
        self.data = {}
        self.fields_to_resolve = {
            "all_dependent_configs": GnTargetsMerger._MergeLists,
            "args": GnTargetsMerger._IgnoreNewData,
            "defines": GnTargetsMerger._MergeLists,
            "deps": GnTargetsMerger._MergeLists,
            "cflags": GnTargetsMerger._MergeLists,
            "cflags_c": GnTargetsMerger._MergeLists,
            "cflags_cc": GnTargetsMerger._MergeLists,
            "configs": GnTargetsMerger._MergeLists,
            "include_dirs": GnTargetsMerger._MergeLists,
            "inputs": GnTargetsMerger._MergeLists,
            # Metadata structure varies between targets but not much between
            # packages with the same target. It should be safe to keep the first
            # metadata and ignore the rest.
            "metadata": GnTargetsMerger._IgnoreNewData,
            "ldflags": GnTargetsMerger._MergeLists,
            "lib_dirs": GnTargetsMerger._MergeLists,
            "libs": GnTargetsMerger._MergeLists,
            "outputs": GnTargetsMerger._MergeLists,
            "sources": GnTargetsMerger._MergeLists,
            # Scripts from different packages differ only in path but use the
            # same file. It should be safe to keep the first script and ignore
            # the rest.
            "script": GnTargetsMerger._IgnoreNewData,
            # Everything else shall be either unique or equal.
        }

    @staticmethod
    def _MergeLists(existing_list: List, new_list: List) -> List:
        return existing_list + [
            element for element in new_list if element not in existing_list
        ]

    @staticmethod
    def _IgnoreNewData(existing_data: Any, new_data: Any) -> Any:
        del new_data  # Unused.
        return existing_data

    def Append(self, new_targets: GnTargets) -> None:
        """Add targets from |new_targets| to existing ones."""

        for target in new_targets.data:
            if not target in self.data:
                # Brand new target. Nothing to merge.
                self.data[target] = new_targets.data[target]
                continue

            logger.g_logger.debug(
                "%s: Merging existing target: %s",
                new_targets.package.full_name,
                target,
            )

            for field in new_targets.data[target]:
                if not field in self.data[target]:
                    # Brand new field. Nothing to merge.
                    self.data[target][field] = new_targets.data[target][field]
                    continue

                field_data = self.data[target][field]
                new_field_data = new_targets.data[target][field]

                if field_data == new_field_data:
                    # Fields equal. Nothing  to merge.
                    continue

                logger.g_logger.debug(
                    "%s: %s: Merging existing field: %s",
                    new_targets.package.full_name,
                    target,
                    field,
                )

                if not field in self.fields_to_resolve:
                    raise GnTargetsMergeException(
                        f"{new_targets.package.full_name}: "
                        f"Unknown '{field}' in '{target}'"
                    )

                self.data[target][field] = self.fields_to_resolve[field](
                    field_data, new_field_data
                )


class GnTargetsGenerator:
    """Generates and fixes output of gn desc command generating gn targets."""

    class RootDirException(package.PackagePathException):
        """Indicates troubles with root dir."""

    def __init__(
        self,
        setup_data: setup.Setup,
        *,
        result_build_dir: Optional[str] = None,
        file_conflicts: Optional[Dict[str, str]] = None,
        keep_going: bool = False,
    ):
        """Construct a new GnTargetsGenerator instance.

        Args:
            setup_data: Setup data (board, dirs, etc).
            result_build_dir: Path to the result build dir, simulating a single
                result package.
            file_conflicts: Map of {original_artifact_path: result_path}, where
                original_artifact_path is an original build artifact in the
                chroot dir that conflicts between packages, and result_path is
                the corresponding artifact in |result_build_dir|.
            keep_going: If given, don't stop generating upon a package failure.
        """
        self.setup = setup_data
        self.result_build_dir = result_build_dir
        self.file_conflicts = file_conflicts or {}
        self.keep_going = keep_going

    def _FindRootDir(self, pkg: package.Package) -> str:
        """Returns a dir from which it's possible to generate gn targets."""

        for src_match in pkg.src_dir_matches:
            if os.path.isfile(os.path.join(src_match.temp, ".gn")):
                return src_match.temp

        raise GnTargetsGenerator.RootDirException(pkg, "Cannot find root dir")

    def _GenerateTargetsForPackage(self, pkg: package.Package) -> GnTargets:
        _path_handler = path_handler.PathHandler(self.setup)
        chroot_targets_root_dir = _path_handler.ToChroot(self._FindRootDir(pkg))
        chroot_build_dir = _path_handler.ToChroot(pkg.build_dir)
        targets_str = cros_sdk.CrosSdk(self.setup).GenerateGnTargets(
            chroot_targets_root_dir, chroot_build_dir
        )
        targets_str = targets_str[
            targets_str.find("{") : targets_str.rfind("}") + 1
        ]
        logger.g_logger.debug("%s: Generated targets", pkg.full_name)

        targets_data = json.loads(targets_str)
        if not targets_data:
            logger.g_logger.error("%s: gn targets are empty", pkg)

        if not isinstance(targets_data, Dict):
            raise NotImplementedError(
                f"gn targets are not dict for package: {pkg.full_name}"
            )

        return GnTargets(
            targets_data,
            pkg,
            self.setup,
            result_build_dir=self.result_build_dir,
            file_conflicts=self.file_conflicts,
        )

    def _GenerateResultTargets(self, packages: List[package.Package]) -> List:
        """Generates, fixes and merges gn_targets for given packages."""

        result_targets = GnTargetsMerger()

        for pkg in packages:
            try:
                new_targets = self._GenerateTargetsForPackage(pkg).Fix()
                result_targets.Append(new_targets)
                logger.g_logger.debug("%s: targets merged", pkg.full_name)
            except (
                GnTargetsMergeException,
                package.PackagePathException,
            ) as e:
                if self.keep_going:
                    logger.g_logger.error(
                        "%s: Failed to fix gn targets: %s", pkg.full_name, e
                    )
                else:
                    raise e

        return result_targets.data

    def Generate(
        self, packages: List[package.Package], result_targets_file: str
    ) -> str:
        """Generate, fix, and merge gn_targets for the given packages.

        Raises:
            TargetPathException: Failed to fix a target.
        """
        assert result_targets_file

        result_targets = self._GenerateResultTargets(packages)

        with open(result_targets_file, "w", encoding="utf-8") as output:
            json.dump(result_targets, output, indent=2)
