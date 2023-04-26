# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration options for various cbuildbot builders."""

import copy
import logging
import re

from chromite.config import chromeos_config_boards as chromeos_boards
from chromite.config import chromeos_test_config as chromeos_test
from chromite.config.chromeos_test_config import HWTestList
from chromite.config.chromeos_test_config import TRADITIONAL_VM_TESTS_SUPPORTED
from chromite.lib import config_lib
from chromite.lib import constants
from chromite.utils import memoize


def _frozen_ge_set(ge_build_config, values, extras=None):
    """Return a frozenset of things in GE."""
    separate_board_names = set(
        config_lib.GeBuildConfigAllBoards(ge_build_config)
    )
    unified_builds = config_lib.GetUnifiedBuildConfigAllBuilds(ge_build_config)
    unified_board_names = set(
        [
            b[config_lib.CONFIG_TEMPLATE_REFERENCE_BOARD_NAME]
            for b in unified_builds
        ]
    )
    board_names = separate_board_names | unified_board_names
    return frozenset(x for x in values if x in board_names).union(
        extras or frozenset()
    )


def add_images(required_images):
    """Add required images when applying changes to a BuildConfig.

    Used similarly to append_useflags.

    Args:
      required_images: A list of image names that need to be present in the
                       final build config.

    Returns:
      A callable suitable for use with BuildConfig.apply.
    """
    required_images = set(required_images)

    def handler(old_images):
        if not old_images:
            old_images = []

        new_images = old_images
        for image_name in required_images:
            if set(required_images).issubset(new_images):
                break
            new_images.append(image_name)
        return new_images

    return handler


def remove_images(unsupported_images):
    """Remove unsupported images when applying changes to a BuildConfig.

    Used similarly to append_useflags.

    Args:
      unsupported_images: A list of image names that should not be present
                          in the final build config.

    Returns:
      A callable suitable for use with BuildConfig.apply.
    """
    unsupported = set(unsupported_images)

    def handler(old_images):
        if not old_images:
            old_images = []
        return [i for i in old_images if i not in unsupported]

    return handler


def GetBoardTypeToBoardsDict(ge_build_config):
    """Get board type to board names dict.

    Args:
      ge_build_config: Dictionary containing the decoded GE configuration file.

    Returns:
      A dict mapping board types to board name collections.
      The dict contains board types including distinct_board_sets,
      all_release_boards, all_full_boards, all_boards, internal_boards,
      and no_vmtest_boards.
    """
    ge_arch_board_dict = config_lib.GetArchBoardDict(ge_build_config)

    boards_dict = {}

    arm_internal_release_boards = (
        chromeos_boards.arm_internal_release_boards
        | ge_arch_board_dict.get(config_lib.CONFIG_ARM_INTERNAL, set())
    )
    arm_external_boards = (
        chromeos_boards.arm_external_boards
        | ge_arch_board_dict.get(config_lib.CONFIG_ARM_EXTERNAL, set())
    )

    x86_internal_release_boards = (
        chromeos_boards.x86_internal_release_boards
        | ge_arch_board_dict.get(config_lib.CONFIG_X86_INTERNAL, set())
    )
    x86_external_boards = (
        chromeos_boards.x86_external_boards
        | ge_arch_board_dict.get(config_lib.CONFIG_X86_EXTERNAL, set())
    )

    # Every board should be in only 1 of the above sets.
    boards_dict["distinct_board_sets"] = [
        arm_internal_release_boards,
        arm_external_boards,
        x86_internal_release_boards,
        x86_external_boards,
    ]

    arm_full_boards = arm_internal_release_boards | arm_external_boards
    x86_full_boards = x86_internal_release_boards | x86_external_boards

    arm_boards = arm_full_boards
    x86_boards = x86_full_boards

    boards_dict["all_release_boards"] = (
        arm_internal_release_boards | x86_internal_release_boards
    )
    boards_dict["all_full_boards"] = arm_full_boards | x86_full_boards
    all_boards = x86_boards | arm_boards
    boards_dict["all_boards"] = all_boards

    boards_dict["internal_boards"] = boards_dict["all_release_boards"]

    # This set controls the final vmtest override. It allows us to specify
    # vm_tests for each class of builders, but only execute on vmtest_boards.
    boards_dict["no_vmtest_boards"] = all_boards - chromeos_test.vmtest_boards

    boards_dict["generic_kernel_boards"] = frozenset(
        ["amd64-generic", "arm-generic", "arm64-generic"]
    )

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
    defaults["manifest_repo_url"] = config_lib.GetSiteParams().MANIFEST_URL

    return defaults


