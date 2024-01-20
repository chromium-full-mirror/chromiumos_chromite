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
    # Reason: build dir does not contain out/Debug
    # Is built with Makefile but lists .gn in CROS_WORKON_SUBTREE.
    "chromeos-base/avtest_label_detect",
    # Reason: Fails build because it cannot find src/aosp/external/perfetto.
    # It's a go package that pretends to be an actual package. Should be
    # properly ignored.
    "dev-go/perfetto-protos",
    # TODO(b/308121733): Remove once symlinks are handled correctly.
    "chromeos-base/debugd",
    # Appears to want both llvm-12 and llvm-15 at the same time when printing
    # deps. crbug.com/1501725
    "sys-devel/llvm",
    "sys-libs/llvm-libunwind",
}

# Set of packages that are not currently supported when building with tests.
TEMPORARY_UNSUPPORTED_PACKAGES_WITH_TESTS = {
    "chromeos-base/screen-capture-utils",
    "chromeos-base/update_engine",
    "chromeos-base/mtpd",
    "net-wireless/floss",
}

# Set of packages failing test run. To be skipped for test run.
PACKAGES_FAILING_TESTS = {
    "chromeos-base/vboot_reference",
    "chromeos-base/chromeos-installer",
    "chromeos-base/chromeos-init",
    "chromeos-base/chromeos-trim",
}
