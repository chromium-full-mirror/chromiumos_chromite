# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the citc workspaces class"""

import dataclasses
import getpass
from pathlib import Path

import pytest

from chromite.lib import citc_workspaces
from chromite.lib import path_util


@pytest.fixture(name="username")
def a_username(monkeypatch):
    monkeypatch.setattr(getpass, "getuser", lambda: "testuser")
    return "testuser"


@pytest.fixture(name="home_dir")
def a_home_dir(monkeypatch, tmp_path, username):
    monkeypatch.setattr(
        Path,
        "home",
        lambda: tmp_path / "usr" / "local" / "google" / "home" / username,
    )
    return tmp_path / "usr" / "local" / "google" / "home" / username


@pytest.fixture(name="global_cog_base_dir")
def a_global_cog_base_dir(monkeypatch, home_dir):
    #  user local dir cache location
    monkeypatch.setattr(
        path_util,
        "get_global_cog_base_dir",
        lambda: home_dir / ".local" / "state" / "cros" / "cog",
    )
    return home_dir / ".local" / "state" / "cros" / "cog"


@pytest.fixture(name="cog_cloud_dir")
def a_cog_cloud_dir(monkeypatch, tmp_path):
    #  cogd named workspace location
    monkeypatch.setattr(
        citc_workspaces, "COG_CLOUD_DIR", tmp_path / "google" / "cog" / "cloud"
    )
    return tmp_path / "google" / "cog" / "cloud"


@dataclasses.dataclass
class CitcTestEnvironment:
    """Used to generate temp files and directories for citc workspaces"""

    citc_test_dir = None
    username = None
    home_dir = None
    named_workspace_parent_dir = None
    id_workspace_parent_dir = None
    reference_workspace = None
    test_workspaces = []


@pytest.fixture(name="citc_test_environment")
def init_citc_test_environment(
    tmp_path, home_dir, global_cog_base_dir, cog_cloud_dir
):
    """Initialize the test environment"""
    test_environment = CitcTestEnvironment()
    test_environment.citc_test_dir = tmp_path
    test_environment.username = getpass.getuser()
    test_environment.home_dir = home_dir
    test_environment.named_workspace_parent_dir = cog_cloud_dir
    test_environment.id_workspace_parent_dir = (
        global_cog_base_dir / "workspaces"
    )
    return test_environment


def _create_test_filesystem(tmp_citc_workspace: CitcTestEnvironment) -> None:
    """Generate the test filesystem from the passed in workspaces"""

    named_workspaces_location = (
        tmp_citc_workspace.named_workspace_parent_dir
        / tmp_citc_workspace.username
    )

    named_workspaces_location.mkdir(parents=True, exist_ok=True)

    for workspace in tmp_citc_workspace.test_workspaces:
        if workspace.name_workspace_location:
            # create workspace location
            (workspace.name_workspace_location / ".citc").mkdir(
                parents=True, exist_ok=True
            )
            (workspace.name_workspace_location / ".citc/workspace_id").touch()
            (
                workspace.name_workspace_location / ".citc/workspace_id"
            ).write_text(workspace.cache_id)
        if workspace.cache_location:
            workspace.cache_location.mkdir(parents=True, exist_ok=True)


@pytest.fixture(name="chroot_without_workspace")
def a_chroot_without_workspace(
    citc_test_environment,
) -> CitcTestEnvironment:
    """An orphaned cache, only has an existing id location"""
    id_number = "1"
    citc_id = f"{citc_test_environment.username}/{id_number}"
    cache_location = citc_test_environment.id_workspace_parent_dir / citc_id
    citc_test_environment.reference_workspace = citc_workspaces.Workspace(
        cache_id_number=id_number,
        cache_id=citc_id,
        cache_location=cache_location,
    )
    citc_test_environment.test_workspaces.append(
        citc_test_environment.reference_workspace
    )

    _create_test_filesystem(citc_test_environment)
    return citc_test_environment


def test_chroot_without_workspace_is_orphaned(chroot_without_workspace) -> None:
    workspaces = citc_workspaces.Workspaces()
    orphaned_workspaces = [
        workspace for workspace in workspaces if workspace.orphaned
    ]

    assert len(orphaned_workspaces) == 1
    assert (
        orphaned_workspaces[0].cache_id
        == chroot_without_workspace.reference_workspace.cache_id
    )
    assert (
        orphaned_workspaces[0].cache_id_number
        == chroot_without_workspace.reference_workspace.cache_id_number
    )
    assert (
        orphaned_workspaces[0].cache_location
        == chroot_without_workspace.reference_workspace.cache_location
    )


