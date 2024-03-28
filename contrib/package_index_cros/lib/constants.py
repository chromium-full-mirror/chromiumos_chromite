# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Commonly-used constants for package_index_cros."""

import os


PACKAGE_ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
PACKAGE_SCRIPTS_DIR = os.path.join(PACKAGE_ROOT_DIR, "scripts")

PRINT_DEPS_SCRIPT_PATH = os.path.join(PACKAGE_SCRIPTS_DIR, "print_deps")

# Set of packages that should be fine to work with but are not handled properly
# yet.
TEMPORARY_UNSUPPORTED_PACKAGES = {
    # TODO(b/308121733): Remove once symlinks are handled correctly.
    "chromeos-base/debugd",
    # Hangs forever.
    "net-wireless/floss",
}

# Packages (defined by their atom) to hard-code as "highly volatile", in the
# context of deciding which failures to ignore.
HIGHLY_VOLATILE_PACKAGES = {
    # Libchrome has a number of patches applied on top of checkout.
    "chromeos-base/libchrome",
}