def GeneralTemplates(site_config):
    """Defines templates that are shared between categories of builders.

    Args:
      site_config: A SiteConfig object to add the templates too.
      ge_build_config: Dictionary containing the decoded GE configuration file.
    """
    # Config parameters for builders that do not run tests on the builder.
    site_config.AddTemplate(
        "no_unittest_builder",
        unittests=False,
    )

    # Builder type templates.

    site_config.AddTemplate(
        "full",
        # Full builds are test builds to show that we can build from scratch,
        # so use settings to build from scratch, and archive the results.
        usepkg_build_packages=False,
        chrome_sdk=True,
        build_timeout=12 * 60 * 60,
        display_label=config_lib.DISPLAY_LABEL_FULL,
        build_type=constants.FULL_TYPE,
        luci_builder=config_lib.LUCI_BUILDER_FULL,
        archive_build_debug=True,
        images=["base", "recovery", "test", "factory_install"],
        git_sync=True,
        description="Full Builds",
        image_test=True,
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-Continuous",
    )

    # Incremental builders are intended to test the developer workflow.
    # For that reason, they don't uprev.
    site_config.AddTemplate(
        "incremental",
        display_label=config_lib.DISPLAY_LABEL_INCREMENATAL,
        build_type=constants.INCREMENTAL_TYPE,
        luci_builder=config_lib.LUCI_BUILDER_INCREMENTAL,
        chroot_replace=False,
        uprev=False,
        overlays=constants.PUBLIC_OVERLAYS,
        description="Incremental Builds",
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-Continuous",
    )

    site_config.AddTemplate(
        "informational",
        display_label=config_lib.DISPLAY_LABEL_INFORMATIONAL,
        description="Informational Builds",
        luci_builder=config_lib.LUCI_BUILDER_INFORMATIONAL,
    )

    site_config.AddTemplate(
        "external",
        internal=False,
        overlays=constants.PUBLIC_OVERLAYS,
        manifest_repo_url=config_lib.GetSiteParams().MANIFEST_URL,
        manifest=constants.DEFAULT_MANIFEST,
    )

    # This builds with more source available.
    site_config.AddTemplate(
        "internal",
        internal=True,
        overlays=constants.BOTH_OVERLAYS,
        manifest_repo_url=config_lib.GetSiteParams().MANIFEST_INT_URL,
    )

    site_config.AddTemplate(
        "infra_builder",
        luci_builder=config_lib.LUCI_BUILDER_INFRA,
    )

    site_config.AddTemplate(
        "brillo",
        sync_chrome=False,
        chrome_sdk=False,
        dev_installer_prebuilts=False,
    )

    site_config.AddTemplate(
        "termina",
        sync_chrome=False,
        chrome_sdk=False,
        dev_installer_prebuilts=False,
        signer_tests=False,
        sign_types=None,
        paygen=False,
        upload_hw_test_artifacts=False,
        upload_stripped_packages=["sys-kernel/*kernel*"],
        image_test=False,
        guest_vm_image=True,
        images=["base", "test"],
        packages=[
            "virtual/target-os",
            "virtual/target-os-dev",
            "virtual/target-os-test",
        ],
    )

    site_config.AddTemplate(
        "loonix",
        factory=False,
        factory_install_netboot=False,
        factory_toolkit=False,
        sync_chrome=False,
        chrome_sdk=False,
        dev_installer_prebuilts=False,
        # TODO(harshmodi): Re-enable this when we start using vboot
        signer_tests=False,
        paygen=False,
        upload_hw_test_artifacts=False,
        image_test=False,
        images=remove_images(["recovery", "factory_install"]),
    )

    site_config.AddTemplate("wshwos", site_config.templates.loonix)

    site_config.AddTemplate(
        "dustbuster",
        # TODO(ehislen): Starting with loonix but will diverge later.
        site_config.templates.loonix,
        # Disable rootfs_verification until Dustbuster is ready.
        rootfs_verification=False,
    )

    site_config.AddTemplate(
        "beaglebone",
        site_config.templates.brillo,
        image_test=False,
        rootfs_verification=False,
        paygen=False,
        signer_tests=False,
        images=remove_images(["dev", "test", "recovery", "factory_install"]),
    )

    # This adds Chrome branding.
    site_config.AddTemplate(
        "official_chrome",
        useflags=config_lib.append_useflags([constants.USE_CHROME_INTERNAL]),
    )

    # This sets chromeos_official.
    site_config.AddTemplate(
        "official",
        site_config.templates.official_chrome,
        chromeos_official=True,
    )

    site_config.AddTemplate(
        "fuzzer",
        site_config.templates.internal,
        site_config.templates.informational,
        profile="fuzzer",
        chrome_sdk=False,
        sync_chrome=True,
        usepkg_build_packages=False,
        # Run fuzzer builder specific stages.
        builder_class_name="fuzzer_builders.FuzzerBuilder",
        # Need larger rootfs since fuzzing also enables asan.
        disk_layout="2gb-rootfs",
        gs_path="gs://chromeos-fuzzing-artifacts/libfuzzer-asan-buganizer",
        images=[],
        image_test=None,
        packages=["virtual/target-fuzzers"],
    )

    site_config.AddTemplate(
        "pre_flight_branch",
        site_config.templates.internal,
        site_config.templates.official_chrome,
        build_type=constants.PFQ_TYPE,
        luci_builder=config_lib.LUCI_BUILDER_PFQ,
        build_timeout=20 * 60,
        manifest_version=True,
        branch=True,
        master=True,
        slave_configs=[],
        vm_tests=[],
        vm_tests_override=TRADITIONAL_VM_TESTS_SUPPORTED,
        hw_tests=[],
        hw_tests_override=[],
        unittests=False,
        uprev=True,
        overlays=constants.BOTH_OVERLAYS,
        push_overlays=constants.BOTH_OVERLAYS,
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-Chrome-PFQ",
    )

    # Internal incremental builders don't use official chrome because we want
    # to test the developer workflow.
    site_config.AddTemplate(
        "internal_incremental",
        site_config.templates.internal,
        site_config.templates.incremental,
        overlays=constants.BOTH_OVERLAYS,
        description="Incremental Builds (internal)",
    )

    # A test-ap image is just a test image with a special profile enabled.
    # Note that each board enabled for test-ap use has to have the testbed-ap
    # profile linked to from its private overlay.
    site_config.AddTemplate(
        "test_ap",
        site_config.templates.internal,
        display_label=config_lib.DISPLAY_LABEL_UTILITY,
        build_type=constants.INCREMENTAL_TYPE,
        description="WiFi AP images used in testing",
        profile="testbed-ap",
    )

    site_config.AddTemplate(
        "release_common",
        site_config.templates.full,
        site_config.templates.official,
        site_config.templates.internal,
        display_label=config_lib.DISPLAY_LABEL_RELEASE,
        build_type=constants.CANARY_TYPE,
        luci_builder=config_lib.LUCI_BUILDER_LEGACY_RELEASE,
        suite_scheduling=True,
        # Because release builders never use prebuilts, they need the
        # longer timeout.  See crbug.com/938958.
        build_timeout=18 * 60 * 60,
        useflags=config_lib.append_useflags(["-cros-debug", "thinlto"]),
        manifest=constants.OFFICIAL_MANIFEST,
        manifest_version=True,
        images=["base", "recovery", "test", "factory_install"],
        sign_types=["recovery", "accessory_rwsig"],
        push_image=True,
        upload_symbols=True,
        run_cpeexport=True,
        run_build_configs_export=True,
        binhost_bucket="gs://chromeos-dev-installer",
        binhost_key="RELEASE_BINHOST",
        binhost_base_url="https://commondatastorage.googleapis.com/"
        "chromeos-dev-installer",
        dev_installer_prebuilts=True,
        git_sync=False,
        vm_tests=[],
        vm_tests_override=[],
        paygen=True,
        signer_tests=True,
        hwqual=True,
        description="Release Builds (canary) (internal)",
        chrome_sdk=True,
        image_test=True,
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-Canaries",
    )

    site_config.AddTemplate(
        "release_basic",
        site_config.templates.release_common,
        luci_builder=config_lib.LUCI_BUILDER_LEGACY_RELEASE,
        description="Fail Fast Release Builds (canary) (internal)",
        basic_builder=True,
        notification_configs=[
            config_lib.NotificationConfig(email="navil+spam@chromium.org")
        ],
        chromeos_official=False,
        paygen=False,
        suite_scheduling=False,
        unittests=False,
        hw_tests=[],
        hw_tests_override=[],
        hwqual=False,
        image_test=False,
        paygen_skip_testing=True,
        signer_tests=False,
        vm_tests=[],
        vm_tests_override=None,
        push_image=False,
        sign_types=[],
        upload_symbols=False,
        upload_stripped_packages=[],
        archive=False,
        archive_build_debug=False,
        upload_standalone_images=False,
        upload_hw_test_artifacts=False,
        cpe_export=False,
        run_cpeexport=False,
        run_build_configs_export=False,
    )

    site_config.AddTemplate(
        "release",
        site_config.templates.release_common,
        luci_builder=config_lib.LUCI_BUILDER_LEGACY_RELEASE,
    )

    site_config.AddTemplate(
        "moblab_release",
        site_config.templates.release,
        description="Moblab release builders",
        images=["base", "recovery", "test"],
        signer_tests=False,
    )

    # Factory releases much inherit from these classes.
    # Modifications for these release builders should go here.

    # Naming conventions also must be followed. Factory branches must end
    # in "-factory".

    site_config.AddTemplate(
        "factory",
        site_config.templates.release_common,
        display_label=config_lib.DISPLAY_LABEL_FACTORY,
        chrome_sdk=False,
        chrome_sdk_build_chrome=False,
        description="Factory Builds",
        dev_installer_prebuilts=False,
        factory_toolkit=True,
        hwqual=False,
        images=["test", "factory_install"],
        image_test=False,
        luci_builder=config_lib.LUCI_BUILDER_FACTORY,
        paygen=False,
        signer_tests=False,
        sign_types=["factory"],
        upload_hw_test_artifacts=True,
        upload_symbols=False,
    )

    # This should be used by any "workspace_builders."
    site_config.AddTemplate(
        "workspace",
        postsync_patch=False,
    )

    site_config.AddTemplate(
        "payloads",
        site_config.templates.internal,
        site_config.templates.no_unittest_builder,
        display_label=config_lib.DISPLAY_LABEL_TRYJOB,
        build_type=constants.PAYLOADS_TYPE,
        luci_builder=config_lib.LUCI_BUILDER_LEGACY_RELEASE,
        builder_class_name="release_builders.GeneratePayloadsBuilder",
        description="Regenerate release payloads.",
        # Sync to the code used to do the build the first time.
        manifest_version=True,
        # This is the actual work we want to do.
        paygen=True,
        upload_hw_test_artifacts=False,
    )

    site_config.AddTemplate(
        "build_external_chrome",
        useflags=config_lib.append_useflags(
            ["-%s" % constants.USE_CHROME_INTERNAL]
        ),
    )

    # Tast is an alternate system for running integration tests.

    # The expression specified here matches the union of the tast.critical-* and
    # tast.informational-* Autotest server tests, which are executed by the
    # bvt-tast-cq and bvt-tast-informational suites on real hardware in the lab.
    site_config.AddTemplate(
        "tast_vm_canary_tests",
        tast_vm_tests=[
            config_lib.TastVMTestConfig(
                "tast_vm_canary_critical",
                ['("group:mainline" && !informational)'],
                timeout=210 * 60,
            ),
        ],
    )
    site_config.AddTemplate(
        "tast_vm_asan_tests",
        tast_vm_tests=[
            config_lib.TastVMTestConfig(
                "tast_vm_asan_critical",
                ['("group:asan" && !informational)'],
                timeout=2 * 60 * 60,
            ),
        ],
    )

    site_config.AddTemplate(
        "buildspec",
        site_config.templates.workspace,
        site_config.templates.internal,
        luci_builder=config_lib.LUCI_BUILDER_FACTORY,
        master=True,
        boards=[],
        build_type=constants.GENERIC_TYPE,
        uprev=True,
        overlays=constants.BOTH_OVERLAYS,
        push_overlays=constants.BOTH_OVERLAYS,
        builder_class_name="workspace_builders.BuildSpecBuilder",
        build_timeout=4 * 60 * 60,
        description="Buildspec creator.",
    )

    site_config.AddTemplate(
        "vm",
        site_config.templates.full,
        profile="vm-optimized",
    )

    site_config.AddTemplate(
        "asan",
        site_config.templates.full,
        site_config.templates.tast_vm_asan_tests,
        profile="asan",
        # TODO(crbug.com/1080416): Investigate why rootfs verification fails and
        #   re-enable it. It used to work till late 2019.
        rootfs_verification=False,
        # THESE IMAGES CAN DAMAGE THE LAB and cannot be used for hardware
        # testing.
        disk_layout="16gb-rootfs",
        # TODO(deymo): ASan builders generate bigger files, in particular a
        #   bigger Chrome binary, that update_engine can't handle in delta
        #   payloads due to memory limits. Remove the following lines once
        #   crbug.com/329248 is fixed.
        images=["base", "test"],
        chrome_sdk=False,
        vm_tests=[],
        vm_tests_override=None,
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-ASAN",
    )

    site_config.AddTemplate(
        "ubsan",
        profile="ubsan",
        # Need larger rootfs for ubsan builds.
        disk_layout="16gb-rootfs",
        images=["base", "test"],
        chrome_sdk=False,
        vm_tests=[],
        vm_tests_override=None,
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-ASAN",
    )


def CreateBoardConfigs(site_config, boards_dict, ge_build_config):
    """Create mixin templates for each board."""
    # Extract the full list of board names from GE data.
    separate_board_names = set(
        config_lib.GeBuildConfigAllBoards(ge_build_config)
    )
    unified_builds = config_lib.GetUnifiedBuildConfigAllBuilds(ge_build_config)
    unified_board_names = set(
        [
            b[config_lib.CONFIG_TEMPLATE_REFERENCE_BOARD_NAME]
            for b in unified_builds
        ]
    )
    board_names = separate_board_names | unified_board_names

    # TODO(crbug.com/648473): Remove these after GE adds them to their data set.
    board_names = board_names.union(boards_dict["all_boards"])

    result = dict()
    for board in board_names:
        board_config = config_lib.BuildConfig(boards=[board])

        if board in chromeos_boards.brillo_boards:
            board_config.apply(site_config.templates.brillo)
        if board in chromeos_boards.wshwos_boards:
            board_config.apply(site_config.templates.wshwos)
        if board in chromeos_boards.dustbuster_boards:
            board_config.apply(site_config.templates.dustbuster)
        if board in chromeos_boards.moblab_boards:
            board_config.apply(site_config.templates.moblab)
        if board in chromeos_boards.termina_boards:
            board_config.apply(site_config.templates.termina)
        if board in chromeos_boards.nofactory_boards:
            board_config.apply(
                factory=False,
                factory_toolkit=False,
                factory_install_netboot=False,
                images=remove_images(["factory_install"]),
            )
        if board in chromeos_boards.noimagetest_boards:
            board_config.apply(image_test=False)
        if board in chromeos_boards.nohwqual_boards:
            board_config.apply(hwqual=False)
        if board in chromeos_boards.base_layout_boards:
            board_config.apply(disk_layout="base")
        if board in chromeos_boards.beaglebone_boards:
            board_config.apply(site_config.templates.beaglebone)
        if board in chromeos_boards.builder_incompatible_binaries_boards:
            board_config.apply(unittests=False)

        result[board] = board_config

    return result


