# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Print the file paths of all chromite files critical to the build.

This script gets used by the relevancy service to determine which paths in
Chromite are considered critical to normal build targets.  It's a separate
script so we can inspect sys.modules once we import all the "roots" and see
what's imported.
"""

import importlib
from pathlib import Path
import sys
import types
from typing import List, Optional

# Any chromite modules imported at this point will become relevant to all build
# targets.  Use care.
from chromite.lib import commandline
from chromite.lib import constants


# A hardcoded set of entry points which we know are used by a typical build.
ROOTS = [
    "chromite.api.controller.artifacts",
    "chromite.api.controller.dependency",
    "chromite.api.controller.image",
    "chromite.api.controller.sdk",
    "chromite.api.controller.sysroot",
    "chromite.api.controller.test",
    "chromite.api.controller.toolchain",
    "chromite.cros.test.image_test",
    "chromite.licensing.ebuild_license_hook",
    "chromite.scripts.build_api",
    "chromite.scripts.build_dlc",
    "chromite.scripts.build_minios",
    "chromite.scripts.cros_choose_profile",
    "chromite.scripts.cros_generate_os_release",
    "chromite.scripts.cros_generate_sysroot",
    "chromite.scripts.cros_losetup",
    "chromite.scripts.cros_sdk",
    "chromite.scripts.cros_set_lsb_release",
    "chromite.scripts.disk_layout_tool",
    "chromite.scripts.gconv_strip",
    "chromite.scripts.generate_reclient_inputs",
    "chromite.scripts.gs_fetch_binpkg",
    "chromite.scripts.has_prebuilt",
    "chromite.scripts.package_has_missing_deps",
    "chromite.scripts.parallel_emerge",
    "chromite.scripts.pkg_size",
    "chromite.scripts.sync_chrome",
    "chromite.scripts.test_image",
    "chromite.third_party.lddtree",
]

# Some modules assume they're imported only in the chroot.  We fake-out these
# modules to make the imports work.
FAKE_MODULES = [
    "ahocorasick",
    "magic",
]


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    return parser


def parse_arguments(argv: Optional[List[str]]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)

    opts.Freeze()
    return opts


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    parse_arguments(argv)

    for name in FAKE_MODULES:
        sys.modules[name] = types.ModuleType(name)

    for name in ROOTS:
        importlib.import_module(name)

    relevant_files = []
    for name, module in sys.modules.items():
        if name.startswith("chromite.") and getattr(module, "__file__", None):
            # This script itself isn't actually relevant to build targets.
            if module.__file__ == __file__:
                continue
            relevant_files.append(Path(module.__file__))

            # Find launcher symlink for scripts.
            if name.startswith("chromite.scripts."):
                script_name = name.rsplit(".", 1)[1]
                for path in (
                    constants.CHROMITE_BIN_DIR / script_name,
                    constants.CHROMITE_DIR / "scripts" / script_name,
                ):
                    if path.exists():
                        relevant_files.append(path)

    for path in sorted(relevant_files):
        print(path.relative_to(constants.CHROMITE_DIR))

    return 0
