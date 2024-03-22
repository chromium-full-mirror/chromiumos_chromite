# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros_detector unittests."""

import datetime
import os

from chromite.lib import chroot_lib
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import path_util
from chromite.lib import workon_helper
from chromite.lib.telemetry import cros_detector


class ManifestCheckoutMock:
    """Mock class for git.ManifestCheckout."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    @property
    def manifest_branch(self):
        """Test value for the manifest branch."""
        return "snapshot"


def test_sdk_state_to_capture_manifest_info(monkeypatch) -> None:
    """Test that Sdk detector captures manifest sync info."""

    manifest_mtime = datetime.datetime.now(tz=datetime.timezone.utc)
    commit = git.CommitEntry(
        sha="commitsha",
        commit_date=datetime.datetime.now(),
        change_id="change-id-1",
    )

    monkeypatch.setattr(git, "FindRepoDir", lambda _: "/source/.repo")
    monkeypatch.setattr(git, "ManifestCheckout", ManifestCheckoutMock)
    monkeypatch.setattr(git, "GetLastCommit", lambda _: commit)
    monkeypatch.setattr(
        os.path, "getmtime", lambda _: manifest_mtime.timestamp()
    )
    monkeypatch.setattr(workon_helper, "ListAllWorkedOnAtoms", lambda: {})
    monkeypatch.setattr(cros_build_lib, "IsInsideChroot", lambda: True)
    monkeypatch.setattr(
        chroot_lib.Chroot, "tarball_version", "2024.03.12.050012"
    )

    sdk_detector = cros_detector.SDKSourceDetector()
    resource = sdk_detector.detect().attributes

    assert resource["manifest_branch"] == "snapshot"
    assert resource["manifest_commit_date"] == commit.commit_date.isoformat()
    assert resource["manifest_change_id"] == commit.change_id
    assert resource["manifest_commit_sha"] == commit.sha
    assert resource["manifest_sync_date"] == manifest_mtime.isoformat()
    assert resource["inside_sdk"]
    assert resource["chroot_tarball_version"] == "2024.03.12.050012"
    assert resource["checkout_type"] == "REPO"


def test_sdk_state_to_capture_empty(monkeypatch) -> None:
    """Test that Sdk detector handles None for repo dir."""

    monkeypatch.setattr(git, "FindRepoDir", lambda _: None)
    monkeypatch.setattr(workon_helper, "ListAllWorkedOnAtoms", lambda: {})
    monkeypatch.setattr(cros_build_lib, "IsInsideChroot", lambda: False)

    sdk_detector = cros_detector.SDKSourceDetector()
    resource = sdk_detector.detect().attributes

    assert len(resource) == 2
    assert not resource["inside_sdk"]
    assert resource["checkout_type"]


def test_sdk_state_to_all_workon_atoms(monkeypatch) -> None:
    """Test that sdk state detector captures all workon packages."""

    workon_atoms = {
        "kevin": [
            "chromeos-base/dcad",
        ],
        "betty": ["chromeos-base/libbrillo", "chromeos-base/chaps"],
    }
    monkeypatch.setattr(git, "FindRepoDir", lambda _: None)
    monkeypatch.setattr(
        workon_helper, "ListAllWorkedOnAtoms", lambda: workon_atoms
    )
    monkeypatch.setattr(cros_build_lib, "IsInsideChroot", lambda: False)

    sdk_detector = cros_detector.SDKSourceDetector()
    resource = sdk_detector.detect().attributes

    # inside_sdk is always set.
    assert len(resource) == 4
    assert not resource["inside_sdk"]
    assert resource["checkout_type"]
    # Check the workon entries.
    assert list(resource["workon_kevin"]) == workon_atoms["kevin"]
    assert list(resource["workon_betty"]) == workon_atoms["betty"]


def test_sdk_state_to_capture_non_repo_checkout(monkeypatch) -> None:
    cog_checkout_info = path_util.CheckoutInfo(
        path_util.CheckoutType.CITC, None, None
    )
    monkeypatch.setattr(
        path_util, "DetermineCheckout", lambda: cog_checkout_info
    )

    sdk_detector = cros_detector.SDKSourceDetector()
    resource = sdk_detector.detect().attributes

    assert len(resource) == 3
    assert resource["inside_sdk"]
    assert resource["checkout_type"] == "CITC"
