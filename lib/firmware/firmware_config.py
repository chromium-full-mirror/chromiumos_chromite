# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""AP Firmware Config related functionality.

This module holds the firmware config objects, provides functionality to read
the config from ap_firmware_config modules, and export it into JSON.
"""

import json
import logging
import os
from pathlib import Path
import sys
from typing import List, NamedTuple, Optional

from chromite.lib.firmware import ap_firmware_config
from chromite.lib.firmware import servo_lib


_CONFIG_BUILD_WORKON_PACKAGES = "BUILD_WORKON_PACKAGES"
_CONFIG_BUILD_PACKAGES = "BUILD_PACKAGES"


class Error(Exception):
    """Base error class for the module."""


class FirmwareConfig(NamedTuple):
    """Stores firmware config for a specific board and a specific servo/ssh.

    Attributes:
        dut_control_on:  2d array formatted like
            [["cmd1", "arg1", "arg2"], ["cmd2", "arg3", "arg4"]]
            with commands that need to be ran before flashing,
            where cmd1 will be run before cmd2.
        dut_control_off: 2d array formatted like
            [["cmd1", "arg1", "arg2"], ["cmd2", "arg3", "arg4"]]
            with commands that need to be ran after flashing,
            where cmd1 will be run before cmd2.
        programmer: programmer argument (-p) for flashrom and futility.
        force_flashrom: force use of flashrom instead of futility.
        flash_extra_flags_futility: extra flags to flash with futility.
        flash_extra_flags_flashrom: extra flags to flash with flashrom.
        workon_packages: packages to cros-workon before building.
        build_packages: packages to build.
    """

    dut_control_on: List[List[str]]
    dut_control_off: List[List[str]]
    programmer: str
    force_flashrom: bool
    flash_extra_flags_futility: List[str]
    flash_extra_flags_flashrom: List[str]
    workon_packages: List[str]
    build_packages: List[str]


def get_config(
    build_target_name: str, servo: Optional[servo_lib.Servo]
) -> FirmwareConfig:
    """Return config for a given build target and servo/ssh.

    Args:
        build_target_name: Name of the build target, e.g. 'dedede'.
        servo: servo: The servo connected to the target DUT. None for SSH.
    """
    module = ap_firmware_config.get(build_target_name, fallback=True)

    workon_packages = getattr(module, _CONFIG_BUILD_WORKON_PACKAGES, None)
    build_packages = getattr(
        module, _CONFIG_BUILD_PACKAGES, ["chromeos-bootimage"]
    )

    if servo:
        dut_control_on, dut_control_off, programmer = module.get_config(servo)
        force_flashrom = getattr(module, "DEPLOY_SERVO_FORCE_FLASHROM", False)
        # Some servo variables are set to a different value by other programs.
        # Reset them to the default and then append with variables from the
        # config to avoid overriding config.
        reset_dut_control_on = [["ec_uart_timeout:10"]]
        dut_control_on = reset_dut_control_on + dut_control_on
    else:
        dut_control_on = []
        dut_control_off = []
        programmer = "host"
        force_flashrom = getattr(module, "DEPLOY_SSH_FORCE_FLASHROM", False)

    flash_extra_flags_futility = []
    flash_extra_flags_flashrom = []
    if hasattr(module, "is_fast_required") and servo:
        if module.is_fast_required(True, servo):
            flash_extra_flags_futility += ["--fast"]
        if module.is_fast_required(False, servo):
            flash_extra_flags_flashrom += ["-n"]
    if hasattr(module, "deploy_extra_flags_futility"):
        flash_extra_flags_futility += module.deploy_extra_flags_futility(servo)
    if hasattr(module, "deploy_extra_flags_flashrom"):
        flash_extra_flags_flashrom += module.deploy_extra_flags_flashrom(servo)

    return FirmwareConfig(
        dut_control_on,
        dut_control_off,
        programmer,
        force_flashrom,
        flash_extra_flags_futility,
        flash_extra_flags_flashrom,
        workon_packages,
        build_packages,
    )


def export_config_as_json(
    build_targets: Optional[List[str]] = None,
    output_path: Optional[str] = None,
    serial: str = None,
):
    """Exports config for all board:servo pairs in JSON.

    Args:
        build_targets: Names of the boards, e.g. ['dedede']. None for all
            boards.
        output_path: Name of the output file. None for stdout.
        serial: Serial number of the DUT. If None, %s will be used.
    """
    if not serial:
        serial = "%s"

    boards = []
    if build_targets:
        boards = build_targets
    else:
        # Get the board list from config python modules in ap_firmware_config
        ap_firmware_config_path = (
            Path(os.path.dirname(__file__)) / "ap_firmware_config"
        )
        for p in ap_firmware_config_path.glob("*.py"):
            if not p.is_file():
                continue
            if p.name.startswith("_"):
                continue
            # Remove paths, leaving only filenames, and remove .py suffixes.
            boards.append(p.with_suffix("").name)
    boards.sort()

    if output_path:
        logging.info("Dumping AP config to %s", output_path)
        logging.info("List of boards: %s", ", ".join(boards))
        logging.info("List of servos: %s", ", ".join(servo_lib.VALID_SERVOS))

    output = {}
    failed_board_servos = {}
    for board in boards:
        output[board] = {}
        for servo_version in servo_lib.VALID_SERVOS + ("ssh",):
            servo = None
            if servo_version != "ssh":
                servo = servo_lib.Servo(servo_version, serial)
            # get_config() call is expected to fail for some board:servo pairs.
            # Disable logging to avoid inconsistent error messages from config
            # modules' get_config() calls.
            logging.disable(logging.CRITICAL)
            try:
                conf = get_config(board, servo)
            except servo_lib.UnsupportedServoVersionError:
                failed_board_servos.setdefault(board, []).append(servo_version)
                continue
            finally:
                # Reenable logging.
                logging.disable(logging.NOTSET)

            output[board][servo_version] = {
                "dut_control_on": conf.dut_control_on,
                "dut_control_off": conf.dut_control_off,
                "programmer": conf.programmer,
                "force_flashrom": conf.force_flashrom,
                "flash_extra_flags_futility": conf.flash_extra_flags_futility,
                "flash_extra_flags_flashrom": conf.flash_extra_flags_flashrom,
            }

    for board, servos in failed_board_servos.items():
        logging.info("[%s] skipping servos %s", board, ", ".join(servos))

    if not output_path:
        # Print to stdout.
        json.dump(
            output, sys.stdout, ensure_ascii=False, indent=2, sort_keys=True
        )
    else:
        # Write to a file.
        with open(output_path, "w", encoding="utf-8") as output_file:
            json.dump(
                output,
                output_file,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
