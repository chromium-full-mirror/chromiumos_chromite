# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A dumping ground for constants shared across multiple modules."""

import os
from pathlib import Path


THIS_FILE = Path(__file__).resolve()


def _FindSourceRoot() -> Path:
    """Try and find the root check out of the chromiumos tree"""
    source_root = path = THIS_FILE.parent.parent.parent
    root = Path("/")
    while True:
        if (path / ".repo").is_dir():
            return path
        if path == root:
            break
        # CitC is one level above the real source root.
        if (path.parent / ".citc").is_dir():
            return path
        path = path.parent
    return source_root


SOURCE_ROOT = _FindSourceRoot()
CHROOT_SOURCE_ROOT = Path("/mnt/host/source")
CHROOT_OUT_ROOT = Path("/mnt/host/out")
CHROOT_CACHE_ROOT = Path("/var/cache/chromeos-cache")
CHROOT_EDB_CACHE_ROOT = Path("/var/cache/edb")
DEPOT_TOOLS_SUBPATH = Path("src/chromium/depot_tools")

CROSUTILS_DIR = SOURCE_ROOT / "src/scripts"
CHROMITE_DIR = THIS_FILE.parent.parent
CHROMITE_SHELL_DIR = CHROMITE_DIR / "shell"
BRANCHED_CHROMITE_DIR = SOURCE_ROOT / "chromite"
IS_BRANCHED_CHROMITE = CHROMITE_DIR == BRANCHED_CHROMITE_DIR
DEPOT_TOOLS_DIR = SOURCE_ROOT / DEPOT_TOOLS_SUBPATH
CHROMITE_BIN_SUBDIR = Path("chromite/bin")
CHROMITE_BIN_DIR = CHROMITE_DIR / "bin"
CHROMITE_SCRIPTS_DIR = CHROMITE_DIR / "scripts"
DEFAULT_CHROOT_DIR = "chroot"
DEFAULT_CHROOT_PATH = os.path.join(SOURCE_ROOT, DEFAULT_CHROOT_DIR)
DEFAULT_OUT_DIR = Path("out")
DEFAULT_OUT_PATH = SOURCE_ROOT / DEFAULT_OUT_DIR
DEFAULT_BUILD_ROOT = SOURCE_ROOT / "src" / "build"
BAZEL_WORKSPACE_ROOT = SOURCE_ROOT / "src"

STATEFUL_DIR = "/mnt/stateful_partition"

# User ID and group ID for "portage".
PORTAGE_UID = 250
PORTAGE_GID = 250

# These constants are defined and used in the die_hook that logs failed
# packages: 'cros_log_failed_packages' in profiles/base/profile.bashrc in
# chromiumos-overlay. The status file is generated in CROS_METRICS_DIR, and
# only if that environment variable is defined.
CROS_METRICS_DIR_ENVVAR = "CROS_METRICS_DIR"
DIE_HOOK_STATUS_FILE_NAME = "FAILED_PACKAGES"
METRICS_FILE = "METRICS_FILE"

# SDK overlay tarballs created during SDK builder runs. The paths are relative
# to the build root's chroot, which guarantees that they are reachable from it
# and get cleaned up when it is removed.
SDK_TOOLCHAINS_OUTPUT = "tmp/toolchain-pkgs"
# The filename of the SDK tarball created during SDK builder runs.
SDK_TARBALL_NAME = "built-sdk.tar.zst"

AUTOTEST_BUILD_PATH = "usr/local/build/autotest"
UNITTEST_PKG_PATH = "tmp/test-packages"

# Path to the lsb-release file on the device.
LSB_RELEASE_PATH = "/etc/lsb-release"

GOB_HOST = "%s.googlesource.com"

EXTERNAL_GOB_INSTANCE = "chromium"
EXTERNAL_GERRIT_INSTANCE = "chromium-review"
EXTERNAL_GOB_HOST = GOB_HOST % EXTERNAL_GOB_INSTANCE
EXTERNAL_GERRIT_HOST = GOB_HOST % EXTERNAL_GERRIT_INSTANCE
EXTERNAL_GOB_URL = "https://%s" % EXTERNAL_GOB_HOST
EXTERNAL_GERRIT_URL = "https://%s" % EXTERNAL_GERRIT_HOST
EXTERNAL_MANIFEST_REMOTE = "cros"
EXTERNAL_MANIFEST_PROJECT = "chromiumos/manifest"
EXTERNAL_MANIFEST_URL = f"{EXTERNAL_GOB_URL}/{EXTERNAL_MANIFEST_PROJECT}"

