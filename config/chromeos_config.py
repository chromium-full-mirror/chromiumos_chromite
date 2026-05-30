# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration options for various cbuildbot builders."""

import logging

from chromite.lib import config_lib
from chromite.lib import constants
from chromite.utils import memoize


def GetBoardTypeToBoardsDict(ge_build_config):
    """Get board type to board names dict.

    Args:
        ge_build_config: Dictionary containing the decoded GE configuration
            file.

    Returns:
        A dict mapping board types to board name collections.
        The dict contains board types including all_release_boards, all_boards,
        and internal_boards.
    """
    ge_arch_board_dict = config_lib.GetArchBoardDict(ge_build_config)

    boards_dict = {}

    arm_internal_release_boards = ge_arch_board_dict.get(
        config_lib.CONFIG_ARM_INTERNAL, set()
    )
    arm_external_boards = ge_arch_board_dict.get(
        config_lib.CONFIG_ARM_EXTERNAL, set()
    )

    x86_internal_release_boards = ge_arch_board_dict.get(
        config_lib.CONFIG_X86_INTERNAL, set()
    )
    x86_external_boards = ge_arch_board_dict.get(
        config_lib.CONFIG_X86_EXTERNAL, set()
    )

    arm_full_boards = arm_internal_release_boards | arm_external_boards
    x86_full_boards = x86_internal_release_boards | x86_external_boards

    arm_boards = arm_full_boards
    x86_boards = x86_full_boards

    boards_dict["all_release_boards"] = (
        arm_internal_release_boards | x86_internal_release_boards
    )
    all_boards = x86_boards | arm_boards
    boards_dict["all_boards"] = all_boards

    boards_dict["internal_boards"] = boards_dict["all_release_boards"]

    all_ge_boards = set()
    for val in ge_arch_board_dict.values():
        all_ge_boards |= val
    boards_dict["unknown_boards"] = frozenset(all_ge_boards - all_boards)

    return boards_dict


def DefaultSettings():
    """Create the default build config values for this site.

    Returns:
        dict: of default config_lib.BuildConfig values to use for this site.
    """
    # Site specific adjustments for default BuildConfig values.
    defaults = config_lib.DefaultSettings()

    # Git repository URL for our manifests.
    #  https://chromium.googlesource.com/chromiumos/manifest
    #  https://chrome-internal.googlesource.com/chromeos/manifest-internal
    defaults["manifest_repo_url"] = constants.EXTERNAL_MANIFEST_URL

    return defaults


@memoize.Memoize
def GetConfig():
    """Create the Site configuration for all ChromeOS builds.

    Returns:
        A config_lib.SiteConfig.
    """
    defaults = DefaultSettings()

    ge_build_config = config_lib.LoadGEBuildConfigFromFile()
    boards_dict = GetBoardTypeToBoardsDict(ge_build_config)

    # If there are unknown boards in the GE config, issue a warning and ignore
    # them.
    unknown = boards_dict["unknown_boards"]
    if unknown:
        logging.warning(
            "dropping unknown boards from GE config: %s",
            " ".join(x for x in unknown),
        )
        ge_build_config["boards"] = [
            x for x in ge_build_config["boards"] if x["name"] not in unknown
        ]
        boards_dict = GetBoardTypeToBoardsDict(ge_build_config)

    # site_config with no templates or build configurations.
    site_config = config_lib.SiteConfig(defaults=defaults)

    return site_config
