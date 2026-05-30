# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Utility script to update the generated config files."""

import logging

from chromite.config import chromeos_config
from chromite.lib import commandline
from chromite.lib import constants


def main(argv) -> None:
    # Parse arguments to respect log levels.
    commandline.ArgumentParser().parse_args(argv)

    # Regenerate `config_dump.json`.
    logging.info("Regenerating config_dump.json")
    site_config = chromeos_config.GetConfig()
    site_config.SaveConfigToFile(constants.CHROMEOS_CONFIG_FILE)
