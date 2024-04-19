# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros cron: streamlined prefetching tool.

"cros cron" improves local development experience by prefetching network
resources (e.g., git objects, sdk tarballs, etc.) in the background on an
hourly cron job.
"""

from pathlib import Path
from typing import Optional

from chromite.cli import command
from chromite.lib import commandline
from chromite.lib import cros_sdk_lib


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
            "--prefetch-sdks",
            True,
            "Prefetch SDK tarballs",
            "Don't prefetch SDK tarballs",
        )

    def Run(self) -> Optional[int]:
        if self.options.prefetch_sdks:
            prefetch_sdks(Path(self.options.cache_dir))