INTERNAL_GOB_INSTANCE = "chrome-internal"
INTERNAL_GERRIT_INSTANCE = "chrome-internal-review"
INTERNAL_GOB_HOST = GOB_HOST % INTERNAL_GOB_INSTANCE
INTERNAL_GERRIT_HOST = GOB_HOST % INTERNAL_GERRIT_INSTANCE
INTERNAL_GOB_URL = "https://%s" % INTERNAL_GOB_HOST
INTERNAL_GERRIT_URL = "https://%s" % INTERNAL_GERRIT_HOST
INTERNAL_MANIFEST_REMOTE = "cros-internal"
INTERNAL_MANIFEST_PROJECT = "chromeos/manifest-internal"
INTERNAL_MANIFEST_URL = f"{INTERNAL_GOB_URL}/{INTERNAL_MANIFEST_PROJECT}"

GOB_COOKIE_PATH = Path("~/.git-credential-cache/cookie").expanduser()
GITCOOKIES_PATH = Path("~/.gitcookies").expanduser()

# Timestamps in the JSON from GoB's web interface is of the form 'Tue
# Dec 02 17:48:06 2014' and is assumed to be in UTC.
GOB_COMMIT_TIME_FORMAT = "%a %b %d %H:%M:%S %Y"

CHROMIUM_SRC_PROJECT = "chromium/src"
CHROMIUM_GOB_URL = "%s/%s.git" % (EXTERNAL_GOB_URL, CHROMIUM_SRC_PROJECT)

SHARED_CACHE_ENVVAR = "CROS_CACHEDIR"
PARALLEL_EMERGE_STATUS_FILE_ENVVAR = "PARALLEL_EMERGE_STATUS_FILE"

PATCH_BRANCH = "patch_branch"
STABLE_EBUILD_BRANCH = "stabilizing_branch"
MERGE_BRANCH = "merge_branch"

# SDK target.
TARGET_SDK = "virtual/target-sdk"
TARGET_SDK_BROOT = "virtual/target-sdk-broot"
# Default OS target packages.
TARGET_OS_PKG = "virtual/target-os"
TARGET_OS_DEV_PKG = "virtual/target-os-dev"
TARGET_OS_TEST_PKG = "virtual/target-os-test"
TARGET_OS_FACTORY_PKG = "virtual/target-os-factory"
TARGET_OS_FACTORY_SHIM_PKG = "virtual/target-os-factory-shim"
# All virtuals used for a full build of a board.
ALL_TARGET_PACKAGES = (
    TARGET_OS_PKG,
    TARGET_OS_DEV_PKG,
    TARGET_OS_TEST_PKG,
    TARGET_OS_FACTORY_PKG,
    TARGET_OS_FACTORY_SHIM_PKG,
)

# Paths excluded when packaging SDK artifacts. These are relative to the target
# build root where SDK packages are being installed (e.g. /build/amd64-host).
SDK_PACKAGE_EXCLUDED_PATHS = (
    "usr/lib/debug",
    "usr/lib64/debug",
    AUTOTEST_BUILD_PATH,
    "packages",
    "tmp",
)

# Portage category and package name for Chrome.
CHROME_CN = "chromeos-base"
CHROME_PN = "chromeos-chrome"
CHROME_CP = f"{CHROME_CN}/{CHROME_PN}"

# Other packages to uprev while uprevving Chrome.
OTHER_CHROME_PACKAGES = (
    "chromeos-base/chromium-source",
    "chromeos-base/chrome-icu",
)

# Chrome + OTHER_CHROME_PACKAGES.
ALL_CHROME_PACKAGES = (CHROME_CP,) + OTHER_CHROME_PACKAGES

# How long we should wait for the signing fleet to sign payloads.
PAYLOAD_SIGNING_TIMEOUT = 10800

# Special build type for Chroot builders.  These builds focus on building
# toolchains and validate that they work.
CHROOT_BUILDER_BOARD = "amd64-host"