def CreateInternalBoardConfigs(site_config, boards_dict, ge_build_config):
    """Create mixin templates for each board."""
    result = CreateBoardConfigs(site_config, boards_dict, ge_build_config)

    for board in boards_dict["internal_boards"]:
        if board in result:
            result[board].apply(
                site_config.templates.internal,
                site_config.templates.official_chrome,
                manifest=constants.OFFICIAL_MANIFEST,
            )

    return result


def UpdateBoardConfigs(board_configs, boards, *args, **kwargs):
    """Update "board_configs" for selected chromeos_boards.

    Args:
      board_configs: Dict in CreateBoardConfigs format to filter from.
      boards: Iterable of boards to update in the dict.
      *args: List of templates to apply.
      **kwargs: Individual keys to update.

    Returns:
      Copy of board_configs dict with boards boards update with templates
      and values applied.
    """
    result = board_configs.copy()
    for b in boards:
        result[b] = result[b].derive(*args, **kwargs)

    return result


def ToolchainBuilders(site_config, boards_dict, ge_build_config):
    """Define templates used for toolchain builders.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
      boards_dict: A dict mapping board types to board name collections.
      ge_build_config: Dictionary containing the decoded GE configuration file.
    """
    board_configs = CreateInternalBoardConfigs(
        site_config, boards_dict, ge_build_config
    )
    hw_test_list = HWTestList(ge_build_config)

    site_config.AddTemplate(
        "base_toolchain",
        # Full build, AFDO, latest-toolchain, -cros-debug, and simple-chrome.
        site_config.templates.full,
        display_label=config_lib.DISPLAY_LABEL_TOOLCHAIN,
        build_type=constants.TOOLCHAIN_TYPE,
        build_timeout=(15 * 60 + 50) * 60,
        # Need to re-enable platform_SyncCrash after issue crosbug/658864 is
        # fixed. Need to re-enable network_VPNConnect.* tests after issue
        # crosbug/585936 is fixed. Need to re-enable
        # power_DarkResumeShutdownServer after issue crosbug/689598 is fixed.
        # According to crosbug/653496 security_OpenFDs will not work for
        # non-official builds, so we need to leave it permanently disabled.
        # Need to reenable power_DarkResumeDisplay after crosbug/703250 is
        # fixed.
        # Need to reenable cheets_SELinuxTest after crosbug/693308 is fixed.
        # Add strict_toolchain_checks to perform toolchain-related checks
        useflags=config_lib.append_useflags(
            [
                "-cros-debug",
                "-tests_security_OpenFDs",
                "-tests_platform_SyncCrash",
                "-tests_network_VPNConnect.l2tpipsec_xauth",
                "-tests_network_VPNConnect.l2tpipsec_psk",
                "-tests_power_DarkResumeShutdownServer",
                "-tests_power_DarkResumeDisplay",
                "-tests_cheets_SELinuxTest",
                "thinlto",
                "strict_toolchain_checks",
            ]
        ),
        latest_toolchain=True,
        enable_skylab_hw_tests=True,
        debuginfo_test=True,
    )

    site_config.AddTemplate(
        "toolchain",
        site_config.templates.base_toolchain,
        site_config.templates.internal,
        site_config.templates.official_chrome,
        site_config.templates.no_vmtest_builder,
        images=["base", "test", "recovery"],
        manifest=constants.OFFICIAL_MANIFEST,
        manifest_version=True,
        git_sync=False,
        description="Toolchain Builds (internal)",
    )
    site_config.AddTemplate(
        "llvm_toolchain",
        site_config.templates.toolchain,
        description="Full release build with LLVM toolchain",
        hw_tests=hw_test_list.ToolchainTestMedium(
            constants.HWTEST_QUOTA_POOL,
            quota_account=constants.HWTEST_QUOTA_ACCOUNT_TOOLCHAIN,
        ),
        hw_tests_override=hw_test_list.ToolchainTestMedium(
            constants.HWTEST_QUOTA_POOL,
            quota_account=constants.HWTEST_QUOTA_ACCOUNT_TOOLCHAIN,
        ),
    )
    site_config.AddTemplate(
        "llvm_next_toolchain",
        site_config.templates.llvm_toolchain,
        description="Full release build with LLVM (next) toolchain",
        useflags=config_lib.append_useflags(["llvm-next"]),
    )
    site_config.AddTemplate(
        "llvm_tot_toolchain",
        site_config.templates.llvm_toolchain,
        useflags=config_lib.append_useflags(["llvm-tot"]),
        description="Full release builds with a near-top-of-tree LLVM. Since "
        "this uses internal sources, it should only be used with LLVM "
        "revisions that have been reviewed manually somehow",
    )

    #
    # Create toolchain tryjob builders.
    #
    builder_to_boards_dict = config_lib.GroupBoardsByBuilder(
        ge_build_config[config_lib.CONFIG_TEMPLATE_BOARDS]
    )

    toolchain_tryjob_boards = (
        builder_to_boards_dict[config_lib.CONFIG_TEMPLATE_RELEASE]
        | boards_dict["all_boards"]
    )

    site_config.AddForBoards(
        "llvm-toolchain",
        toolchain_tryjob_boards,
        board_configs,
        site_config.templates.llvm_toolchain,
    )
    site_config.AddForBoards(
        "llvm-next-toolchain",
        toolchain_tryjob_boards,
        board_configs,
        site_config.templates.llvm_next_toolchain,
    )

    # All *-generic boards are external.
    site_config.Add(
        "eve-llvm-tot-toolchain",
        site_config.templates.llvm_tot_toolchain,
        vm_tests=[],
        vm_tests_override=TRADITIONAL_VM_TESTS_SUPPORTED,
        boards=["eve"],
    )
    site_config.Add(
        "kevin-llvm-tot-toolchain",
        site_config.templates.llvm_tot_toolchain,
        site_config.templates.no_vmtest_builder,
        boards=["kevin"],
    )


def FullBuilders(site_config, boards_dict, ge_build_config):
    """Create all full builders.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
      boards_dict: A dict mapping board types to board name collections.
      ge_build_config: Dictionary containing the decoded GE configuration file.
    """
    active_builders = _frozen_ge_set(
        ge_build_config,
        [
            "eve",
            "hana",
            "jacuzzi",
            "kevin",
            "kevin64",
            "octopus",
            "tael",
            "tatl",
            "zork",
        ],
        ("amd64-generic", "arm-generic", "arm64-generic"),
    )

    # Move the following builders to active_builders once they are consistently
    # green.
    unstable_builders = _frozen_ge_set(ge_build_config, [])

    external_board_configs = CreateBoardConfigs(
        site_config, boards_dict, ge_build_config
    )

    site_config.AddForBoards(
        config_lib.CONFIG_TYPE_FULL,
        boards_dict["all_full_boards"],
        external_board_configs,
        site_config.templates.full,
        site_config.templates.build_external_chrome,
        run_cpeexport=True,
        internal=False,
        manifest_repo_url=config_lib.GetSiteParams().MANIFEST_URL,
        overlays=constants.PUBLIC_OVERLAYS,
        prebuilts=constants.PUBLIC,
    )

    master_config = site_config.Add(
        "master-full",
        site_config.templates.full,
        site_config.templates.internal,
        site_config.templates.build_external_chrome,
        boards=[],
        master=True,
        manifest_version=True,
        overlays=constants.PUBLIC_OVERLAYS,
        slave_configs=[],
        schedule=None,
    )

    master_config.AddSlaves(
        site_config.ApplyForBoards(
            config_lib.CONFIG_TYPE_FULL,
            active_builders,
            manifest_version=True,
        )
    )

    master_config.AddSlaves(
        site_config.ApplyForBoards(
            config_lib.CONFIG_TYPE_FULL,
            unstable_builders,
            manifest_version=True,
            important=False,
        )
    )

    vm_config = site_config.Add(
        "amd64-generic-vm-full",
        site_config.templates.vm,
        site_config.templates.build_external_chrome,
        boards=["amd64-generic"],
        description="Build for running on VMs",
        run_cpeexport=True,
        internal=False,
        manifest_version=True,
        manifest_repo_url=config_lib.GetSiteParams().MANIFEST_URL,
        overlays=constants.PUBLIC_OVERLAYS,
        prebuilts=constants.PUBLIC,
    )

    master_config.AddSlave(vm_config)


