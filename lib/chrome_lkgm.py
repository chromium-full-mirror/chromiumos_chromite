# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Find LKGM or older latest version of ChromeOS image for a board

This module reads //chromeos/CHROMEOS_LKGM file in a chrome checkout to
determine what the current LKGM version is.
"""

import logging
import os
from typing import Optional, Tuple

from chromite.lib import chromeos_version
from chromite.lib import config_lib
from chromite.lib import constants
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import path_util


# Number of snapshots in a release version.
SNAPSHOTS_PER_VERSION = 24


class Error(Exception):
    """Base class for the errors happened upon finding ChromeOS image version"""


class NoChromiumSrcDir(Error):
    """Error thrown when no chromium src dir is found."""

    def __init__(self, path) -> None:
        super().__init__(f"No chromium src dir found in {path}")


class MissingLkgmFile(Error):
    """Error thrown when we cannot get the version from CHROMEOS_LKGM."""

    def __init__(self, path) -> None:
        super().__init__(f"Cannot parse CHROMEOS_LKGM file: {path}")


def GetChromeLkgm(
    chrome_src_dir: str = "",
) -> Tuple[str, Optional[int]]:
    """Get the CHROMEOS LKGM checked into the Chrome tree.

    Args:
        chrome_src_dir: chrome source directory.

    Returns:
        Tuple of following 2 values:
        - Platform version number in format '10171.0.0'.
        - Snapshot identifier in an integer. None if LKGM is not
          a snapshot.
    """
    if not chrome_src_dir:
        chrome_src_dir = path_util.DetermineCheckout().chrome_src_dir
    if not chrome_src_dir or not os.path.exists(chrome_src_dir):
        raise NoChromiumSrcDir(chrome_src_dir)

    lkgm_file = os.path.join(chrome_src_dir, constants.PATH_TO_CHROME_LKGM)
    try:
        version = osutils.ReadFile(lkgm_file).rstrip()
    except FileNotFoundError:
        raise MissingLkgmFile(lkgm_file)
    if version == "":
        raise RuntimeError("LKGM file is empty.")

    # TODO(fqj): migrate to chromeos_version.VersionInfo
    parts = version.split("-", 2)
    platform_version = parts[0]
    snapshot_identifier = int(parts[1]) if len(parts) == 2 else None

    logging.debug(
        "Read LKGM version from %s: %s (snapshot: %s)",
        lkgm_file,
        platform_version,
        snapshot_identifier,
    )

    return platform_version, snapshot_identifier


def GetVersionStr(platform_version: str, snapshot_identifier: Optional[int]):
    if snapshot_identifier is None:
        return platform_version
    return f"{platform_version}-{snapshot_identifier}"


def _GetGsBucket(board: str, use_external_config: bool):
    """Return a hostname of GS.

    Args:
        board: The board to manage the SDK for.
        use_external_config: Use the external artifacts.
    """
    if use_external_config or not _HasInternalConfig(board):
        gs_bucket = "chromiumos-image-archive"
    else:
        gs_bucket = "chromeos-image-archive"
    return gs_bucket


def GetGsConfigName(
    board: str,
    use_external_config: bool,
    is_snapshot: bool,
):
    """Return a config name, which is used for the directory name of GS.

    Args:
        board: The board to manage the SDK for.
        use_external_config: Use the external artifacts.
        is_snapshot: Use the snapshot artifacts.
    """

    if use_external_config or not _HasInternalConfig(board):
        if is_snapshot:
            return f"{board}-public-snapshot"
        else:
            return f"{board}-{config_lib.CONFIG_TYPE_PUBLIC}"
    else:
        if is_snapshot:
            return f"{board}-snapshot"
        else:
            return f"{board}-{config_lib.CONFIG_TYPE_RELEASE}"


def GetArtifactsGsUrl(board, use_external_config, full_version):
    """Return a base directory of artifacts.

    The returned url should be a directory that contains the CrOS artifacts.
    (eg. "gs://chromeos-image-archive/eve-release/R123-12345.0.0")

    Args:
        board: The board to manage the SDK for.
        use_external_config: use the external artifacts.
        full_version: CrOS full version of image.
    """

    is_snapshot = chromeos_version.IsFullVersionWithSnapshotSuffix(full_version)

    base_url = GetGsBaseUrlForBoard(board, use_external_config, is_snapshot)
    return f"{base_url}/{full_version}"


def GetGsBaseUrlForBoard(board, use_external_config, is_snapshot):
    """Return a base directory for the specific board.

    The returned url should be a directory that contains the directories of CrOS
    artifacts and LATEST-* files.
    (eg. "gs://chromeos-image-archive/eve-release")

    Args:
        board: The board to manage the SDK for.
        use_external_config: use the external artifacts.
        is_snapshot: use the snapshot artifacts.
    """

    config_name = GetGsConfigName(
        board, use_external_config, is_snapshot=is_snapshot
    )
    gs_bucket = _GetGsBucket(board, use_external_config)
    return f"gs://{gs_bucket}/{config_name}"


def _HasInternalConfig(board: str):
    """Determines if the SDK we need is provided by an internal builder.

    A given board can have a public and/or an internal builder that
    publishes its Simple Chrome SDK. e.g. "amd64-generic" only has a public
    builder, "scarlet" only has an internal builder, "octopus" has both. So
    if we haven't explicitly passed "--use-external-config", we need to
    figure out if we want to use a public or internal builder.

    The configs inside gs://chromeos-build-release-console are the proper
    source of truth for what boards have public or internal builders.
    However, the ACLs on that bucket make it difficult for some folk to
    inspect it. So we instead simply assume that everything but the
    "*-generic" boards have internal configs.

    TODO(b/241964080): Inspect gs://chromeos-build-release-console here
        instead if/when ACLs on that bucket are opened up.

    Args:
        board: Name of board (eg. "octopus")

    Returns:
        True if there's an internal builder available that publishes SDKs
        for the board.
    """
    return "generic" not in board


class ChromeOSVersionFinder:
    """Finds LKGM or latest version of ChromeOS image for a board"""

    def __init__(
        self,
        cache_dir,
        board,
        fallback_versions,
        chrome_src=None,
        use_external_config=None,
    ) -> None:
        """Create a new object

        Args:
            cache_dir: The toplevel cache dir to use.
            board: The board to manage the SDK for.
            fallback_versions: number of older versions to be considered
            chrome_src: The location of the chrome checkout. If unspecified, the
                cwd is presumed to be within a chrome checkout.
            use_external_config: When identifying the configuration for a board,
                force usage of the external configuration if both external and
                internal are available.
        """
        self.cache_dir = cache_dir
        self.board = board

        self.gs_base = GetGsBaseUrlForBoard(
            board,
            use_external_config,
            is_snapshot=False,
        )
        self.snapshot_gs_base = GetGsBaseUrlForBoard(
            board, use_external_config, is_snapshot=True
        )

        self.gs_ctx = gs.GSContext(cache_dir=cache_dir, init_boto=False)
        self.fallback_versions = fallback_versions
        self.chrome_src = chrome_src

    def GetLatestVersionInfo(
        self, platform_version: str, snapshot_identifier: Optional[int]
    ) -> Optional[str]:
        """Gets the full version number from LATEST files.

        If |snapshot_identifier| is given, this checks the LATEST files in
        snapshot artifacts. Otherwise, this checks in the release artifacts.

        Args:
            platform_version: Platform version in the "12345.0.0" format.
            snapshot_identifier: Snapshot identifier to check the snapshot
                artifacts.

        Returns:
            Full version number in the format 'R30-3929.0.0' or None.
        """
        snapshot_version = None
        if snapshot_identifier is not None:
            snapshot_version = self.GetFullVersionFromLatestSnapshotFile(
                snapshot_identifier
            )
            if snapshot_version:
                # Snapshot is newer than platform_version release.
                if chromeos_version.VersionInfo(
                    snapshot_version
                ) > chromeos_version.VersionInfo(platform_version):
                    return snapshot_version

                # Latest snapshot image has an older platform_version, there
                # could be a better release image newer than found snapshot
                # image.
                logging.info(
                    "Snapshot %s have older platform version, trying release",
                    snapshot_version,
                )

            # Fall back to LATEST-{version} files in the release.

        release_version = self.GetFullVersionFromLatestFile(platform_version)
        if snapshot_version is None:
            return release_version
        if release_version is None:
            return snapshot_version

        # Handle cases both snapshot and release has matching images
        # If release have larger platform version, use release, otherwise use
        # snapshot. Snapshot is always newer than release at the same platform
        # version.
        if chromeos_version.VersionInfo(
            release_version
        ) > chromeos_version.VersionInfo(snapshot_version):
            return release_version
        return snapshot_version

    def _GetFullVersionFromStorage(self, version_file):
        """Cat |version_file| in google storage.

        Args:
            version_file: google storage path of the version file.

        Returns:
            Version number in the format 'R30-3929.0.0' or None.
        """
        try:
            # If the version doesn't exist in google storage,
            # which isn't unlikely, don't waste time on retries.
            full_version = self.gs_ctx.Cat(
                version_file, retries=0, encoding="utf-8"
            )
            assert full_version == "" or full_version.startswith("R")
            return full_version
        except (gs.GSNoSuchKey, gs.GSCommandError):
            return None

    def _GetFullVersionFromRecentLatest(self, version: str):
        """Gets the full version number from a recent LATEST- file.

        If LATEST-{version} does not exist, we need to look for a recent
        LATEST- file to get a valid full version from.

        Args:
            version: The version number to look backwards from. If version is
                not a canary version (ending in .0.0), returns None.

        Returns:
            Version number in the format 'R30-3929.0.0' or None.
        """
        if version.endswith(".0.0"):
            version_num_position = 0  # Decrement tip build num on canaries.
        elif version.endswith(".0"):
            version_num_position = 1  # Decrement branch build num on branches.
        else:
            return None  # We're on a mini-branch? No fallback for that.

        version_base = int(version.split(".")[version_num_position])
        version_base_min = max(version_base - self.fallback_versions, 0)
        version_file_base = f"{self.gs_base}/LATEST-"
        version_parts = version.split(".")

        for v in range(version_base - 1, version_base_min, -1):
            version_parts[version_num_position] = v
            version_parts = [str(p) for p in version_parts]
            version_file = version_file_base + ".".join(version_parts)

            logging.info("Trying: %s", version_file)
            full_version = self._GetFullVersionFromStorage(version_file)
            if full_version is not None:
                logging.info(
                    "Using cros version from most recent LATEST file: %s -> %s",
                    version_file,
                    full_version,
                )
                return full_version
        logging.warning(
            "No recent LATEST file found from %s.0.0 to %s.0.0",
            version_base_min,
            version_base,
        )
        return None

    def GetFullVersionFromLatestFile(self, version: str):
        """Gets the full version number from the LATEST-{version} file.

        Args:
            version: The version number or branch to look at.

        Returns:
            Version number in the format 'R30-3929.0.0' or None.
        """
        version_file = f"{self.gs_base}/LATEST-{version}"
        full_version = self._GetFullVersionFromStorage(version_file)
        if full_version is None:
            logging.warning("No LATEST file matching SDK version %s", version)
            return self._GetFullVersionFromRecentLatest(version)
        return full_version

    def _GetFullVersionFromRecentLatestSnapshot(self, snapshot_identifier: int):
        """Gets the full version number from a recent LATEST-SNAPSHOT-* file.

        If LATEST-SNAPSHOT-{snapshot_id} does not exist, we need to look for a
        recent LATEST-SNAPSHOT- file to get a valid full version from.

        Args:
            snapshot_identifier: The snapshot number to look at.

        Returns:
            Version number in the format 'R30-3929.0.0-123456-88888' or None.
        """
        base = snapshot_identifier
        # Searching fallback_versions * SNAPSHOTS_PER_VERSION snapshots for
        # consistent time-period of images being searched regardless of LATEST
        # file contains snapshots or releases.
        base_min = max(base - self.fallback_versions * SNAPSHOTS_PER_VERSION, 0)
        version_file_base = f"{self.snapshot_gs_base}/LATEST-SNAPSHOT-"

        for v in range(base - 1, base_min, -1):
            version_file = version_file_base + str(v)

            logging.info("Trying: %s", version_file)
            full_version = self._GetFullVersionFromStorage(version_file)
            if full_version is not None:
                logging.info(
                    "Using cros version from most recent LATEST file: %s -> %s",
                    version_file,
                    full_version,
                )
                return full_version
        logging.warning(
            "No recent LATEST file found from %s.0.0 to %s.0.0",
            base_min,
            base,
        )
        return None

    def GetFullVersionFromLatestSnapshotFile(self, snapshot_identifier: int):
        """Gets the full version number from LATEST-SNAPSHOT-{snapshot} file.

        Args:
            snapshot_identifier: The snapshot number to look at.

        Returns:
            Version number in the format 'R30-3929.0.0-123456-88888' or None.
        """
        version_file = (
            f"{self.snapshot_gs_base}/LATEST-SNAPSHOT-{snapshot_identifier}"
        )
        full_version = self._GetFullVersionFromStorage(version_file)
        if full_version is not None:
            return full_version

        # Traverse the older snapshot when the specified snapshot is not found.
        logging.warning(
            "No LATEST file matching SDK snapshot %s", snapshot_identifier
        )
        full_version = self._GetFullVersionFromRecentLatestSnapshot(
            snapshot_identifier
        )
        if full_version is not None:
            return full_version

        # Not found.
        return None