CHROMIUMOS_OVERLAY_DIR = "src/third_party/chromiumos-overlay"
CHROMEOS_OVERLAY_DIR = "src/private-overlays/chromeos-overlay/"
PORTAGE_STABLE_OVERLAY_DIR = "src/third_party/portage-stable"
ECLASS_OVERLAY_DIR = "src/third_party/eclass-overlay"
CHROMEOS_PARTNER_OVERLAY_DIR = "src/private-overlays/chromeos-partner-overlay/"
PUBLIC_BINHOST_CONF_DIR = os.path.join(
    CHROMIUMOS_OVERLAY_DIR, "chromeos/binhost"
)
PRIVATE_BINHOST_CONF_DIR = os.path.join(
    CHROMEOS_PARTNER_OVERLAY_DIR, "chromeos/binhost"
)
HOST_PREBUILT_CONF_FILE = "src/overlays/overlay-amd64-host/prebuilt.conf"
HOST_PREBUILT_CONF_FILE_FULL_PATH = SOURCE_ROOT / HOST_PREBUILT_CONF_FILE
MAKE_CONF_AMD64_HOST_FILE = os.path.join(
    CHROMIUMOS_OVERLAY_DIR, "chromeos/config/make.conf.amd64-host"
)
MAKE_CONF_AMD64_HOST_FILE_FULL_PATH = SOURCE_ROOT / MAKE_CONF_AMD64_HOST_FILE

VERSION_FILE = os.path.join(
    CHROMIUMOS_OVERLAY_DIR, "chromeos/config/chromeos_version.sh"
)
SDK_VERSION_FILE = os.path.join(
    PUBLIC_BINHOST_CONF_DIR, "host/sdk_version.conf"
)
SDK_VERSION_FILE_FULL_PATH = SOURCE_ROOT / SDK_VERSION_FILE
SDK_GS_BUCKET = "chromiumos-sdk"

PUBLIC = "public"
PRIVATE = "private"

BOTH_OVERLAYS = "both"
PUBLIC_OVERLAYS = PUBLIC
PRIVATE_OVERLAYS = PRIVATE
VALID_OVERLAYS = [BOTH_OVERLAYS, PUBLIC_OVERLAYS, PRIVATE_OVERLAYS, None]

# Common default logging settings for use with the logging module.
LOGGER_FMT = "%(asctime)s: %(levelname)s: %(message)s"
LOGGER_DATE_FMT = "%Y-%m-%d"
LOGGER_TIME_FMT = "%H:%M:%S"
LOGGER_DATETIME_FMT = f"{LOGGER_DATE_FMT} {LOGGER_TIME_FMT}"

# Telemetry configurations.
# Script names for the following configs must be the basename of the executed
# file. For chromite, the executed file is the relevant wrapper.py symlink,
# which in practice will rarely be different but can have - vs _ differences.
# e.g. chromite/scripts/cros_workon.py = chromite/bin/cros-workon = cros-workon.
# The name of scripts that need telemetry disabled.
TELEMETRY_DISABLED_SCRIPTS = frozenset(
    (
        # Explicitly enabled in the script.
        # Full path: chromite/scripts/publish_telemetry.
        "publish_telemetry",
        # Called in awkward location where it is difficult to apply addwrite.
        # It's well understood and not generally run manually anyway.
        # Full path: chromite/licensing/ebuild_license_hook
        "ebuild_license_hook",
        # Called by emerge in awkward location where sandbox exceptions can't be
        # added.
        # Full path: chromite/scripts/package_has_missing_deps
        "package_has_missing_deps",
    )
)
# The name of scripts that need just telemetry publishing disabled.
TELEMETRY_PUBLISH_DISABLED_SCRIPTS = frozenset()
# Allow setting CHROMITE_TELEMETRY_DISABLE="1" in the env to completely skip
# telemetry initialization. Escape hatch in case of bugs.
TELEMETRY_DISABLED_ENVVAR = "CROS_TELEMETRY_DISABLE"

# Used by remote patch serialization/deserialzation.
INTERNAL_PATCH_TAG = "i"
EXTERNAL_PATCH_TAG = "e"
PATCH_TAGS = (INTERNAL_PATCH_TAG, EXTERNAL_PATCH_TAG)

# Environment variables that should be exposed to all children processes
# invoked via cros_build_lib.run.
ENV_PASSTHRU = (
    "CROS_SUDO_KEEP_ALIVE",
    SHARED_CACHE_ENVVAR,
    PARALLEL_EMERGE_STATUS_FILE_ENVVAR,
    # If the user doesn't want bytecode written, don't.
    "PYTHONDONTWRITEBYTECODE",
    # Maintaining a duplicate here to avoid performance penalty associated with
    # importing `chromite.utils.telemetry.trace` package.
    "traceparent",
    TELEMETRY_DISABLED_ENVVAR,
)

