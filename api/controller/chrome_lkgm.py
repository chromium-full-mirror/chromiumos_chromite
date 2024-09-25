# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Handles ChromeOS LKGM image version detection."""

import os

from chromite.api import faux
from chromite.api import validate
from chromite.lib import chrome_lkgm
from chromite.lib import chromeos_version
from chromite.lib import path_util


def _find_lkgm_success(_request, response, _config) -> None:
    """Mock for a success case."""
    response.config_name = "boardname-release"
    response.full_version = "111.0.0.5678"
    response.chromeos_lkgm = "111.0.0.5679"


def _find_lkgm_error(_request, response, _config) -> None:
    """Mock for a failed case."""
    response.error = "something went wrong"


@faux.success(_find_lkgm_success)
@faux.error(_find_lkgm_error)
@validate.require("build_target")
@validate.require("fallback_versions")
@validate.validation_complete
def FindLkgm(request, response, _config) -> None:
    """Find LKGM or older version of image for a board."""
    checkout = path_util.DetermineCheckout(request.chrome_src or os.getcwd())

    f = chrome_lkgm.ChromeOSVersionFinder(
        request.cache_dir or None,
        request.build_target.name,
        fallback_versions=request.fallback_versions,
        chrome_src=request.chrome_src,
        use_external_config=request.use_external_config,
    )

    try:
        (platform_version, snapshot_identifier) = chrome_lkgm.GetChromeLkgm(
            request.chrome_src
        )
    except (
        RuntimeError,
        chrome_lkgm.NoChromiumSrcDir,
        chrome_lkgm.MissingLkgmFile,
    ) as e:
        response.error = str(e)
        return

    if not platform_version:
        response.error = str(
            chrome_lkgm.MissingLkgmFile(checkout.chrome_src_dir)
        )
        return

    full_version = f.GetLatestVersionInfo(platform_version, snapshot_identifier)
    if not full_version:
        response.error = "failed to get full version"
        return

    is_snapshot = chromeos_version.IsFullVersionWithSnapshotSuffix(full_version)

    config_name = chrome_lkgm.GetGsConfigName(
        request.build_target.name,
        request.use_external_config,
        is_snapshot=is_snapshot,
    )

    lkgm_version_str = chrome_lkgm.GetVersionStr(
        platform_version, snapshot_identifier
    )

    response.full_version = full_version
    response.config_name = config_name
    response.chromeos_lkgm = lkgm_version_str
