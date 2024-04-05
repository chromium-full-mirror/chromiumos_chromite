# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Manage various ~/.config/chromite/ configuration files."""

import logging

from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.utils import os_util
from chromite.utils import xdg_util


DIR = xdg_util.CONFIG_HOME / "chromite"

# List of configs that we might use.  Normally this would be declared in the
# respective modules that actually use the config file, but having the list be
# here helps act as a clearing house and get a sense of project-wide naming
# conventions, and to try and prevent conflicts.
# Files that cannot be created automatically on initialize need to handle the
# possibility the file is owned by root as appropriate.

CHROME_SDK_BASHRC = DIR / "chrome_sdk.bashrc"

GERRIT_CONFIG = DIR / "gerrit.cfg"

AUTO_SET_GOV_CONFIG = DIR / "autosetgov"


SDK_READONLY_STICKY_CONFIG = DIR / "sdk-readonly-sticky"

TELEMETRY_CONFIG = DIR / "telemetry.cfg"

# Mapping of names to constants to simplify unit test mocking.
ALL_CONFIGS = {
    "AUTO_SET_GOV_CONFIG": AUTO_SET_GOV_CONFIG.name,
    "CHROME_SDK_BASHRC": CHROME_SDK_BASHRC.name,
    "GERRIT_CONFIG": GERRIT_CONFIG.name,
    "SDK_READONLY_STICKY_CONFIG": SDK_READONLY_STICKY_CONFIG.name,
    "TELEMETRY_CONFIG": TELEMETRY_CONFIG.name,
}


def initialize() -> bool:
    """Initialize the config dir for use.

    Code does not need to invoke this all the time, but can be helpful when
    creating new config files with default content.

    Returns:
        False if there was an error chown-ing a file to the non-root user. True
        otherwise (i.e. on success).
    """
    osutils.SafeMakedirsNonRoot(DIR)

    # Files that can safely be created as empty files. They will be owned by the
    # non-root user if possible, and otherwise chowned to the non-root user at
    # first opportunity.
    chown_error = False
    for current in (GERRIT_CONFIG, TELEMETRY_CONFIG):
        if not current.exists():
            current.touch()

        if current.owner() == "root":
            usr = os_util.get_non_root_user()
            if usr:
                try:
                    osutils.Chown(current, usr)
                except cros_build_lib.RunCommandError as e:
                    # e.g. b/327285178.
                    logging.warning(e)
                    chown_error = True
                    continue

    return not chown_error
