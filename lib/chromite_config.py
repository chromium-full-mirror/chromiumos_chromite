# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Manage various ~/.config/chromite/ configuration files."""

from pathlib import Path


# Respect the various XDG settings if the xdg module is available.  Otherwise
# be lazy and hardcode the most common answer.
try:
    import xdg.BaseDirectory

    XDG_CONFIG_HOME = Path(xdg.BaseDirectory.xdg_config_home)
except ImportError:
    XDG_CONFIG_HOME = Path("~/.config").expanduser()


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
    DIR.mkdir(mode=0o755, parents=True, exist_ok=True)