def InformationalBuilders(site_config, boards_dict, ge_build_config):
    """Create all informational builders.

    We have a number of informational builders that are built, but whose output
    is not directly used for anything other than reporting success or failure.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
      boards_dict: A dict mapping board types to board name collections.
      ge_build_config: Dictionary containing the decoded GE configuration file.
    """
    internal_board_configs = CreateInternalBoardConfigs(
        site_config, boards_dict, ge_build_config
    )

    _chrome_boards = frozenset(
        board
        for board, config in internal_board_configs.items()
        if config.get("sync_chrome", True)
    )

    site_config.Add(
        "amd64-generic-asan",
        site_config.templates.asan,
        site_config.templates.incremental,
        site_config.templates.no_hwtest_builder,
        site_config.templates.build_external_chrome,
        site_config.templates.informational,
        boards=["amd64-generic"],
        description="Build with Address Sanitizer (Clang)",
        board_replace=True,
    )

    site_config.Add(
        "betty-asan",
        site_config.templates.asan,
        site_config.templates.incremental,
        site_config.templates.no_hwtest_builder,
        site_config.templates.internal,
        site_config.templates.informational,
        boards=["betty"],
        description="Build with Address Sanitizer (Clang)",
        # Once every day. 3 PM UTC is 7 AM PST (no daylight savings).
        # Currently disabled, to schedule uncomment the next line.
        # schedule='0 15 * * *',
        board_replace=True,
        vm_tests=[],
    )

    site_config.Add(
        "amd64-generic-fuzzer",
        site_config.templates.fuzzer,
        boards=["amd64-generic"],
        description="Build for fuzzing testing",
        # THESE IMAGES CAN DAMAGE THE LAB and cannot be used for hardware
        # testing.
        disk_layout="4gb-rootfs",
        image_test=None,
        board_replace=True,
    )

    site_config.Add(
        "amd64-generic-coverage-fuzzer",
        site_config.templates.fuzzer,
        boards=["amd64-generic"],
        profile="coverage-fuzzer",
        description="Build for fuzzing coverage testing",
        gs_path="gs://chromeos-fuzzing-artifacts/libfuzzer-coverage-buganizer",
        disk_layout="4gb-rootfs",
        image_test=None,
        board_replace=True,
    )

    site_config.Add(
        "amd64-generic-msan-fuzzer",
        site_config.templates.fuzzer,
        boards=["amd64-generic"],
        profile="msan-fuzzer",
        description="Build for msan fuzzing testing",
        gs_path="gs://chromeos-fuzzing-artifacts/libfuzzer-msan-buganizer",
        disk_layout="4gb-rootfs",
        image_test=None,
        board_replace=True,
    )

    site_config.Add(
        "amd64-generic-ubsan",
        site_config.templates.ubsan,
        site_config.templates.incremental,
        site_config.templates.no_hwtest_builder,
        site_config.templates.informational,
        boards=["amd64-generic"],
        description="Build with Undefined Behavior Sanitizer (Clang)",
        # THESE IMAGES CAN DAMAGE THE LAB and cannot be used for hardware
        # testing.
        disk_layout="16gb-rootfs",
        board_replace=True,
        vm_tests=[],
    )

    site_config.Add(
        "amd64-generic-ubsan-fuzzer",
        site_config.templates.fuzzer,
        boards=["amd64-generic"],
        profile="ubsan-fuzzer",
        description="Build for fuzzing testing",
        gs_path="gs://chromeos-fuzzing-artifacts/libfuzzer-ubsan-buganizer",
        disk_layout="4gb-rootfs",
        image_test=None,
        board_replace=True,
    )

    site_config.Add(
        "amd64-generic-fwupd-upstream",
        site_config.templates.full,
        site_config.templates.informational,
        boards=["amd64-generic"],
        profile="fwupd-upstream",
        chrome_sdk=False,
        description="Build with Upstream fwupd",
        disk_layout="4gb-rootfs",
        board_replace=True,
        images=["base", "test"],
        vm_tests=[],
        tast_vm_tests=[
            config_lib.TastVMTestConfig(
                "tast_vm_fwupd",
                ['("group:mainline" && !informational && "dep:fwupd")'],
            )
        ],
    )


def FactoryBuilders(site_config, _boards_dict, _ge_build_config):
    """Create all factory build configs.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
      boards_dict: A dict mapping board types to board name collections.
      ge_build_config: Dictionary containing the decoded GE configuration file.
    """
    # pylint: disable=unused-variable
    # Intervals:
    # None: Do not schedule automatically.
    DAILY = "with 24h interval"  # 1 day interval
    WEEKLY = "with 168h interval"  # 1 week interval
    MONTHLY = "with 720h interval"  # 30 day interval
    TRIGGERED = "triggered"  # Only when triggered
    branch_builders = [
        (MONTHLY, "factory-glados-7657.B", ["glados", "chell"]),
        (
            MONTHLY,
            "factory-glados-7828.B",
            ["glados", "chell", "lars", "sentry", "cave", "asuka", "caroline"],
        ),
        (MONTHLY, "factory-oak-8182.B", ["elm", "hana"]),
        (MONTHLY, "factory-gru-8652.B", ["kevin"]),
        (MONTHLY, "factory-gale-8743.19.B", ["gale"]),
        (MONTHLY, "factory-reef-8811.B", ["reef", "pyro", "sand", "snappy"]),
        (MONTHLY, "factory-gru-9017.B", ["gru", "bob"]),
        (MONTHLY, "factory-eve-9667.B", ["eve"]),
        (MONTHLY, "factory-coral-10122.B", ["coral"]),
        (MONTHLY, "factory-fizz-10167.B", ["fizz"]),
        (MONTHLY, "factory-scarlet-10211.B", ["scarlet"]),
        (MONTHLY, "factory-soraka-10323.39.B", ["soraka"]),
        (MONTHLY, "factory-poppy-10504.B", ["nautilus"]),
        (MONTHLY, "factory-nami-10715.B", ["nami", "kalista"]),
        (MONTHLY, "factory-nocturne-11066.B", ["nocturne"]),
        (MONTHLY, "factory-grunt-11164.B", ["grunt"]),
        (MONTHLY, "factory-grunt-11164.135.B", ["grunt"]),
        (MONTHLY, "factory-rammus-11289.B", ["rammus"]),
        (WEEKLY, "factory-octopus-11512.B", ["octopus"]),
        (WEEKLY, "factory-atlas-11907.B", ["atlas"]),
        (WEEKLY, "factory-sarien-12033.B", ["sarien"]),
        (WEEKLY, "factory-mistral-12361.B", ["mistral"]),
        (WEEKLY, "factory-kukui-12587.B", ["kukui", "jacuzzi"]),
        (WEEKLY, "factory-hatch-12692.B", ["hatch"]),
        (WEEKLY, "factory-excelsior-12812.B", ["excelsior"]),
        (WEEKLY, "factory-drallion-13080.B", ["drallion"]),
        (MONTHLY, "factory-endeavour-13295.B", ["endeavour"]),
        (WEEKLY, "factory-puff-13329.B", ["puff", "puff-moblab"]),
        (WEEKLY, "factory-zork-13427.B", ["zork"]),
        (WEEKLY, "factory-trogdor-13443.B", ["trogdor", "strongbad"]),
        (DAILY, "factory-trogdor-15210.B", ["trogdor", "strongbad"]),
        (DAILY, "factory-strongbad-13963.B", ["trogdor", "strongbad"]),
        (WEEKLY, "factory-volteer-13600.B", ["volteer"]),
        (WEEKLY, "factory-dedede-13683.B", ["dedede"]),
        (TRIGGERED, "factory-keeby-14162.B", ["keeby"]),
        (WEEKLY, "factory-zork-13700.B", ["zork"]),
        (WEEKLY, "factory-puff-13813.B", ["puff"]),
        (WEEKLY, "factory-asurada-13929.B", ["asurada"]),
        (WEEKLY, "factory-ambassador-14265.B", ["ambassador"]),
        (DAILY, "factory-kukui-14374.B", ["kukui", "jacuzzi"]),
        (WEEKLY, "factory-cherry-14455.B", ["cherry"]),
        (DAILY, "factory-brya-14517.B", ["brya", "brask"]),
        (WEEKLY, "factory-guybrush-14908.B", ["guybrush"]),
        (WEEKLY, "factory-brya-14909.124.B", ["brya"]),
        (WEEKLY, "factory-corsola-15196.B", ["corsola"]),
        (DAILY, "factory-nissa-15199.B", ["nissa"]),
        (DAILY, "factory-brya-15231.B", ["brya", "brask"]),
        (DAILY, "factory-skyrim-15384.B", ["skyrim"]),
        # This is intended to create master branch tryjobs, NOT for production
        # builds. Update the associated list of boards as needed.
        (
            None,
            "master",
            [
                "atlas",
                "octopus",
                "rammus",
                "coral",
                "eve",
                "sarien",
                "mistral",
                "drallion",
            ],
        ),
    ]

    _FACTORYBRANCH_TIMEOUT = 12 * 60 * 60

    # Requires that you set boards, and workspace_branch.
    site_config.AddTemplate(
        "factorybranch",
        site_config.templates.factory,
        site_config.templates.workspace,
        sign_types=["factory"],
        build_type=constants.GENERIC_TYPE,
        uprev=True,
        overlays=constants.BOTH_OVERLAYS,
        push_overlays=constants.BOTH_OVERLAYS,
        useflags=config_lib.append_useflags(
            ["-cros-debug", "thinlto", "chrome_internal"]
        ),
        builder_class_name="workspace_builders.FactoryBranchBuilder",
        build_timeout=_FACTORYBRANCH_TIMEOUT,
        description="TOT builder to build a factory branch.",
        doc="https://goto.google.com/tot-for-firmware-branches",
    )

    site_config.AddTemplate(
        "old_factorybranch_packages",
        packages=[
            "virtual/target-os",
            "virtual/target-os-dev",
            "virtual/target-os-test",
            "chromeos-base/chromeos-installshim",
            "chromeos-base/chromeos-factory",
            "chromeos-base/chromeos-hwid",
            "chromeos-base/autotest-factory-install",
            "chromeos-base/autotest-all",
        ],
    )

    # These branches require a differnt list of packages to build.
    old_package_branches = {
        "factory-glados-7657.B",
        "factory-glados-7828.B",
    }

    for active, branch, boards in branch_builders:
        schedule = {}
        if active:
            schedule = {
                "schedule": active,
            }

        # Define the buildspec builder for the branch.
        branch_master = site_config.Add(
            "%s-buildspec" % branch,
            site_config.templates.buildspec,
            display_label=config_lib.DISPLAY_LABEL_FACTORY,
            workspace_branch=branch,
            build_timeout=_FACTORYBRANCH_TIMEOUT,
            **schedule,
        )

        # Define the per-board builders for the branch.
        for board in boards:
            child = site_config.Add(
                "%s-%s-factorybranch" % (board, branch),
                site_config.templates.factorybranch,
                boards=[board],
                workspace_branch=branch,
            )
            if branch in old_package_branches:
                child.apply(site_config.templates.old_factorybranch_packages)
            branch_master.AddSlave(child)


