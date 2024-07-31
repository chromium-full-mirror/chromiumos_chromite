# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite/CrOS specific detectors."""

import datetime
import os
from pathlib import Path

from chromite.third_party.opentelemetry.sdk import resources

from chromite.lib import chroot_lib
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import path_util
from chromite.lib import workon_helper


class SDKSourceDetector(resources.ResourceDetector):
    """Capture SDK source state."""

    def detect(self) -> resources.Resource:
        resource = {}

        checkout_info = path_util.DetermineCheckout()
        resource["checkout_type"] = checkout_info.type.name

        if (
            checkout_info.type == path_util.CheckoutType.REPO
            and checkout_info.root
        ):
            repo = git.FindRepoDir(checkout_info.root)
            manifest_repo = Path(repo) / "manifests" if repo else None

            if manifest_repo and (manifest_repo / ".git").is_dir():
                manifest_checkout = git.ManifestCheckout.Cached(
                    checkout_info.root
                )
                branch = manifest_checkout.manifest_branch or ""
                commit = git.GetLastCommit(manifest_repo)
                resource["manifest_branch"] = branch
                resource[
                    "manifest_commit_date"
                ] = commit.commit_date.isoformat()
                resource["manifest_change_id"] = commit.change_id or ""
                resource["manifest_commit_sha"] = commit.sha
                resource[
                    "manifest_sync_date"
                ] = datetime.datetime.fromtimestamp(
                    os.path.getmtime(manifest_repo), tz=datetime.timezone.utc
                ).isoformat()

        workon_atoms = workon_helper.ListAllWorkedOnAtoms()
        if workon_atoms:
            for board, atoms in workon_atoms.items():
                resource[f"workon_{board}"] = atoms

        resource["inside_sdk"] = cros_build_lib.IsInsideChroot()
        if cros_build_lib.IsInsideChroot():
            # Only fetch when inside the SDK since we don't know whether the
            # chroot in the default location, or even initialized.
            chroot = chroot_lib.Chroot()
            resource["chroot_tarball_version"] = chroot.tarball_version

        return resources.Resource(resource)


class DevelopmentDetector(resources.ResourceDetector):
    """Capture development related info."""

    def __init__(
        self,
        *args,
        force_dev: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.force_dev = force_dev

    def detect(self) -> resources.Resource:
        resource = {
            "development.ignore_span": (
                self.force_dev
                or os.environ.get("CHROMITE_TELEMETRY_IGNORE") == "1"
            ),
            "development.tag": os.environ.get("CHROMITE_TELEMETRY_TAG", ""),
        }

        return resources.Resource(resource)


class UserDetector(resources.ResourceDetector):
    """Capture user information."""

    def __init__(self, user_uuid: str = "") -> None:
        super().__init__()
        self.user_uuid = user_uuid

    def detect(self) -> resources.Resource:
        return resources.Resource({"user.uuid": self.user_uuid})
