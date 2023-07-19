# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Keeby configs."""

from chromite.lib.firmware import servo_lib


_COMMON_PACKAGES = (
    "chromeos-ec",
    "coreboot",
    "depthcharge",
    "libpayload",
    "vboot_reference",
)

BUILD_PACKAGES = _COMMON_PACKAGES + (
    "chromeos-bootimage",
    "coreboot-private-files",
    "intel-jslfsp",
)


def get_config(servo: servo_lib.Servo) -> servo_lib.ServoConfig:
    """Get DUT controls and programmer argument to flash Keeby.

    Each board needs specific config including the voltage for Vref, to turn
    on and turn off the SPI flash. get_config() returns servo_lib.ServoConfig
    with settings to flash a servo for a particular build target.
    The voltage for this board needs to be set to 3.3 V.

    Args:
        servo: The servo connected to the target DUT.

    Returns:
        servo_lib.ServoConfig:
            dut_control_{on, off}=2d arrays formatted like
                [["cmd1", "arg1", "arg2"], ["cmd2", "arg3", "arg4"]]
                where cmd1 will be run before cmd2.
            programmer=programmer argument (-p) for flashrom and futility.
    """
    dut_control_on = []
    dut_control_off = []

    if servo.is_micro or servo.is_v2:
        dut_control_on.append(["cpu_fw_spi:on"])
        dut_control_off = [["cpu_fw_spi:off"]]
        if servo.is_v2:
            programmer = (
                "ft2232_spi:type=google-servo-v2,serial=%s" % servo.serial
            )
        else:
            # Servo micro
            programmer = "raiden_debug_spi:serial=%s" % servo.serial
    else:
        raise servo_lib.UnsupportedServoVersionError(
            "%s not supported" % servo.version
        )

    return servo_lib.ServoConfig(dut_control_on, dut_control_off, programmer)
