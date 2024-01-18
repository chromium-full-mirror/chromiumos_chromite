# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module to interact with the compile commands database."""

import collections
import filecmp
import json
import logging
import os
from typing import Any, DefaultDict, Dict, List, NamedTuple, Optional, Set

from chromite.contrib.package_index_cros.lib import cros_sdk
from chromite.contrib.package_index_cros.lib import package
from chromite.contrib.package_index_cros.lib import path_handler
from chromite.contrib.package_index_cros.lib import setup


class CdbException(Exception):
    """Exception to indicate failure while fixing Cdb."""


class DirectoryFieldException(CdbException, package.PackagePathException):
    """Exception to indicate failure resolving the directory field."""


class FileFieldException(CdbException, package.PackagePathException):
    """Exception to indicate failure resolving the file field."""


class _IncludePathOrder(NamedTuple):
    """Dataclass to hold the include args sorted by interest.

    TODO: chroot paths shall be skipped in favor of include paths from
        dependencies.

    Attributes:
        local: Paths in the ChromiumOS src tree.
        generated: Paths in the build dir.
        chroot: Paths in the chroot dir, or in the chroot's out dir.
    """

    local: Set[str]
    generated: Set[str]
    chroot: Set[str]


class Cdb:
    """Responsible for fixing paths in compile commands database."""

    g_clang_additional_args = ["-stdlib=libc++"]

    def __init__(
        self,
        cdb_data: List,
        pkg: package.Package,
        setup_data: setup.Setup,
        package_to_include_args: Dict[str, _IncludePathOrder],
        *,
        result_build_dir: Optional[str] = None,
        file_conflicts: Optional[Dict[str, str]] = None,
    ):
        """Initialize a new Cdb instance.

        Args:
            cdb_data: loaded of compile_commands.json for |pkg|.
            pkg: package to work with.
            setup_data: setup data (board, dirs, etc).
            package_to_include_args: maps packages to their include dirs. Is
                used to populate |pkg| dependencies' include paths.
            result_build_dir: path to result build dir simulating single result
                package.
            file_conflicts: Map of {original_artifact_path: result_path}, where
                original_artifact_path is an original build artifact in the
                chroot dir that conflicts between packages, and result_path is
                the corresponding artifact in |result_build_dir|.
        """
        self.data = cdb_data
        self.package = pkg
        self.setup = setup_data
        self.path_handler = path_handler.PathHandler(self.setup)
        if result_build_dir:
            self.build_dir = result_build_dir
        else:
            self.build_dir = self.package.build_dir
        self.file_conflicts = file_conflicts or {}

        for dep in self.package.dependencies:
            if dep.name not in package_to_include_args:
                raise CdbException(
                    f"{self.package.full_name}:"
                    f" No include path for dependency: {dep.name}"
                )

        self.package_to_include_args = package_to_include_args
        self.package_to_include_args[
            self.package.full_name
        ] = _IncludePathOrder(set(), set(), set())

    def Fix(self) -> "Cdb":
        """Fix cdb entries.

        This will do a few things:
        *   Substitute chroot paths with corresponding paths outside of chroot.
        *   Substitute temp src paths with actual paths.
        *   TODO: substitute chroot include paths with actual paths from
            dependencies.
        *   Add several clang args.

        Returns:
            Self.
        """
        if self.package.is_highly_volatile:
            logging.debug(
                "%s: Is highly volatile package. Not all checks performed",
                self.package.full_name,
            )

        for include_path in self.package.additional_include_paths:
            logging.debug(
                "%s: Additional include path will be used: %s",
                self.package.full_name,
                include_path,
            )

        for entry in self.data:
            entry["directory"] = self._GetFixedDirectory(entry)

            entry["file"] = os.path.relpath(
                self._GetFixedFile(entry), entry["directory"]
            )

            entry["command"] = " ".join(self._GetFixedArguments(entry))
            if "arguments" in entry:
                del entry["arguments"]

            if "output" in entry:
                entry["output"] = self._GetFixOutput(entry)

        return self

    def _GetFixedDirectory(self, entry: Dict) -> str:
        if "directory" not in entry:
            raise ValueError(f"Directory field is missing from {entry}")
        directory = self.path_handler.FromChroot(entry["directory"])
        if directory != self.package.build_dir:
            raise DirectoryFieldException(
                self.package,
                "Directory field does not match build dir",
                directory,
                self.package.build_dir,
            )
        return self.build_dir

    def _GetFixedArguments(self, entry: Dict) -> List[str]:
        # Each entry has either command or arguments. If it's arguments then
        # substitute it with command.
        assert (
            "arguments" in entry or "command" in entry
        ), "Arguments and command field are missing"

        if "arguments" in entry:
            compiler, *arguments = entry["arguments"]
        else:
            compiler, *arguments = entry["command"].split(" ")

        # First argument is always a compiler.
        actual_arguments = [self._FixArgumentsCompiler(compiler)]
        actual_include_args = _IncludePathOrder(set(), set(), set())

        for arg in arguments:

            def Fixer(chroot_path: str) -> str:
                return self._FixPath(
                    chroot_path,
                    ignore_highly_volatile=True,
                    ignore_generated=True,
                    ignore_stable=True,
                    ignorable_dirs=self.setup.ignorable_dirs,
                ).actual

            (
                arg_prefix,
                actual_path,
            ) = path_handler.FixPathInArgument(arg, Fixer)
            actual_arg = arg_prefix + actual_path

            if arg_prefix == "-I":
                # Put include path into corresponding ordered location.
                if actual_path.startswith(self.build_dir):
                    # build_dir can be inside src_dir, so it comes before local.
                    actual_include_args.generated.add(actual_arg)
                elif actual_path.startswith(self.setup.src_dir):
                    actual_include_args.local.add(actual_arg)
                elif actual_path.startswith(
                    self.setup.chroot.path
                ) or actual_path.startswith(str(self.setup.chroot.out_path)):
                    actual_include_args.chroot.add(actual_arg)
                else:
                    raise NotImplementedError(
                        f"Unexpected include path: {actual_path}"
                    )
            else:
                actual_arguments.append(actual_arg)

        # Args are fixed.

        for include_path in self.package.additional_include_paths:
            actual_include_args.local.add("-I" + include_path)

        # Do not pass our dependencies up.
        self.package_to_include_args[self.package.full_name].local.update(
            actual_include_args.local
        )
        self.package_to_include_args[self.package.full_name].generated.update(
            actual_include_args.generated
        )

        for dep in self.package.dependencies:
            actual_include_args.local.update(
                self.package_to_include_args[dep.name].local
            )
            actual_include_args.generated.update(
                self.package_to_include_args[dep.name].generated
            )

        actual_arguments.extend(Cdb.g_clang_additional_args)
        actual_arguments.extend(actual_include_args.local)
        actual_arguments.extend(actual_include_args.generated)
        actual_arguments.extend(actual_include_args.chroot)

        return actual_arguments

    def _GetFixedFile(self, entry: Dict) -> str:
        assert "file" in entry, "File field is missing"

        temp_file, actual_file = self._FixPath(
            entry["file"], ignore_generated=True, ignore_highly_volatile=True
        )

        if temp_file != actual_file:
            if not os.path.isfile(temp_file) or not os.path.isfile(actual_file):
                logging.debug(
                    "%s: Cannot verify if temp and actual file are the same: "
                    "%s vs %s",
                    self.package.full_name,
                    temp_file,
                    actual_file,
                )
            elif not filecmp.cmp(temp_file, actual_file):
                if self.package.is_highly_volatile:
                    logging.debug(
                        "%s: Temp and actual files differ. Possibly patches: "
                        "%s vs %s",
                        self.package.full_name,
                        temp_file,
                        actual_file,
                    )
                else:
                    raise FileFieldException(
                        self.package,
                        "Temp and actual file differ",
                        temp_file,
                        actual_file,
                    )

        return actual_file

    def _GetFixOutput(self, entry: Dict) -> str:
        assert "output" in entry, "Output field is missing"

        actual_file = self._FixPath(
            entry["output"], ignore_generated=True, ignore_highly_volatile=True
        ).actual

        return actual_file

    def _FixPath(  # pylint: disable=docstring-misnamed-args
        self, chroot_path: str, **ignore_args: Any
    ) -> path_handler.FixedPath:
        """Wrap |FixPathWithIgnores|, and move build_dir to the result dir."""
        fixed_path = self.path_handler.FixPathWithIgnores(
            chroot_path,
            self.package,
            conflicting_paths=self.file_conflicts,
            **ignore_args,
        )

        if fixed_path.actual.startswith(self.package.build_dir):
            return path_handler.FixedPath(
                fixed_path.original,
                path_handler.MovePath(
                    fixed_path.actual, self.package.build_dir, self.build_dir
                ),
            )
        return fixed_path

    def _FixArgumentsCompiler(self, compiler: str) -> str:
        if compiler.endswith("clang++"):
            return "clang++"
        elif compiler.endswith("clang"):
            return "clang"
        else:
            raise NotImplementedError(f"Unknown compiler: '{compiler}'")


