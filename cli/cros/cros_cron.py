# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros cron: streamlined prefetching tool.

"cros cron" improves local development experience by prefetching network
resources (e.g., git objects, sdk tarballs, etc.) in the background on an
hourly cron job.
"""

import logging
from pathlib import Path
import string
from typing import Optional

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.utils import xdg_util


# Names of config files in chromite/systemd we symlink.
SYSTEMD_CONFIGS = ("cros-cron@.timer", "cros-cron@.service")


def detect_systemd() -> bool:
    """Detect if the system has capability for systemd timers.

    Returns:
        True, if it appears the system is systemd, False otherwise.
    """
    # This path is used by systemd itself (see sd_booted()) to detect if the
    # system is running systemd.
    return Path("/run/systemd/system").is_dir()


def systemd_escape(input_str: str) -> str:
    r"""Escape a string for usage as a parameter to a systemd template.

    Systemd uses the following escaping algorithm:
    - / (slash) becomes - (hyphen)
    - - (hyphen) and other non-alphanumeric characters becomes \xHH, where HH is
      the 2-character hexadecimal representation.

    This function should mirror the functionality of the systemd-escape command.

    Args:
        input_str: The string to be escaped.

    Returns:
        An escaped string according to the algorithm described above.
    """

    def translate_char(char: str) -> str:
        if char == "/":
            return "-"
        if char in string.ascii_letters + string.digits:
            return char
        return rf"\x{ord(char):02X}"

    return "".join(translate_char(x) for x in input_str)


def get_systemd_units() -> str:
    """Get the unit names for this checkout.

    Returns:
        A two-tuple, the timer unit and the service unit.
    """
    return tuple(
        f"cros-cron@{systemd_escape(str(constants.SOURCE_ROOT))}.{x}"
        for x in ("timer", "service")
    )


def prefetch_repo(checkout: path_util.CheckoutInfo) -> None:
    """Prefetch git objects to speed up repo sync."""
    assert checkout.type == path_util.CheckoutType.REPO
    assert checkout.repo_binary
    assert checkout.root

    cros_build_lib.run(
        [checkout.repo_binary, "sync", "--optimized-fetch", "--network-only"],
        cwd=checkout.root,
    )


def prefetch_sdks(cache_dir: Path) -> None:
    """Prefetch SDK tarballs.

    Args:
        cache_dir: The cache directory to fetch into (typically
            ${CHECKOUT}/.cache).
    """
    storage_dir = cache_dir / "sdks"
    storage_dir.mkdir(exist_ok=True, parents=True)
    prefetch_versions = cros_sdk_lib.get_prefetch_sdk_versions()
    for sdk_version in sorted(prefetch_versions):
        cros_sdk_lib.fetch_remote_tarballs(
            storage_dir,
            [cros_sdk_lib.get_sdk_tarball_url(sdk_version)],
            prefetch_versions=prefetch_versions,
        )


@command.command_decorator("cron")
class CronCommand(command.CommandGroup):
    """Streamlined pre-fetching tool."""


@CronCommand.subcommand("run", caching=True)
class RunSub(command.CliCommand):
    """Run the cron job."""

    @classmethod
    def AddParser(cls, parser: commandline.ArgumentParser) -> None:
        parser.add_bool_argument(
            "--prefetch-repo",
            True,
            "Prefetch git objects",
            "Don't prefetch git objects",
        )
        parser.add_bool_argument(
            "--prefetch-sdks",
            True,
            "Prefetch SDK tarballs",
            "Don't prefetch SDK tarballs",
        )

    def Run(self) -> Optional[int]:
        cros_build_lib.AssertOutsideChroot()
        cros_build_lib.AssertNonRootUser()

        if self.options.prefetch_repo:
            checkout = path_util.DetermineCheckout(constants.SOURCE_ROOT)
            if checkout.type == path_util.CheckoutType.REPO:
                prefetch_repo(checkout)
            else:
                logging.warning(
                    "Skipping repo prefetch, source tree does not look to be "
                    "created with repo."
                )
        if self.options.prefetch_sdks:
            prefetch_sdks(Path(self.options.cache_dir))


@CronCommand.subcommand("enable")
class EnableSub(command.CliCommand):
    """Enable the cron service."""

    def Run(self) -> Optional[int]:
        cros_build_lib.AssertOutsideChroot()
        cros_build_lib.AssertNonRootUser()

        if not detect_systemd():
            cros_build_lib.Die(
                "Your system is not running systemd.  I'll presume you know "
                "how to set up a cron job on your system.  Create a job which "
                "calls this command hourly as your user account: %s cron run",
                constants.CHROMITE_BIN_DIR / "cros",
            )

        systemd_user_dir = xdg_util.CONFIG_HOME / "systemd" / "user"
        systemd_user_dir.mkdir(exist_ok=True, parents=True)

        for config_name in SYSTEMD_CONFIGS:
            osutils.SafeSymlink(
                constants.CHROMITE_DIR / "systemd" / config_name,
                systemd_user_dir / config_name,
            )

        # Enable and start the timer.
        timer_unit, service_unit = get_systemd_units()
        for action in ("enable", "start"):
            cros_build_lib.run(["systemctl", action, "--user", timer_unit])

        # Execute the service now.
        logging.notice("Executing the service now, this may take a moment...")
        cros_build_lib.run(["systemctl", "start", "--user", service_unit])

        # Enable linger for user sessions.  This allows `cros cron` to run even
        # after the user has logged out.
        cros_build_lib.run(["loginctl", "enable-linger"])

        logging.notice("cros cron has successfully been enabled.")
        logging.notice(
            "The timer configuration encodes the path to your source checkout. "
            "If you need to re-locate your tree, you should run "
            "`cros cron disable`, then move your tree, and `cros cron enable` "
            "once you're done."
        )


@CronCommand.subcommand("disable")
class DisableSub(command.CliCommand):
    """Disable the cron service."""

    def Run(self) -> Optional[int]:
        cros_build_lib.AssertOutsideChroot()
        cros_build_lib.AssertNonRootUser()

        if not detect_systemd():
            cros_build_lib.Die(
                "Your system is not running systemd.  Please manually disable "
                "the cron job you created."
            )

        # Disable and stop the timer.
        timer_unit, _ = get_systemd_units()
        for action in ("disable", "stop"):
            cros_build_lib.run(["systemctl", action, "--user", timer_unit])


@CronCommand.subcommand("status")
class StatusSub(command.CliCommand):
    """Show the status of the cron service."""

    def Run(self) -> Optional[int]:
        cros_build_lib.AssertOutsideChroot()
        cros_build_lib.AssertNonRootUser()

        if not detect_systemd():
            cros_build_lib.Die(
                "Your system is not running systemd.  Please check your "
                "distribution's documentation on how to view cron job status."
            )

        cros_build_lib.run(
            ["systemctl", "status", "--user", *get_systemd_units()],
            check=False,
        )