def ReleaseBuilders(site_config, boards_dict, ge_build_config):
    """Create all release builders.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
      boards_dict: A dict mapping board types to board name collections.
      ge_build_config: Dictionary containing the decoded GE configuration file.
    """
    board_configs = CreateInternalBoardConfigs(
        site_config, boards_dict, ge_build_config
    )

    unified_builds = config_lib.GetUnifiedBuildConfigAllBuilds(ge_build_config)
    unified_board_names = set(
        [
            b[config_lib.CONFIG_TEMPLATE_REFERENCE_BOARD_NAME]
            for b in unified_builds
        ]
    )

    def _CreateMasterConfig(
        name, template=site_config.templates.release, schedule="  0 12 * * *"
    ):
        return site_config.Add(
            name,
            template,
            boards=[],
            master=True,
            slave_configs=[],
            sync_chrome=True,
            chrome_sdk=False,
            # Because PST is 8 hours from UTC, these times are the same in both.
            # But daylight savings time is NOT adjusted for
            schedule=schedule,
        )

    ### Master release configs.
    master_config = _CreateMasterConfig("master-release")
    # pylint: disable=unused-variable
    basic_master_config = _CreateMasterConfig(
        "master-release-basic",
        template=site_config.templates.release_basic,
        schedule="30 */2 * * * *",
    )

    def _AssignToMaster(config):
        """Add |config| as a slave config to the appropriate master config."""
        # Default to chromeos master release builder.
        master = master_config

        # Add this config to the master release basic builder.
        if config.name.endswith("-release-basic"):
            master = basic_master_config

        master.AddSlave(config)

    ### Release configs.

    # Used for future bvt migration.
    _release_experimental_boards = _frozen_ge_set(
        ge_build_config,
        [
            "betty-kernelnext",
            "elm-kernelnext",
            "grunt-kernelnext",
            "hana-kernelnext",
            "hatch-kernelnext",
            "volteer-kernelnext",
            "zork-kernelnext",
        ],
    )

    _release_enable_skylab_hwtest = _frozen_ge_set(
        ge_build_config,
        [
            "asuka",
            "coral",
            "nyan_blaze",
            "reef",
        ],
    )

    _release_enable_skylab_partial_boards = {
        "coral": ["astronaut", "nasher", "lava"],
    }

    _release_enable_skylab_cts_hwtest = _frozen_ge_set(
        ge_build_config,
        [
            "terra",
        ],
    )

    _no_unittest_configs = [
        "grunt-kernelnext-release",
        "guybrush-kernelnext-release",
        "zork-connectivitynext-release",
        "zork-minios-release",
    ]

    def _get_skylab_settings(board_name):
        """Get skylab settings for release builder.

        Args:
          board_name: A string board name.

        Returns:
            A dict mapping suite types to booleans indicating whether this suite
            on this board is to be run on Skylab. Current suite types:
                - cts: all suites using pool:cts,
                - default: the rest of the suites.
        """
        return {
            "cts": board_name in _release_enable_skylab_cts_hwtest,
            "default": board_name in _release_enable_skylab_hwtest,
        }

    builder_to_boards_dict = config_lib.GroupBoardsByBuilder(
        ge_build_config[config_lib.CONFIG_TEMPLATE_BOARDS]
    )

    _all_release_builder_boards = builder_to_boards_dict[
        config_lib.CONFIG_TEMPLATE_RELEASE
    ]

    site_config.AddForBoards(
        config_lib.CONFIG_TYPE_RELEASE,
        (
            (boards_dict["all_release_boards"] | _all_release_builder_boards)
            - unified_board_names
        ),
        board_configs,
        site_config.templates.release,
    )

    hw_test_list = HWTestList(ge_build_config)

    for unibuild in config_lib.GetUnifiedBuildConfigAllBuilds(ge_build_config):
        models = []
        for model in unibuild[config_lib.CONFIG_TEMPLATE_MODELS]:
            name = model[config_lib.CONFIG_TEMPLATE_MODEL_NAME]
            lab_board_name = config_lib.GetNonUniBuildLabBoardName(
                model[config_lib.CONFIG_TEMPLATE_MODEL_BOARD_NAME]
            )
            enable_skylab = True
            if (
                lab_board_name in _release_enable_skylab_hwtest
                and lab_board_name in _release_enable_skylab_partial_boards
                and name
                not in _release_enable_skylab_partial_boards[lab_board_name]
            ):
                enable_skylab = False

            if config_lib.CONFIG_TEMPLATE_MODEL_TEST_SUITES in model:
                test_suites = model[
                    config_lib.CONFIG_TEMPLATE_MODEL_TEST_SUITES
                ]
                models.append(
                    config_lib.ModelTestConfig(
                        name,
                        lab_board_name,
                        test_suites,
                        enable_skylab=enable_skylab,
                    )
                )
            else:
                no_model_test_suites = []
                models.append(
                    config_lib.ModelTestConfig(
                        name,
                        lab_board_name,
                        no_model_test_suites,
                        enable_skylab=enable_skylab,
                    )
                )

        reference_board_name = unibuild[
            config_lib.CONFIG_TEMPLATE_REFERENCE_BOARD_NAME
        ]

        config_name = "%s-release" % reference_board_name

        # Move unibuild to skylab.
        important = not unibuild[config_lib.CONFIG_TEMPLATE_EXPERIMENTAL]
        if reference_board_name in _release_experimental_boards:
            important = False

        enable_skylab_hw_tests = _get_skylab_settings(reference_board_name)
        props = {
            "models": models,
            "important": important,
            "enable_skylab_hw_tests": enable_skylab_hw_tests["default"],
            "hw_tests": hw_test_list.SharedPoolCanary(),
        }
        if config_name in _no_unittest_configs:
            props["unittests"] = False
        site_config.AddForBoards(
            config_lib.CONFIG_TYPE_RELEASE,
            [reference_board_name],
            board_configs,
            site_config.templates.release,
            **props,
        )
        _AssignToMaster(site_config[config_name])

    def GetReleaseConfigName(board):
        """Convert a board name into a release config name."""
        return "%s-release" % board

    def GetConfigName(builder, board):
        """Convert a board name into a config name."""
        if builder == config_lib.CONFIG_TEMPLATE_RELEASE:
            return GetReleaseConfigName(board)
        else:
            # Currently just support RELEASE builders
            raise Exception("Do not support other builders.")

    def _GetConfigValues(board):
        """Get and return config values from template and user definitions."""
        important = not board[config_lib.CONFIG_TEMPLATE_EXPERIMENTAL]
        if board["name"] in _release_experimental_boards:
            important = False

        enable_skylab_hw_tests = _get_skylab_settings(board["name"])

        # Move non-unibuild to skylab.
        config_values = {
            "important": important,
            "enable_skylab_hw_tests": enable_skylab_hw_tests["default"],
            "enable_skylab_cts_hw_tests": enable_skylab_hw_tests["cts"],
        }

        return config_values

    def _AdjustUngroupedReleaseConfigs(builder_ungrouped_dict):
        """Adjust for ungrouped release boards"""
        for builder in builder_ungrouped_dict:
            for board in builder_ungrouped_dict[builder]:
                config_name = GetConfigName(
                    builder, board[config_lib.CONFIG_TEMPLATE_NAME]
                )
                site_config[config_name].apply(
                    _GetConfigValues(board),
                )
                _AssignToMaster(site_config[config_name])

    def _AdjustGroupedReleaseConfigs(builder_group_dict):
        """Adjust leader and follower configs for grouped boards"""
        for builder in builder_group_dict:
            for group in builder_group_dict[builder]:
                board_group = builder_group_dict[builder][group]

                # Leaders are built on baremetal builders and run all tests
                # needed by the related boards.
                for board in board_group.leader_boards:
                    config_name = GetConfigName(
                        builder, board[config_lib.CONFIG_TEMPLATE_NAME]
                    )
                    site_config[config_name].apply(
                        _GetConfigValues(board),
                    )
                    _AssignToMaster(site_config[config_name])

                # Followers are built on GCE instances, and turn off testing
                # that breaks on GCE. The missing tests run on the leader board.
                for board in board_group.follower_boards:
                    config_name = GetConfigName(
                        builder, board[config_lib.CONFIG_TEMPLATE_NAME]
                    )
                    site_config[config_name].apply(
                        _GetConfigValues(board),
                        chrome_sdk_build_chrome=False,
                        vm_tests=[],
                    )
                    _AssignToMaster(site_config[config_name])

    def _AdjustReleaseConfigs():
        """Adjust ungrouped and grouped release configs"""
        (
            builder_group_dict,
            builder_ungrouped_dict,
        ) = config_lib.GroupBoardsByBuilderAndBoardGroup(
            ge_build_config[config_lib.CONFIG_TEMPLATE_BOARDS]
        )
        _AdjustUngroupedReleaseConfigs(builder_ungrouped_dict)
        _AdjustGroupedReleaseConfigs(builder_group_dict)

        for board in chromeos_boards.moblab_boards:
            config_name = GetReleaseConfigName(board)
            if config_name not in site_config:
                continue
            # If the board is in moblab_boards, use moblab_release template
            site_config[config_name].apply(
                site_config.templates.moblab_release,
                board_configs[board],
            )

    def AddReleaseBasicMirrors():
        """Create basic release builder variants for relevant build configs."""
        release_basic_boards = ["eve", "atlas", "grunt"]
        for board in release_basic_boards:
            config_name = "%s-release-basic" % board
            site_config.Add(
                config_name,
                site_config.templates.release_basic,
                site_config[board + "-release"],
            )
            site_config[config_name].apply(site_config.templates.release_basic)
            _AssignToMaster(site_config[config_name])

    _AdjustReleaseConfigs()
    AddReleaseBasicMirrors()


def PayloadBuilders(site_config, boards_dict):
    """Create <board>-payloads configs for all payload generating boards.

    We create a config named 'board-payloads' for every board which has a
    config with 'paygen' True. The idea is that we have a build that generates
    payloads, we need to have a tryjob to re-attempt them on failure.
    """
    for board in boards_dict["all_release_boards"]:
        if site_config["%s-release" % board].paygen:
            site_config.Add(
                "%s-payloads" % board,
                site_config.templates.payloads,
                boards=[board],
            )