@pytest.fixture(name="workspace_with_chroot")
def a_workspace_with_chroot(
    citc_test_environment: CitcTestEnvironment,
) -> CitcTestEnvironment:
    """Named workspace with cache id location that exists"""
    id_number = "2"
    citc_id = f"{citc_test_environment.username}/{id_number}"
    cache_location = citc_test_environment.id_workspace_parent_dir / citc_id
    workspace_name = "test_citc_workspace_with_cache"
    name_workspace_location = (
        citc_test_environment.named_workspace_parent_dir
        / citc_test_environment.username
        / workspace_name
    )
    complete_workspace = citc_workspaces.Workspace(
        cache_id_number=id_number,
        cache_id=citc_id,
        cache_location=cache_location,
        name=workspace_name,
        name_workspace_location=name_workspace_location,
    )
    citc_test_environment.reference_workspace = complete_workspace
    citc_test_environment.test_workspaces.append(complete_workspace)

    _create_test_filesystem(citc_test_environment)
    return citc_test_environment


def test_workspace_with_chroot_is_not_orphaned(workspace_with_chroot) -> None:
    workspaces = citc_workspaces.Workspaces()
    orphaned_workspaces = [
        workspace for workspace in workspaces if workspace.orphaned
    ]
    assert len(orphaned_workspaces) == 0
    assert len(workspaces.workspaces) == 1
    assert (
        workspaces.workspaces[0].name
        == workspace_with_chroot.reference_workspace.name
    )
    assert (
        workspaces.workspaces[0].cache_id
        == workspace_with_chroot.reference_workspace.cache_id
    )
    assert (
        workspaces.workspaces[0].cache_id_number
        == workspace_with_chroot.reference_workspace.cache_id_number
    )
    assert (
        workspaces.workspaces[0].cache_location
        == workspace_with_chroot.reference_workspace.cache_location
    )
    assert (
        workspaces.workspaces[0].name_workspace_location
        == workspace_with_chroot.reference_workspace.name_workspace_location
    )


@pytest.fixture(name="workspace_without_chroot")
def a_workspace_without_chroot(
    citc_test_environment: CitcTestEnvironment,
) -> CitcTestEnvironment:
    """Named workspace, id location does not exist."""
    id_number = "3"
    citc_id = f"{citc_test_environment.username}/{id_number}"
    workspace_name = "test_citc_workspace_no_cache"
    name_workspace_location = (
        citc_test_environment.named_workspace_parent_dir
        / citc_test_environment.username
        / workspace_name
    )
    named_workspace = citc_workspaces.Workspace(
        cache_id=citc_id,
        name=workspace_name,
        name_workspace_location=name_workspace_location,
    )
    citc_test_environment.reference_workspace = named_workspace
    citc_test_environment.test_workspaces.append(named_workspace)

    _create_test_filesystem(citc_test_environment)
    return citc_test_environment


def test_workspace_without_chroot_is_not_orphaned(
    workspace_without_chroot,
) -> None:
    workspaces = citc_workspaces.Workspaces()
    orphaned_workspaces = [
        workspace for workspace in workspaces if workspace.orphaned
    ]
    assert len(orphaned_workspaces) == 0
    assert len(workspaces.workspaces) == 1
    assert (
        workspaces.workspaces[0].name
        == workspace_without_chroot.reference_workspace.name
    )
    assert (
        workspaces.workspaces[0].cache_id
        == workspace_without_chroot.reference_workspace.cache_id
    )
    assert (
        workspaces.workspaces[0].cache_id_number
        == workspace_without_chroot.reference_workspace.cache_id_number
    )
    assert (
        workspaces.workspaces[0].name_workspace_location
        == workspace_without_chroot.reference_workspace.name_workspace_location
    )


# pylint: disable=unused-argument
def test_found_all_workspaces(
    chroot_without_workspace, workspace_without_chroot, workspace_with_chroot
):
    workspaces = citc_workspaces.Workspaces()
    assert len([workspaces.orphaned_workspaces()]) == 1
    assert len(workspaces.workspaces) == 3


def test_cog_workspaces_dont_exist(cog_cloud_dir):
    # We don't want to raise unexpected exceptions when a user hasn't created a
    # Cog workspace.
    cog_cloud_dir.mkdir(parents=True)
    workspaces = citc_workspaces.Workspaces()

    assert len(workspaces.workspaces) == 0

    orphaned_workspaces = [
        workspace for workspace in workspaces if workspace.orphaned
    ]
    assert len(orphaned_workspaces) == 0