# List of variables to proxy into the chroot from the host, and to
# have sudo export if existent.
CHROOT_ENVIRONMENT_ALLOWLIST = (
    "BAZEL_USE_REMOTE_CACHING",
    "CHROMEOS_OFFICIAL",
    "CHROMEOS_VERSION_AUSERVER",
    "CHROMEOS_VERSION_DEVSERVER",
    "CHROMEOS_VERSION_TRACK",
    "CROS_CLEAN_OUTDATED_PKGS",
    "CROS_COG_WORKSPACE_ID",
    "CROS_WORKON_SRCROOT",
    "GCE_METADATA_HOST",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_NAME",
    "GIT_PROXY_COMMAND",
    "GIT_SSH",
    "NOCOLOR",
    "PORTAGE_USERNAME",
    "PYTHONDONTWRITEBYTECODE",
    "RSYNC_PROXY",
    "SSH_AGENT_PID",
    "SSH_AUTH_SOCK",
    "TMUX",
    "USE",
    "USE_PINNED_CHROMITE",
    "all_proxy",
    "ftp_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "traceparent",
    TELEMETRY_DISABLED_ENVVAR,
)

# Paths for Chrome LKGM which are relative to the Chromium base url.
CHROME_LKGM_FILE = "CHROMEOS_LKGM"
PATH_TO_CHROME_LKGM = "chromeos/%s" % CHROME_LKGM_FILE
# Path for the Chrome LKGM's closest OWNERS file.
PATH_TO_CHROME_CHROMEOS_OWNERS = "chromeos/OWNERS"

# Cache constants.
COMMON_CACHE = "common"


# Artifact constants.
def _SlashToUnderscore(string: str) -> str:
    return string.replace("/", "_")


# GCE tar ball constants.
def ImageBinToGceTar(image_bin: str) -> str:
    assert image_bin.endswith(".bin"), (
        'Filename %s does not end with ".bin"' % image_bin
    )
    return "%s_gce.tar.gz" % os.path.splitext(image_bin)[0]


TRASH_BUCKET = "gs://chromeos-throw-away-bucket"
CHROME_SYSROOT_TAR = "sysroot_%s.tar.xz" % _SlashToUnderscore(CHROME_CP)
CHROME_ENV_TAR = "environment_%s.tar.xz" % _SlashToUnderscore(CHROME_CP)
CHROME_ENV_FILE = "environment"
BASE_IMAGE_NAME = "chromiumos_base_image"
BASE_IMAGE_TAR = "%s.tar.xz" % BASE_IMAGE_NAME
BASE_IMAGE_BIN = "%s.bin" % BASE_IMAGE_NAME
IMAGE_SCRIPTS_NAME = "image_scripts"
IMAGE_SCRIPTS_TAR = "%s.tar.xz" % IMAGE_SCRIPTS_NAME
TARGET_SYSROOT_TAR = "sysroot_%s.tar.xz" % _SlashToUnderscore(TARGET_OS_PKG)
VM_IMAGE_NAME = "chromiumos_qemu_image"
VM_IMAGE_BIN = "%s.bin" % VM_IMAGE_NAME
BASE_GUEST_VM_DIR = "guest-vm-base"
TEST_GUEST_VM_DIR = "guest-vm-test"
BASE_GUEST_VM_TAR = "%s.tar.xz" % BASE_GUEST_VM_DIR
TEST_GUEST_VM_TAR = "%s.tar.xz" % TEST_GUEST_VM_DIR

KERNEL_IMAGE_NAME = "vmlinuz"
KERNEL_IMAGE_BIN = "%s.bin" % KERNEL_IMAGE_NAME
KERNEL_IMAGE_TAR = "%s.tar.xz" % KERNEL_IMAGE_NAME
KERNEL_IMAGE_IMG = "%s.image" % KERNEL_IMAGE_NAME
KERNEL_SYMBOL_NAME = "vmlinux.debug"

