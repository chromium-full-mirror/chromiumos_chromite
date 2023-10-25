# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Manage various ~/.config/chromite/ configuration files."""

import getpass
import logging
import os
from pathlib import Path
import tempfile

from chromite.lib import osutils
from chromite.utils import os_util


# Most common answer, in case there isn't a better answer found below.
XDG_CONFIG_HOME = Path("~/.config").expanduser()
if "chrome-bot" in (getpass.getuser(), os.environ.get("SUDO_USER")):
    # chrome-bot gets permission denied for /home/chrome-bot/.config/chromite.
    # pylint: disable=consider-using-with
    XDG_CONFIG_HOME = Path(tempfile.gettempdir()) / ".config"
elif os_util.is_non_root_user():
    # Respect the various XDG settings if the xdg module is available.
    try:
        import xdg.BaseDirectory

        XDG_CONFIG_HOME = Path(xdg.BaseDirectory.xdg_config_home)
    except ImportError:
        pass
else:
    # Running as root, fall back to hardcoded, most common answer for the user.
    try:
        XDG_CONFIG_HOME = os_util.non_root_home() / ".config"
    except os_util.Error as e:
        logging.warning(
            "Unable to locate a non-root user home, "
            "falling back to root's configs."
        )
        logging.debug(e)


DIR = XDG_CONFIG_HOME / "chromite"

# List of configs that we might use.  Normally this would be declared in the
# respective modules that actually use the config file, but having the list be
# here helps act as a clearing house and get a sense of project-wide naming
# conventions, and to try and prevent conflicts.
# Files that cannot be created automatically on initialize need to handle the
# possibility the file is owned by root as appropriate.

CHROME_SDK_BASHRC = DIR / "chrome_sdk.bashrc"

GERRIT_CONFIG = DIR / "gerrit.cfg"

AUTO_SET_GOV_CONFIG = DIR / "autosetgov"

AUTO_COP_CONFIG_OFF = DIR / "autocop-off"

TELEMETRY_CONFIG = DIR / "telemetry.cfg"

# Mapping of names to constants to simplify unit test mocking.
ALL_CONFIGS = {
    "AUTO_COP_CONFIG_OFF": AUTO_COP_CONFIG_OFF.name,
    "AUTO_SET_GOV_CONFIG": AUTO_SET_GOV_CONFIG.name,
    "CHROME_SDK_BASHRC": CHROME_SDK_BASHRC.name,
    "GERRIT_CONFIG": GERRIT_CONFIG.name,
    "TELEMETRY_CONFIG": TELEMETRY_CONFIG.name,
}


def initialize():
    """Initialize the config dir for use.

    Code does not need to invoke this all the time, but can be helpful when
    creating new config files with default content.
    """
    osutils.SafeMakedirsNonRoot(DIR)

    # Files that can safely be created as empty files. They will be owned by the
    # non-root user if possible, and otherwise chowned to the non-root user at
    # first opportunity.
    for current in (GERRIT_CONFIG, TELEMETRY_CONFIG):
        if not current.exists():
            current.touch()
        if current.owner() == "root":
            usr = os_util.get_non_root_user()
            if usr:
                osutils.Chown(current, usr)
