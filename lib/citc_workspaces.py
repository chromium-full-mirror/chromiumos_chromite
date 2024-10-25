# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Class for determining all citc workspaces and their state"""

import dataclasses
import getpass
import logging
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from chromite.lib import path_util


class Error(Exception):
    """Base error class for citc_workspaces module."""


class UnknownWorkspaceError(Error):
    """Exception for unknown workspace"""


class FailedCitcCommandError(Error):
    """Exception for failed git citc command"""


COG_CLOUD_DIR = "/google/cog/cloud/"


@dataclasses.dataclass
class Workspace:
    """Class for a citc workspace"""

    cache_id: str = None
    cache_id_number: str = None
    cache_location: Path = None
    name: str = None
    name_workspace_location: Path = None

    @property
    def orphaned(self) -> bool:
        return self.name is None

    def __str__(self) -> str:
        return (
            f"cache_id:{str(self.cache_id)} "
            f"cache_id_number:{str(self.cache_id_number)} "
            f"name:{str(self.name)} "
            f"cache_location:{self.cache_location} "
            f"name_workspace_location:{str(self.name_workspace_location)}"
        )

    def __repr__(self) -> str:
        return self.__str__()


class Workspaces:
    """class for determining all citc workspaces and their state"""

    def __init__(self) -> None:
        """Initialize

        Args:
            named_workspace_parent_dir: parent directory for citc workspaces
        """
        self.username = getpass.getuser()
        self.cache_parent_dir = (
            path_util.get_global_cog_base_dir() / "workspaces"
        )
        self.cache_workspaces_location = self.cache_parent_dir / Path(
            self.username
        )
        self.named_workspace_parent_dir = Path(COG_CLOUD_DIR) / Path(
            self.username
        )
        self.workspaces = []
        self.workspace_cache_mapping = {}
        self.workspace_name_mapping = {}
        self._enumerate_workspaces()
        self._sort_workspaces()

    def _enumerate_workspaces(self) -> None:
        self._generate_workspaces_from_citc_names()
        self._generate_workspaces_from_id_numbers()

    def _generate_workspaces_from_citc_names(self) -> None:
        named_workspaces = self.get_citc_workspace_names()
        for workspace_name in named_workspaces:
            name_workspace_location = (
                self.named_workspace_parent_dir / workspace_name
            )
            cache_id = self.determine_named_workspace_id(
                name_workspace_location
            )
            if cache_id in self.workspace_cache_mapping:
                # get existing workspace
                workspace = self.workspace_cache_mapping[cache_id]
            else:
                # create new workspace
                workspace = Workspace()
                self.workspaces.append(workspace)
                if cache_id is not None:
                    # Add to the cache mapping
                    self.workspace_cache_mapping[cache_id] = workspace
                    workspace.cache_id = cache_id
            self.workspace_name_mapping[workspace_name] = workspace
            workspace.name = workspace_name
            workspace.name_workspace_location = name_workspace_location

    def get_citc_workspace_names(self) -> List[str]:
        """Get all named citc workspaces from directory"""
        if not self.named_workspace_parent_dir.exists():
            return []
        return [
            location.name
            for location in self.named_workspace_parent_dir.iterdir()
        ]

    @staticmethod
    def determine_named_workspace_id(
        named_workspace_location: Path,
    ) -> Optional[str]:
        """Determine workspace id from named citc workspace location"""
        workspace_id = None
        try:
            workspace_id = path_util.read_workspace_id_file(
                named_workspace_location
            )

        except FileNotFoundError as e:
            logging.debug(
                "citc workspace_id_file_location does not exist: %s",
                e.filename,
            )
        except PermissionError as e:
            logging.debug(
                "citc workspace_id_file_location is not accessible %s",
                e.filename,
            )
        return workspace_id

    def _generate_workspaces_from_id_numbers(self) -> None:
        """Generate workspaces from cache dirs"""

        # Check if the cache directory exists
        if not self.cache_workspaces_location.exists():
            return

        for cache_location in self.cache_workspaces_location.iterdir():
            cache_id_number = cache_location.name
            workspace_id = f"{self.username}/{cache_id_number}"
            if workspace_id in self.workspace_cache_mapping:
                workspace = self.workspace_cache_mapping[workspace_id]
            else:
                workspace = Workspace()
                workspace.cache_id = workspace_id
                self.workspaces.append(workspace)
                self.workspace_cache_mapping[workspace_id] = workspace
            workspace.cache_id_number = cache_id_number
            workspace.cache_location = self.cache_parent_dir / workspace_id

    def __str__(self) -> str:
        """Return a string representation of the workspaces"""
        max_workspace_name_length = max(
            len(name) for name in list(self.workspace_name_mapping.keys())
        )
        workspace_info: str = (
            "CITC Workspaces: \n"
            f'{"orphaned":10} | '
            f'{"workspace name":{max_workspace_name_length}} | '
            f'{"workspace id":20} | workspace id location\n'
        )
        for workspace in self.workspaces:
            workspace_info += (
                f"{str(not workspace.name):10} | "
                f"{str(workspace.name):{max_workspace_name_length}} | "
                f"{str(workspace.cache_id):20} | "
                f"{str(workspace.cache_location)}\n"
            )
        return workspace_info

    def __repr__(self) -> str:
        return self.__str__()

    def __iter__(self) -> Iterator[Workspace]:
        return iter(self.workspaces)

    def orphaned_workspaces(self) -> Iterable[Workspace]:
        """Get all orphaned workspaces"""
        for cache_workspace in self.workspace_cache_mapping.values():
            if cache_workspace.orphaned:
                yield cache_workspace

    def _sort_workspaces(self) -> None:
        """Sort workspaces by name then by the id location"""
        self.workspaces.sort(key=lambda x: (str(x.name), str(x.cache_location)))