TEST_IMAGE_NAME = "chromiumos_test_image"
TEST_IMAGE_TAR = "%s.tar.xz" % TEST_IMAGE_NAME
TEST_IMAGE_BIN = "%s.bin" % TEST_IMAGE_NAME
TEST_IMAGE_GCE_TAR = ImageBinToGceTar(TEST_IMAGE_BIN)
TEST_KEY_PRIVATE = "id_rsa"

BREAKPAD_DEBUG_SYMBOLS_NAME = "debug_breakpad"
BREAKPAD_DEBUG_SYMBOLS_TAR = "%s.tar.xz" % BREAKPAD_DEBUG_SYMBOLS_NAME

# Code coverage related constants
CODE_COVERAGE_EXCLUDE_DIRS = ("src/platform/ec/",)
CODE_COVERAGE_LLVM_JSON_SYMBOLS_NAME = "code_coverage"
CODE_COVERAGE_LLVM_JSON_SYMBOLS_TAR = (
    "%s.tar.xz" % CODE_COVERAGE_LLVM_JSON_SYMBOLS_NAME
)
CODE_COVERAGE_GOLANG_NAME = "code_coverage_go"
CODE_COVERAGE_GOLANG_TAR = "%s.tar.xz" % CODE_COVERAGE_GOLANG_NAME
CODE_COVERAGE_LLVM_FILE_NAME = "coverage.json"
ZERO_COVERAGE_FILE_EXTENSIONS_TO_PROCESS = {
    "RUST": [".rs"],
    "CPP": [".cc", ".c", ".cpp"],
}
ZERO_COVERAGE_EXCLUDE_LINE_PREFIXES = {
    "CPP": (
        "/*",
        "#include",
        "//",
        "* ",
        "*/",
        "\n",
        "}\n",
        "};\n",
        "**/\n",
    ),
    "RUST": (
        "/*",
        "//",
        "* ",
        "*/",
        "fn ",
        "\n",
        "}\n",
        "#",
        "use",
        "pub mod",
        "impl ",
    ),
}
ZERO_COVERAGE_EXCLUDE_FILES_SUFFIXES = (
    # Exclude unit test code from zero coverage
    "test.c",
    "test.cc",
    "tests.c",
    "tests.cc",
    "test.cpp",
    "tests.cpp",
    "fuzzer.c",
    "fuzzer.cc",
    "fuzzer.cpp",
)

DEBUG_SYMBOLS_NAME = "debug"
DEBUG_SYMBOLS_TAR = "%s.tgz" % DEBUG_SYMBOLS_NAME

DEV_IMAGE_NAME = "chromiumos_image"
DEV_IMAGE_BIN = "%s.bin" % DEV_IMAGE_NAME

RECOVERY_IMAGE_NAME = "recovery_image"
RECOVERY_IMAGE_BIN = "%s.bin" % RECOVERY_IMAGE_NAME
RECOVERY_IMAGE_TAR = "%s.tar.xz" % RECOVERY_IMAGE_NAME

FACTORY_IMAGE_NAME = "factory_install_shim"
FACTORY_IMAGE_BIN = f"{FACTORY_IMAGE_NAME}.bin"

FLEXOR_KERNEL_IMAGE_NAME = "flexor_vmlinuz"
FLEXOR_KERNEL_IMAGE_TAR = f"{FLEXOR_KERNEL_IMAGE_NAME}.tar.zst"

# Image type constants.
IMAGE_TYPE_BASE = "base"
IMAGE_TYPE_DEV = "dev"
IMAGE_TYPE_TEST = "test"
IMAGE_TYPE_RECOVERY = "recovery"
# This is the image type used by legacy CBB configs.
IMAGE_TYPE_FACTORY = "factory"
# This is the image type for the factory image type in `cros build-image`.
IMAGE_TYPE_FACTORY_SHIM = "factory_install"
IMAGE_TYPE_FIRMWARE = "firmware"
# Firmware for cros hps device src/platform/hps-firmware2.
IMAGE_TYPE_HPS_FIRMWARE = "hps_firmware"
# USB PD accessory microcontroller firmware (e.g. power brick, display dongle).
IMAGE_TYPE_ACCESSORY_USBPD = "accessory_usbpd"
# Standalone accessory microcontroller firmware (e.g. wireless keyboard).
IMAGE_TYPE_ACCESSORY_RWSIG = "accessory_rwsig"
# GSC Firmware.
IMAGE_TYPE_GSC_FIRMWARE = "gsc_firmware"
# Netboot kernel.
IMAGE_TYPE_NETBOOT = "netboot"
# Flexor.
IMAGE_TYPE_FLEXOR_KERNEL = "flexor"

