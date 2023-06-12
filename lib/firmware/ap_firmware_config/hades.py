# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Draco configs."""

from chromite.lib.firmware import servo_lib


def get_config(servo: servo_lib.Servo) -> servo_lib.ServoConfig:
    """Get DUT controls and programmer argument to flash Draco.

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

    # Common flashing sequence for C2D2 and CCD
    # Shutdown AP so that it enters G3 state.
    dut_control_on.append(["ec_uart_cmd:apshutdown"])
    # Sleep to ensure the SoC rails get chance to discharge enough.
    dut_control_on.append(["sleep:5"])
    # Block power sequence (PG_PP3300_S5_OD) in order to
    dut_control_on.append(["ec_uart_cmd:gpioset PG_PP3300_S5_OD 0"])
    # Turning on AP but it'll stay in S5 because PG_PP3300_S5 is blocked.
    # This allows AP to set BIOS SPI pins to high-z, preventing leakage.
    dut_control_on.append(["ec_uart_cmd:gpioset EN_S5_RAILS 1"])
    # Undo the changes on exit.
    dut_control_off.append(["ec_uart_cmd:gpioset EN_S5_RAILS 0"])
    dut_control_off.append(["ec_uart_cmd:gpioset PG_PP3300_S5_OD 1"])

    if servo.is_micro:
        # Supply power to PP3300_BIOS (via PP3300_SERVO_PCH_SPI).
        dut_control_on.append(["spi2_vref:pp3300"])
        dut_control_off.append(["spi2_vref:off"])
        programmer = "raiden_debug_spi:serial=%s" % servo.serial
    elif servo.is_ccd:
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
