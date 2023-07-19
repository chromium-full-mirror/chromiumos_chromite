# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Hades configs."""

from chromite.lib.firmware import servo_lib


def get_config(servo: servo_lib.Servo) -> servo_lib.ServoConfig:
    """Get DUT controls and programmer argument to flash Hades.

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
    if servo.is_micro:
        dut_control_on = [["cpu_fw_spi:on"]]
        dut_control_off = [["cpu_fw_spi:off"]]
        # Supply power to PP3300_BIOS (via PP3300_SERVO_PCH_SPI).
        dut_control_on.append(["spi2_vref:pp3300"])
        dut_control_off.append(["spi2_vref:off"])
        programmer = "raiden_debug_spi:serial=%s" % servo.serial
    elif servo.is_ccd:
        dut_control_on = [["ccd_cpu_fw_spi:on"]]
        dut_control_off = [["ccd_cpu_fw_spi:off"]]
        dut_control_off.append(["power_state:reset"])
        programmer = (
            "raiden_debug_spi:target=AP,custom_rst=True,serial=%s"
            % servo.serial
        )
    else:
        raise servo_lib.UnsupportedServoVersionError(
            "%s not supported" % servo.version
        )

    return servo_lib.ServoConfig(dut_control_on, dut_control_off, programmer)
