# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration options for various cbuildbot builders."""

from chromite.lib import config_lib
from chromite.lib import constants
from chromite.utils import memoize


def DefaultSettings():
    """Create the default build config values for this site.

    Returns:
        dict: of default config_lib.BuildConfig values to use for this site.
    """
    # Site specific adjustments for default BuildConfig values.
    defaults = config_lib.DefaultSettings()

    # Git repository URL for our manifests.
    #  https://chromium.googlesource.com/chromiumos/manifest
    #  https://chrome-internal.googlesource.com/chromeos/manifest-internal
    defaults["manifest_repo_url"] = constants.EXTERNAL_MANIFEST_URL

    return defaults


@memoize.Memoize
def GetConfig():
    """Create the Site configuration for all ChromeOS builds.

    Returns:
        A config_lib.SiteConfig.
    """
    defaults = DefaultSettings()

    # site_config with no templates or build configurations.
    site_config = config_lib.SiteConfig(defaults=defaults)

    return site_config