def AddNotificationConfigs(site_config):
    """Add NotificationConfigs to specific builders.

    Set the notification_config property of specific builders enabling
    notifications through luci-notify.

    notification_config values should only be set through this method as it will
    overwrite notification_config values set elsewhere.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding
                    NotificationConfigs.
    """

    # Notifiers is a map of builder config names to a list of NotificationConfig
    # objects. Example:
    # notifiers = {
    #     'sample-release': [
    #         config_lib.NotificationConfig(email='test1@google.com'),
    #         config_lib.NotificationConfig(email='test2@google.com')
    #     ],
    #     'test-release': [
    #         config_lib.NotificationConfig(email='test1@chromium.org')
    #     ],
    # }
    notifiers = {
        "amd64-generic-fwupd-upstream": [
            config_lib.NotificationConfig(
                email="chromeos-fwupd@google.com",
                template="legacy_informational",
            ),
        ],
        "dedede-release": [
            config_lib.NotificationConfig(
                email="dedede-release-builder-alerts@google.com", threshold=2
            ),
        ],
        "hatch-borealis-release": [
            config_lib.NotificationConfig(
                email="borealis-release-builder-alerts@google.com", threshold=2
            ),
        ],
        "puff-borealis-release": [
            config_lib.NotificationConfig(
                email="borealis-release-builder-alerts@google.com", threshold=2
            ),
        ],
        "swanky-release": [
            config_lib.NotificationConfig(email="navil+spam@chromium.org"),
        ],
        "volteer-borealis-release": [
            config_lib.NotificationConfig(
                email="borealis-release-builder-alerts@google.com", threshold=2
            ),
        ],
        "zork-borealis-release": [
            config_lib.NotificationConfig(
                email="borealis-release-builder-alerts@google.com", threshold=2
            ),
        ],
        "tatl-release": [
            config_lib.NotificationConfig(
                email="clumptini+release-builder-alerts@google.com"
            ),
        ],
        "tael-release": [
            config_lib.NotificationConfig(
                email="clumptini+release-builder-alerts@google.com"
            ),
        ],
    }

    for config_name, notification_configs in notifiers.items():
        if config_name in site_config:
            site_config[config_name].apply(
                **{"notification_configs": notification_configs}
            )
        else:
            logging.warning(
                "ignoring notifier for missing config %s", config_name
            )


def ApplyCustomOverrides(site_config):
    """Method with to override specific flags for specific builders.

    Generally try really hard to avoid putting anything here that isn't
    a really special case for a single specific builder. This is performed
    after every other bit of processing, so it always has the final say.

    Args:
      site_config: config_lib.SiteConfig containing builds to have their
                   waterfall values updated.
    """

    overwritten_configs = {
        "amd64-generic-cheets-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1000717",
        },
        # The board does not exist in the lab. See crbug.com/1003981
        "beaglebone_servo-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1003981",
        },
        # No hw tests for beaglebone, expresso (crbug.com/1011171).
        "beaglebone-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1011171",
        },
        "expresso-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1011171",
        },
        # Currently betty-arc-r is VM only.
        "betty-arc-r-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/998427",
            "vm_tests": [],
            "vm_tests_override": [],
        },
        "betty-arc-t-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/998427",
            "vm_tests": [],
            "vm_tests_override": [],
        },
        "betty-arc-u-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/998427",
            "vm_tests": [],
            "vm_tests_override": [],
        },
        # No hw tests for any betty builders.  See crbug/998427.
        "betty-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/998427",
        },
        "betty-pi-arc-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1026430",
        },
        # No hw_tests for caroline-ndktranslation.  See crbug.com/1091053.
        "caroline-ndktranslation-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "http://crbug.com/1091053",
        },
        # No hw_tests for eve-arc-r.  See crbug.com/1161335
        "eve-arc-r-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "http://crbug.com/1161335",
        },
        # No hw_tests for eve-kvm.  See crbug.com/1085769.
        "eve-kvm-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "http://crbug.com/1085769",
        },
        # No hw_tests for eve-userdebug.  See crbug.com/1085769.
        "eve-userdebug-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "http://crbug.com/1085769",
        },
        "heli-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "http://b/148950027",
        },
        "novato-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1000717",
        },
        "novato-arc64-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1000717",
        },
        "setzer-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1092947",
        },
        # No hw_tests for arkham, whirlwind, gale, mistral.  See b/140317527.
        "arkham-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://b/140317527",
        },
        "whirlwind-release": {
            "dev_installer_prebuilts": True,
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://b/140317527",
            "paygen_skip_testing": True,
        },
        "gale-release": {
            "dev_installer_prebuilts": True,
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://b/140317527",
            "paygen_skip_testing": True,
        },
        "mistral-release": {
            "dev_installer_prebuilts": True,
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://b/140317527",
            "paygen_skip_testing": True,
        },
        # TODO(yshaul): find out if hwqual needs to go as well
        # TODO(yshaul): fix apply method to merge base and test
        "guado_labstation-release": {
            "hwqual": False,
            "images": ["base", "test"],
            "paygen": False,
        },
        "fizz-labstation-release": {
            "hwqual": False,
            "images": ["base", "test"],
            "paygen": False,
        },
        # Run TestSimpleChromeWorkflow only on kevin64-release instead of
        # arm64-generic/kevin64-full.
        "arm64-generic-full": {
            "chrome_sdk_build_chrome": False,
        },
        "kevin64-full": {
            "chrome_sdk_build_chrome": False,
        },
        "kevin64-release": {
            "chrome_sdk_build_chrome": True,
        },
        # Currently factory branches will be created after DVT stage. Therefore
        # we need signed factory shim or accessory_rwsig firmware from ToT
        # temporarily.
        #
        # After factory branches are created, the configuration of this project
        # should be removed.
        # --- start from here ---
        "dedede-release": {
            "sign_types": ["recovery", "factory"],
        },
        # See go/cros-fingerprint-firmware-branching-and-signing for details on
        # accessory_rwsig signing.
        "hatch-release": {
            "sign_types": ["recovery", "factory", "accessory_rwsig"],
        },
        # Mushu does not have DUTs in lab See http://b/147462165
        "mushu-release": {
            "sign_types": ["recovery", "factory"],
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://b/147462165",
        },
        "jacuzzi-release": {
            "sign_types": ["recovery", "factory"],
        },
        "puff-release": {
            "sign_types": ["recovery", "factory"],
        },
        "kukui-release": {
            "sign_types": ["recovery", "factory"],
        },
        "sarien-release": {
            "sign_types": ["recovery", "factory"],
        },
        "strongbad-release": {
            "sign_types": ["recovery", "factory"],
        },
        "trogdor-release": {
            "sign_types": ["recovery", "factory"],
        },
        "trogdor64-release": {
            "sign_types": ["recovery", "factory"],
        },
        "shadowkeep-release": {
            "sign_types": ["recovery", "factory"],
            # Shadowkeep has no DUTs in the lab (b/159934902).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/159934902",
        },
        "draco-release": {
            "sign_types": ["recovery", "factory"],
            # Draco has no DUTs in the lab (b/204940128).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/204940128",
        },
        "brask-release": {
            "sign_types": ["recovery", "factory"],
            # Brask has no DUTs in the lab (b/207095933).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/207095933",
        },
        "brya-release": {
            "sign_types": ["recovery", "factory", "hps_firmware"],
        },
        "brya-lvm-stateful-release": {
            "sign_types": ["recovery", "factory"],
        },
        "keeby-release": {
            "sign_types": ["recovery", "factory"],
        },
        "aurora-release": {
            "sign_types": ["recovery", "factory"],
            # Aurora has no DUTs in the lab. (b/186859558)
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/186859558",
        },
        "volteer-release": {
            "sign_types": ["recovery", "factory"],
        },
        "ghost-release": {
            "sign_types": ["recovery", "factory"],
            # Ghost has no DUTs in the lab (b/237833835).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/237833835",
        },
        # See go/cros-fingerprint-firmware-branching-and-signing for details on
        # accessory_rwsig signing.
        "zork-release": {
            "sign_types": ["recovery", "factory", "accessory_rwsig"],
        },
        "guybrush-release": {
            "sign_types": ["recovery", "factory"],
        },
        "drallion-release": {
            "sign_types": ["recovery", "factory"],
        },
        # reven board does not exist in the lab.
        "reven-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1066311",
            "images": add_images(["base"]),
            "base_is_recovery": True,
        },
        "reven-vmtest-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1232182",
            "images": ["test"],
            "paygen": False,
            # This requires a base image.
            "image_test": False,
            # This requires a recovery image.
            "signer_tests": False,
        },
        # puff-moblab board does not exist in the lab.
        "puff-moblab-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1145306",
        },
        # fizz-moblab board fails are not being monitored.
        "fizz-moblab-release": {
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "https://crbug.com/1145306",
        },
        "cherry-release": {
            "sign_types": ["recovery", "factory"],
        },
        "cherry64-release": {
            "sign_types": ["recovery"],
        },
        "nissa-release": {
            "sign_types": ["recovery", "factory"],
        },
        "corsola-release": {
            "sign_types": ["recovery", "factory"],
        },
        "geralt-release": {
            "sign_types": ["recovery", "factory"],
            # Geralt has no DUTs in the lab (b/239660108).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/239660108",
        },
        "skyrim-release": {
            "sign_types": ["recovery", "factory"],
            # Skyrim has no DUTs in the lab (b/240824186).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/240824186",
        },
        "rex-release": {
            "sign_types": ["recovery", "factory"],
            # Rex has no DUTs in the lab (b/243985220).
            "hw_tests": [],
            "hw_tests_override": [],
            "hw_tests_disabled_bug": "b/243985220",
        },
        # --- end from here ---
        # Enable distributed ThinLTO (crbug/877722) only on nocturne for now.
        "nocturne-release": {
            "useflags": config_lib.append_useflags(["goma_thinlto"]),
        },
    }

    # Some Unibuild boards need to have hardware tests disabled.  This means
    # disabling it at the model level as well.
    _unibuild_disabled_hw_tests = frozenset(
        [
            "eve-arc-r-release",  # crbug.com/1161335
        ]
    )

    for config_name in _unibuild_disabled_hw_tests:
        config = site_config.get(config_name)
        if config and "models" in config:
            models = []
            for model in config["models"]:
                models.append(
                    config_lib.ModelTestConfig(
                        model.name,
                        model.lab_board_name,
                        [],
                        enable_skylab=model.enable_skylab,
                    )
                )
            if config_name not in overwritten_configs:
                overwritten_configs[config_name] = {}
            overwritten_configs[config_name]["models"] = models

    # Some devices has limited DUT in the lab and running bvt-tast-informational
    # may miss tests results due to timeout.
    # TODO(ddmail): Enable it once we have enough DUT in the lab.
    _disable_bvt_tast_informational = [
        "hatch-borealis-release",
        "puff-borealis-release",
        "volteer-borealis-release",
        "zork-borealis-release",
    ]
    for config_name in _disable_bvt_tast_informational:
        config = overwritten_configs.get(config_name)
        if not config:
            config = site_config.get(config_name)
        if not config or "hw_tests" not in config:
            continue

        hw_tests = [
            test
            for test in config["hw_tests"]
            if test.suite != "bvt-tast-informational"
        ]
        if config_name not in overwritten_configs:
            overwritten_configs[config_name] = {}
        overwritten_configs[config_name]["hw_tests"] = hw_tests

    # Some boards in toolchain builder are not using the same configuration as
    # release builders. Configure it here since it's easier, for both
    # llvm-toolchain and llvm-next-toolchain builders.
    for board in ["fizz-moblab", "gale", "mistral", "whirlwind"]:
        if board == "fizz-moblab":
            overwritten_configs[board + "-llvm-toolchain"] = {
                "enable_skylab_hw_tests": False,
                "hw_tests": [
                    config_lib.HWTestConfig(constants.HWTEST_MOBLAB_QUICK_SUITE)
                ],
                "hw_tests_override": [
                    config_lib.HWTestConfig(constants.HWTEST_MOBLAB_QUICK_SUITE)
                ],
            }
        else:  # This is the case for gale, mistral and whirlwind
            overwritten_configs[board + "-llvm-toolchain"] = {
                "hw_tests": [
                    config_lib.HWTestConfig(
                        constants.HWTEST_JETSTREAM_COMMIT_SUITE,
                        pool=constants.HWTEST_QUOTA_POOL,
                        quota_account=constants.HWTEST_QUOTA_ACCOUNT_TOOLCHAIN,
                    )
                ],
                "hw_tests_override": [
                    config_lib.HWTestConfig(
                        constants.HWTEST_JETSTREAM_COMMIT_SUITE,
                        pool=constants.HWTEST_QUOTA_POOL,
                        quota_account=constants.HWTEST_QUOTA_ACCOUNT_TOOLCHAIN,
                    )
                ],
            }

        # Use the same configuration for llvm-next
        overwritten_configs[
            board + "-llvm-next-toolchain"
        ] = overwritten_configs[board + "-llvm-toolchain"]

    # Boards to enable GCE image output, to support launching on GCE directly.
    _build_gce_image = frozenset(
        [
            "betty-arc-r-release",
            "betty-arc-t-release",
            "betty-arc-u-release",
        ]
    )

    for config_name in _build_gce_image:
        config = overwritten_configs.get(
            config_name, site_config.get(config_name)
        )
        if not config:
            continue
        config["gce_image"] = True

    for config_name, overrides in overwritten_configs.items():
        # TODO: Turn this assert into a unittest.
        # config = site_config[config_name]
        # for k, v in overrides.items():
        #   assert config[k] != v, ('Unnecessary override: %s: %s' %
        #                           (config_name, k))
        config = site_config.get(config_name)
        if config:
            config.apply(**overrides)


