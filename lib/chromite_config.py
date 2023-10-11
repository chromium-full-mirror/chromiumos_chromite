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
    except os_util.UnknownNonRootUserError:
        logging.warning(
            "Unable to identify non-root user, falling back to root's configs."
        )


DIR = XDG_CONFIG_HOME / "chromite"

# List of configs that we might use.  Normally this would be declared in the
# respective modules that actually use the config file, but having the list be
# here helps act as a clearing house and get a sense of project-wide naming
# conventions, and to try and prevent conflicts.

CHROME_SDK_BASHRC = DIR / "chrome_sdk.bashrc"

GERRIT_CONFIG = DIR / "gerrit.cfg"

AUTO_SET_GOV_CONFIG = DIR / "autosetgov"

AUTO_COP_CONFIG_OFF = DIR / "autocop-off"

TELEMETRY_CONFIG = DIR / "telemetry.cfg"


def initialize():
    """Initialize the config dir for use.

    Code does not need to invoke this all the time, but can be helpful when
    creating new config files with default content.
    """
    osutils.SafeMakedirsNonRoot(DIR)