IMAGE_TYPE_TO_NAME = {
    IMAGE_TYPE_BASE: BASE_IMAGE_BIN,
    IMAGE_TYPE_DEV: DEV_IMAGE_BIN,
    IMAGE_TYPE_RECOVERY: RECOVERY_IMAGE_BIN,
    IMAGE_TYPE_TEST: TEST_IMAGE_BIN,
    IMAGE_TYPE_FACTORY_SHIM: FACTORY_IMAGE_BIN,
    IMAGE_TYPE_FLEXOR_KERNEL: FLEXOR_KERNEL_IMAGE_NAME,
}
IMAGE_NAME_TO_TYPE = dict((v, k) for k, v in IMAGE_TYPE_TO_NAME.items())

BUILD_REPORT_JSON = "build_report.json"
METADATA_JSON = "metadata.json"
PARTIAL_METADATA_JSON = "partial-metadata.json"

FIRMWARE_ARCHIVE_NAME = "firmware_from_source.tar.bz2"
FIRMWARE_PINNED_ARCHIVE_NAME = "pinned_firmware.tar.bz2"
FPMCU_UNITTESTS_ARCHIVE_NAME = "fpmcu_unittests.tar.bz2"

# Email alias to add as reviewer in Gerrit, which GWSQ will then automatically
# assign to the current gardener.
CHROME_GARDENER_REVIEW_EMAIL = "chrome-os-gardeners-reviews@google.com"

# Email validation regex. Not quite fully compliant with RFC 2822, but good
# approximation.
EMAIL_REGEX = r"[A-Za-z0-9._%~+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,4}"

# Partition labels.
PART_STATE = "STATE"
PART_ROOT_A = "ROOT-A"
PART_ROOT_B = "ROOT-B"
PART_KERN_A = "KERN-A"
PART_KERN_B = "KERN-B"
PART_MINIOS_A = "MINIOS-A"
PART_MINIOS_B = "MINIOS-B"
PART_POWERWASH_DATA = "POWERWASH-DATA"

# Crossystem related constants.
MINIOS_PRIORITY = "minios_priority"

# Quick provision payloads. These file names should never be changed, otherwise
# very bad things can happen :). The reason is we have already uploaded these
# files with these names for all boards. So if the name changes, all scripts
# that have been using this need to handle both cases to be backward compatible.
QUICK_PROVISION_PAYLOAD_KERNEL = "full_dev_part_KERN.bin.gz"
QUICK_PROVISION_PAYLOAD_ROOTFS = "full_dev_part_ROOT.bin.gz"
QUICK_PROVISION_PAYLOAD_MINIOS = "full_dev_part_MINIOS.bin.gz"
QUICK_PROVISION_PAYLOAD_STATEFUL = "stateful.tgz"

# Payloads used for provision/flash.
# For bandwidth-constrained networks, use these payloads.
FULL_PAYLOAD_KERN = "full_KERN.bin.zst"
FULL_PAYLOAD_ROOT = "full_ROOT.bin.zst"
FULL_PAYLOAD_MINIOS = "full_MINIOS.bin.zst"
STATEFUL_PAYLOAD = "stateful.zst"

# Dev key related names.
VBOOT_DEVKEYS_DIR = os.path.join("/usr/share/vboot/devkeys")
KERNEL_PUBLIC_SUBKEY = "kernel_subkey.vbpubk"
KERNEL_DATA_PRIVATE_KEY = "kernel_data_key.vbprivk"
KERNEL_KEYBLOCK = "kernel.keyblock"
RECOVERY_PUBLIC_KEY = "recovery_key.vbpubk"
RECOVERY_DATA_PRIVATE_KEY = "recovery_kernel_data_key.vbprivk"
RECOVERY_KEYBLOCK = "recovery_kernel.keyblock"
MINIOS_DATA_PRIVATE_KEY = "minios_kernel_data_key.vbprivk"
MINIOS_KEYBLOCK = "minios_kernel.keyblock"

# Portage log paths.
PORTAGE_LOG_DIR = Path("/var/log/portage")
PORTAGE_DEPGRAPH_COUNTERS_LOG = PORTAGE_LOG_DIR / "depgraph_counters.log"