def SpecialtyBuilders(site_config):
    """Add a variety of specialized builders or tryjobs.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
    """
    site_config.AddWithoutTemplate(
        "success-build",
        site_config.templates.external,
        site_config.templates.no_hwtest_builder,
        site_config.templates.no_vmtest_builder,
        boards=[],
        display_label=config_lib.DISPLAY_LABEL_TRYJOB,
        luci_builder=config_lib.LUCI_BUILDER_TRY,
        builder_class_name="test_builders.SucessBuilder",
        description="Builder always passes as quickly as possible.",
    )

    # Used by cbuildbot/stages/sync_stages_unittest
    site_config.AddWithoutTemplate(
        "sync-test-cbuildbot",
        site_config.templates.no_hwtest_builder,
        site_config.templates.no_vmtest_builder,
        boards=[],
        display_label=config_lib.DISPLAY_LABEL_TRYJOB,
        luci_builder=config_lib.LUCI_BUILDER_INFRA,
        builder_class_name="test_builders.SucessBuilder",
        description="Used by sync_stages_unittest.",
    )

    site_config.AddWithoutTemplate(
        "fail-build",
        site_config.templates.external,
        site_config.templates.no_hwtest_builder,
        site_config.templates.no_vmtest_builder,
        boards=[],
        display_label=config_lib.DISPLAY_LABEL_TRYJOB,
        luci_builder=config_lib.LUCI_BUILDER_TRY,
        builder_class_name="test_builders.FailBuilder",
        description="Builder always fails as quickly as possible.",
    )

    site_config.AddWithoutTemplate(
        "chromiumos-sdk",
        site_config.templates.full,
        site_config.templates.no_hwtest_builder,
        # The amd64-host has to be last as that is when the toolchains
        # are bundled up for inclusion in the sdk.
        boards=["arm-generic", "amd64-generic"],
        display_label=config_lib.DISPLAY_LABEL_UTILITY,
        build_type=constants.CHROOT_BUILDER_TYPE,
        builder_class_name="sdk_builders.ChrootSdkBuilder",
        use_sdk=False,
        prebuilts=constants.PUBLIC,
        build_timeout=18 * 60 * 60,
        description="Build the SDK and all the cross-compilers",
        doc="https://dev.chromium.org/chromium-os/build/builder-overview#"
        "TOC-Continuous",
        schedule="with 30m interval",
    )

    site_config.AddWithoutTemplate(
        "chromiumos-sdk-llvm-next",
        site_config.templates.full,
        site_config.templates.no_hwtest_builder,
        boards=["arm-generic", "amd64-generic"],
        display_label=config_lib.DISPLAY_LABEL_UTILITY,
        build_type=constants.CHROOT_BUILDER_TYPE,
        builder_class_name="sdk_builders.ChrootSdkBuilder",
        use_sdk=False,
        useflags=config_lib.append_useflags(["llvm-next"]),
        # Do not store artifacts in gs://chromiumos-sdk.
        debug=True,
        prebuilts=constants.PUBLIC,
        description="Build the SDK with llvm-next",
        # Once every day. 8 AM UTC is 1 AM PST.
        schedule="0 8 * * *",
    )

    site_config.AddWithoutTemplate(
        "config-updater",
        site_config.templates.internal,
        site_config.templates.no_hwtest_builder,
        site_config.templates.no_vmtest_builder,
        site_config.templates.infra_builder,
        display_label=config_lib.DISPLAY_LABEL_UTILITY,
        description=(
            "Build Config Updater reads updated GE config files from"
            " GS, and commits them to chromite after running tests."
        ),
        build_type=constants.GENERIC_TYPE,
        build_timeout=2 * 60 * 60,
        boards=[],
        builder_class_name="config_builders.UpdateConfigBuilder",
        schedule="@hourly",
    )

    site_config.AddWithoutTemplate(
        "luci-scheduler-updater",
        site_config.templates.internal,
        site_config.templates.no_hwtest_builder,
        site_config.templates.no_vmtest_builder,
        site_config.templates.infra_builder,
        display_label=config_lib.DISPLAY_LABEL_UTILITY,
        description=("Deploy changes to luci_scheduler.cfg."),
        build_type=constants.GENERIC_TYPE,
        boards=[],
        builder_class_name="config_builders.LuciSchedulerBuilder",
        schedule="triggered",
        triggered_gitiles=[
            [
                "https://chromium.googlesource.com/chromiumos/chromite",
                ["refs/heads/main"],
                ["config/luci-scheduler.cfg"],
            ],
            [
                "https://chrome-internal.googlesource.com/chromeos/infra/"
                "config",
                ["refs/heads/main"],
                ["generated/luci-scheduler.cfg"],
            ],
        ],
    )

    site_config.AddGroup(
        "test-ap-group",
        site_config.Add(
            "whirlwind-test-ap",
            site_config.templates.test_ap,
            boards=["whirlwind"],
        ),
        site_config.Add(
            "gale-test-ap", site_config.templates.test_ap, boards=["gale"]
        ),
        description="Create images used to power access points in WiFi lab.",
    )

    # *-pre-flight-branch builders are in chromeos_release waterfall.
    # *-no-afdo-uprev builder skips uprevving Chrome AFDO profiles in the PFQ
    # builder, as we have separate builders to do so.
    site_config.Add(
        "chell-chrome-no-afdo-uprev-pre-flight-branch",
        site_config.templates.pre_flight_branch,
        display_label=config_lib.DISPLAY_LABEL_CHROME_PFQ,
        boards=["chell"],
        afdo_use=True,
        afdo_update_kernel_ebuild=True,
        sync_chrome=True,
        chrome_rev=constants.CHROME_REV_STICKY,
        prebuilts=False,
        archive_build_debug=True,
        vm_tests_override=None,
    )

    # Loonix release builders; no signed images nor testing
    # Associated with Rapid releases, triggered from Rapid.
    for board in frozenset.union(
        chromeos_boards.dustbuster_boards, chromeos_boards.wshwos_boards
    ):
        site_config.Add(
            f"{board}-rapid",
            site_config.templates.release,
            site_config.templates.loonix,
            display_label=config_lib.DISPLAY_LABEL_UTILITY,
            luci_builder=config_lib.LUCI_BUILDER_RAPID,
            boards=[board],
            debug=True,
            hwqual=False,
            push_image=False,
            suite_scheduling=False,
            # crbug.com/1111964 - Disable rootfs verification
            rootfs_verification=False,
            description=(
                "Create unsigned release image for ingestion "
                + "into build tool"
            ),
        )


