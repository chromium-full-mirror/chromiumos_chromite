# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility script to update the generated config files."""

import logging

from chromite.config import chromeos_config
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils


def main(argv) -> None:
    # Parse arguments to respect log levels.
    commandline.ArgumentParser().parse_args(argv)

    # Regenerate `config_dump.json`.
    logging.info("Regenerating config_dump.json")
    site_config = chromeos_config.GetConfig()
    site_config.SaveConfigToFile(constants.CHROMEOS_CONFIG_FILE)

    # Regenerate `luci-scheduler.cfg`.
    logging.info("Regenerating luci-scheduler.cfg")
    cmd = constants.CHROMITE_SCRIPTS_DIR / "gen_luci_scheduler"
    luci_result = cros_build_lib.run(
        [cmd], capture_output=True, encoding="utf-8", debug_level=logging.DEBUG
    )
    osutils.WriteFile(constants.LUCI_SCHEDULER_CONFIG_FILE, luci_result.stdout)