class CdbGenerator:
    """Generates, fixes and merges compile databases for given packages."""

    def __init__(
        self,
        setup_data: setup.Setup,
        *,
        result_build_dir: Optional[str] = None,
        file_conflicts: Optional[Dict[str, str]] = None,
        fail_fast: bool = False,
    ):
        """Initialize a new CdbGenerator instance.

        Args:
            setup_data: Setup data (board, dirs, etc).
            result_build_dir: Path to the result build dir, simulating a single
                resultpackage.
            file_conflicts: Map of {original_artifact_path: result_path}, where
                original_artifact_path is an original build artifact in the
                chroot dir that conflicts between packages, and result_path is
                the corresponding artifact in |result_build_dir|.
            fail_fast: If given, stop generating upon a package failure.
        """
        self.setup = setup_data
        self.result_build_dir = result_build_dir
        self.file_conflicts = file_conflicts or {}
        self.fail_fast = fail_fast
        self.package_status: DefaultDict[
            str, List[str]
        ] = collections.defaultdict(list)

    def _GenerateCdbForPackage(
        self, pkg: package.Package, packages_to_include_args: Dict
    ) -> Cdb:
        cdb_str = cros_sdk.CrosSdk(self.setup).GenerateCompileCommands(
            path_handler.PathHandler(self.setup).ToChroot(pkg.build_dir)
        )
        logging.debug("%s: Generated compile commands", pkg.full_name)

        cdb_data = json.loads(cdb_str)
        if not cdb_data:
            logging.error("%s: Compile commands are empty", pkg.full_name)

        assert isinstance(cdb_data, List)

        return Cdb(
            cdb_data,
            pkg,
            self.setup,
            packages_to_include_args,
            result_build_dir=self.result_build_dir,
            file_conflicts=self.file_conflicts,
        )

    def _GenerateResultCdb(self, packages: List[package.Package]) -> List:
        result_cdb_data = []

        packages_to_include_args: Dict[str, _IncludePathOrder] = {}
        for pkg in packages:
            try:
                cdb_data = (
                    self._GenerateCdbForPackage(pkg, packages_to_include_args)
                    .Fix()
                    .data
                )
                result_cdb_data.extend(cdb_data)
            except (CdbException, package.PackagePathException) as e:
                self.package_status["failed_exception"].append(pkg.full_name)
                logging.warning(
                    "%s: Failed to fix compile commands: %s",
                    pkg.full_name,
                    e,
                )
                if self.fail_fast:
                    raise e
            else:
                self.package_status["success"].append(pkg.full_name)

        return result_cdb_data

    def Generate(
        self, packages: List[package.Package], result_cdb_file: str
    ) -> None:
        """Generate, fix, and merge compile databases for the given packages.

        Raises:
            CdbException or field specific exception: Failed to fix cdb entry.
        """
        assert result_cdb_file

        result_cdb = self._GenerateResultCdb(packages)

        logging.info(
            "Package CDB Statuses:\n%s",
            json.dumps(self.package_status, indent=2),
        )

        with open(result_cdb_file, "w", encoding="utf-8") as output:
            json.dump(result_cdb, output, indent=2)