def TryjobMirrors(site_config):
    """Create tryjob specialized variants of every build config.

    This creates a new 'tryjob' config for every existing config, unless the
    existing config is already a tryjob config.

    Args:
      site_config: config_lib.SiteConfig to be modified by adding templates
                   and configs.
    """
    tryjob_configs = {}

    for build_name, config in site_config.items():
        # Don't mirror builds that are already tryjob safe.
        if config_lib.isTryjobConfig(config):
            config.apply(hw_tests_override=None, vm_tests_override=None)
            continue

        tryjob_name = build_name + "-tryjob"

        # Don't overwrite mirrored versions that were explicitly created
        # earlier.
        if tryjob_name in site_config:
            continue

        tryjob_config = copy.deepcopy(config)
        tryjob_config.apply(
            name=tryjob_name,
            display_label=config_lib.DISPLAY_LABEL_TRYJOB,
            luci_builder=config_lib.LUCI_BUILDER_TRY,
            notification_configs=[],
            # Generally make tryjobs safer.
            chroot_replace=True,
            debug=True,
            push_image=False,
            # Force uprev. This is so patched in changes are always built.
            uprev=True,
            gs_path=config_lib.GS_PATH_DEFAULT,
            schedule=None,
            suite_scheduling=False,
            triggered_gitiles=None,
            important=True,
            build_affinity=False,
        )

        # Force uprev. This is so patched in changes are always built.
        if tryjob_config.internal:
            tryjob_config.apply(overlays=constants.BOTH_OVERLAYS)

        # In trybots, we want to always run VM tests and all unit tests, so that
        # developers will get better testing for their changes.
        if tryjob_config.hw_tests_override is not None:
            tryjob_config.apply(
                hw_tests=tryjob_config.hw_tests_override, hw_tests_override=None
            )

        if tryjob_config.vm_tests_override is not None:
            tryjob_config.apply(
                vm_tests=tryjob_config.vm_tests_override, vm_tests_override=None
            )

        if tryjob_config.master:
            tryjob_config.apply(debug_cidb=True)

        if tryjob_config.build_type != constants.PAYLOADS_TYPE:
            tryjob_config.apply(paygen=False)

        if tryjob_config.slave_configs:
            new_children = []
            for c in tryjob_config.slave_configs:
                if not config_lib.isTryjobConfig(site_config[c]):
                    c = "%s-tryjob" % c
                new_children.append(c)

            tryjob_config.apply(slave_configs=new_children)

        # Save off the new config so we can insert into site_config.
        tryjob_configs[tryjob_name] = tryjob_config

    for tryjob_name, tryjob_config in tryjob_configs.items():
        site_config[tryjob_name] = tryjob_config


def BranchScheduleConfig():
    """Create a list of configs to schedule for branch builds.

    This function returns a list of build configs with just enough
    information to correctly schedule builds on branches. This function
    is only used by scripts/gen_luci_scheduler.

    After making changes to this function, they must be deployed to take
    effect. See gen_luci_scheduler --help for details.

    Returns:
      List of config_lib.BuildConfig instances.
    """
    # https://github.com/luci/luci-go/blob/HEAD/scheduler/appengine/messages/config.proto
    #
    # Define each branched schedule with:
    #   branch_name: Name of the branch to build as a string.
    #   config_name: Name of the build config already present on the branch.
    #   label: Display label for UI use. Usually release or factory.
    #   schedule: When to do the build. Can take several formats.
    #     'triggered' for manual builds.
    #     Cron style in UTC timezone: '0 15 * * *'
    #     'with 30d interval' to run X time after previous build.
    #
    # When updating this be sure to run `config/refresh_generated_files`
    # or the change will fail chromite unittests.
    branch_builds = [
        # Add non release branch schedules here, if needed.
        # <branch>, <build_config>, <display_label>, <schedule>, <triggers>,
        # <builder>
    ]

    # The three active release branches.
    # (<branch>, [<android PFQs>], <chrome PFQ>, [<orderfiles>],
    #  [<Chrome AFDOs>])
    # Note: <chrome PFQ> is no longer actually doing anything pre-flight: pupr
    # does that as of 2020-09-15.  It needs to run because it *does* update the
    # CWP profiles.

    # Do not remove BOT-TAG:* comments. They are used to help parse config.
    # BOT-TAG:RELEASES_START
    RELEASES = [
        (
            "release-R107-15117.B",
            [],
            "",
            [],
            [],
            config_lib.LUCI_BUILDER_LEGACY_RELEASE,
        ),
        (
            "release-R106-15054.B",
            [],
            "",
            [],
            [],
            config_lib.LUCI_BUILDER_LEGACY_RELEASE,
        ),
        # LTS branch, please do not delete. Contact: cros-lts-team@google.com.
        # BOT-TAG:NO_PRUNE
        (
            "release-R102-14695.B",
            [],
            "chell-chrome-no-afdo-uprev-pre-flight-branch",
            [],
            [],
            config_lib.LUCI_BUILDER_LTS_RELEASE,
        ),
    ]
    # BOT-TAG:RELEASES_END

    PFQ_SCHEDULE = [
        "0 2,6,10,14,18,22 * * *",
        "0 2,6,10,14,18,22 * * *",
        "0 2,6,10,14,18,22 * * *",
    ]

    ORDERFILE_SCHEDULES = [
        "0 8/12 * * *",
        "0 0/12 * * *",
    ]

    AFDO_SCHEDULES = [
        # Start at a different time than the master AFDO generate, as it might
        # increase lab pressure on chell boards
        "0 8/12 * * *",
        # Start verification builders after 7 hours
        "0 3/12 * * *",
        "0 3/12 * * *",
        "0 3/12 * * *",
    ]

    LTS_SCHEDULE = "19 3 * * 6"

    assert len(RELEASES) == len(PFQ_SCHEDULE)
    for (
        (branch, android_pfq, chrome_pfq, orderfile, afdo, builder),
        android_schedule,
    ) in zip(RELEASES, PFQ_SCHEDULE):
        release_num = re.search(r"release-R(\d+)-.*", branch).group(1)
        # All branches except LTS are only triggered by a Chrome uprev, or
        # manually.
        is_lts = bool(builder == config_lib.LUCI_BUILDER_LTS_RELEASE)
        schedule = LTS_SCHEDULE if is_lts else "triggered"
        branch_builds.append(
            [
                branch,
                "master-release",
                config_lib.DISPLAY_LABEL_RELEASE,
                schedule,
                [
                    [
                        (
                            "https://chromium.googlesource.com/chromiumos/"
                            + "overlays/chromiumos-overlay"
                        ),
                        [r"regexp:refs/heads/%s\\..*" % branch],
                        [
                            (
                                "chromeos-base/chromeos-chrome/"
                                "chromeos-chrome-%s.*.ebuild" % release_num
                            )
                        ],
                    ]
                ],
                builder,
            ]
        )
        branch_builds.extend(
            [
                [
                    branch,
                    pfq,
                    config_lib.DISPLAY_LABEL_RELEASE,
                    android_schedule,
                    None,
                    builder,
                ]
                for pfq in android_pfq
            ]
        )

        if chrome_pfq:
            # We extract the release number from the branch, and use it to
            # watch for new chrome tags to trigger Chrome PFQ builds.
            # release-R71-11151.B -> 71 -> regexp:refs/tags/71\\..*
            # Chrome PFQ is retired as of R88, so chrome_pfq may be empty.
            branch_builds.append(
                [
                    branch,
                    chrome_pfq,
                    config_lib.DISPLAY_LABEL_RELEASE,
                    "triggered",
                    [
                        [
                            "https://chromium.googlesource.com/chromium/src",
                            [r"regexp:refs/tags/%s\\..*" % release_num],
                        ]
                    ],
                    builder,
                ]
            )
        if orderfile:
            assert len(orderfile) == len(ORDERFILE_SCHEDULES)
            for b, s in zip(orderfile, ORDERFILE_SCHEDULES):
                branch_builds.append(
                    [
                        branch,
                        b,
                        config_lib.DISPLAY_LABEL_RELEASE,
                        s,
                        None,
                        builder,
                    ]
                )

        if afdo:
            assert len(afdo) == len(AFDO_SCHEDULES)
            for b, s in zip(afdo, AFDO_SCHEDULES):
                branch_builds.append(
                    [
                        branch,
                        b,
                        config_lib.DISPLAY_LABEL_RELEASE,
                        s,
                        None,
                        builder,
                    ]
                )

    # Convert all branch builds into scheduler config entries.
    default_config = config_lib.GetConfig().GetDefault()

    result = []
    for branch, config_name, label, schedule, trigger, builder in branch_builds:
        result.append(
            default_config.derive(
                name=config_name,
                display_label=label,
                luci_builder=builder,
                schedule_branch=branch,
                schedule=schedule,
                triggered_gitiles=trigger,
            )
        )

    return result


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

    GeneralTemplates(site_config)

    chromeos_test.GeneralTemplates(site_config, ge_build_config)

    ToolchainBuilders(site_config, boards_dict, ge_build_config)

    ReleaseBuilders(site_config, boards_dict, ge_build_config)

    PayloadBuilders(site_config, boards_dict)

    SpecialtyBuilders(site_config)

    InformationalBuilders(site_config, boards_dict, ge_build_config)

    FactoryBuilders(site_config, boards_dict, ge_build_config)

    FullBuilders(site_config, boards_dict, ge_build_config)

    AddNotificationConfigs(site_config)

    ApplyCustomOverrides(site_config)

    chromeos_test.ApplyConfig(site_config, boards_dict, ge_build_config)

    TryjobMirrors(site_config)

    return site_config
