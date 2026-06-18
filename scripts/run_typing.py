# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite type checker.

Run the chromite Python codebase through the mypy type checker.
"""

import dataclasses
import logging
import os
from typing import Iterator, Optional

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import terminal


# These files we haven't cleaned up yet.  We filter entire files to avoid having
# to update the baseline when bad lines move around.
KNOWN_ISSUES = (
    # go/keep-sorted start
    "api/api_config.py",
    "api/compile_build_api_proto.py",
    "api/contrib/depgraph_common_ancestors.py",
    "api/contrib/fetch_builder_requests.py",
    "api/controller/artifacts.py",
    "api/controller/binhost.py",
    "api/controller/binhost_unittest.py",
    "api/controller/controller_util.py",
    "api/controller/controller_util_unittest.py",
    "api/controller/dependency_unittest.py",
    "api/controller/dlc.py",
    "api/controller/firmware.py",
    "api/controller/firmware_unittest.py",
    "api/controller/image.py",
    "api/controller/image_unittest.py",
    "api/controller/observability.py",
    "api/controller/packages.py",
    "api/controller/payload.py",
    "api/controller/payload_unittest.py",
    "api/controller/recovery.py",
    "api/controller/sdk.py",
    "api/controller/sdk_unittest.py",
    "api/controller/signing_unittest.py",
    "api/controller/sysroot.py",
    "api/controller/sysroot_unittest.py",
    "api/controller/test.py",
    "api/controller/test_unittest.py",
    "api/controller/toolchain.py",
    "api/controller/toolchain_unittest.py",
    "api/faux.py",
    "api/field_handler.py",
    "api/field_handler_unittest.py",
    "api/message_util.py",
    "api/router.py",
    "api/router_unittest.py",
    "api/validate.py",
    "api/validate_unittest.py",
    "cli/analyzers.py",
    "cli/command.py",
    "cli/command_unittest.py",
    "cli/command_vm_test.py",
    "cli/cros/cros_analyze_image.py",
    "cli/cros/cros_ap.py",
    "cli/cros/cros_build_image.py",
    "cli/cros/cros_build_kernel_unittest.py",
    "cli/cros/cros_build_packages.py",
    "cli/cros/cros_chrome_sdk.py",
    "cli/cros/cros_chrome_sdk_unittest.py",
    "cli/cros/cros_clean.py",
    "cli/cros/cros_clean_outdated_pkgs.py",
    "cli/cros/cros_cp.py",
    "cli/cros/cros_cp_unittest.py",
    "cli/cros/cros_cron.py",
    "cli/cros/cros_cron_unittest.py",
    "cli/cros/cros_debug.py",
    "cli/cros/cros_debug_unittest.py",
    "cli/cros/cros_deploy.py",
    "cli/cros/cros_deploy_unittest.py",
    "cli/cros/cros_flash.py",
    "cli/cros/cros_flash_unittest.py",
    "cli/cros/cros_format.py",
    "cli/cros/cros_lint.py",
    "cli/cros/cros_shell.py",
    "cli/cros/cros_shell_unittest.py",
    "cli/cros/cros_telemetry.py",
    "cli/cros/cros_try.py",
    "cli/cros/lint.py",
    "cli/cros/lint_unittest.py",
    "cli/deploy.py",
    "cli/deploy_unittest.py",
    "cli/device_imager.py",
    "cli/device_imager_unittest.py",
    "cli/flash.py",
    "cli/flash_unittest.py",
    "contrib/aue_overlays.py",
    "contrib/bug_reporting/bug_reporting.py",
    "contrib/cl_perf.py",
    "contrib/codemod/auto_type_dunders.py",
    "contrib/codemod/auto_type_none.py",
    "contrib/copybot_downstream.py",
    "contrib/copybot_downstream_config/coreboot_downstream.py",
    "contrib/copybot_downstream_config/downstream_argparser.py",
    "contrib/crosfw.py",
    "contrib/dump_depgraph.py",
    "contrib/ebuild_housekeeping.py",
    "contrib/find_unused_pkgs.py",
    "contrib/fwgdb.py",
    "contrib/generate_cs_path.py",
    "contrib/generate_firmware_configs.py",
    "contrib/gob-meta-config-checkout.py",
    "contrib/gs_dump_acls.py",
    "contrib/guestos/deploy_to_termina.py",
    "contrib/img_size.py",
    "contrib/libcst_tool.py",
    "contrib/package_index_cros/lib/cdb.py",
    "contrib/package_index_cros/lib/cdb_unittest.py",
    "contrib/package_index_cros/lib/conductor_unittest.py",
    "contrib/package_index_cros/lib/package.py",
    "contrib/package_index_cros/lib/package_sleuth.py",
    "contrib/package_index_cros/lib/package_sleuth_unittest.py",
    "contrib/package_index_cros/lib/package_unittest.py",
    "contrib/package_index_cros/lib/path_handler_unittest.py",
    "contrib/package_index_cros/lib/setup.py",
    "contrib/package_index_cros/lib/setup_unittest.py",
    "contrib/package_index_cros/lib/testing_utils.py",
    "contrib/parse_emerge.py",
    "contrib/portage_explorer/get_ebuild_metadata_spider.py",
    "contrib/portage_explorer/get_overlays_spider.py",
    "contrib/portage_explorer/spider_testables.py",
    "contrib/uprev_frequency.py",
    "contrib/you_dont_need_libchrome.py",
    "cros/test/image_test.py",
    "cros/test/usergroup_baseline.py",
    "format/formatters/gn.py",
    "format/formatters/json.py",
    "format/formatters/repo_manifest.py",
    "format/formatters/rust.py",
    "format/formatters/star.py",
    "format/formatters/textproto.py",
    "ide_tooling/scripts/compdb_no_chroot.py",
    "ide_tooling/scripts/compdb_no_chroot_unittest.py",
    "ide_tooling/scripts/detect_indent.py",
    "ide_tooling/scripts/detect_indent_unittest.py",
    "lib/alerts_unittest.py",
    "lib/auth.py",
    "lib/auth_unittest.py",
    "lib/autotest_util.py",
    "lib/autotest_util_unittest.py",
    "lib/binpkg.py",
    "lib/build_query.py",
    "lib/build_query_unittest.py",
    "lib/build_target_lib.py",
    "lib/buildbucket_v2.py",
    "lib/buildbucket_v2_unittest.py",
    "lib/cache.py",
    "lib/cache_unittest.py",
    "lib/chrome_lkgm.py",
    "lib/chrome_lkgm_unittest.py",
    "lib/chrome_util_unittest.py",
    "lib/chromeos_version.py",
    "lib/chroot_lib.py",
    "lib/chroot_lib_unittest.py",
    "lib/chroot_util_unittest.py",
    "lib/cipd.py",
    "lib/cipd_unittest.py",
    "lib/citc_workspaces.py",
    "lib/citc_workspaces_unittest.py",
    "lib/commandline.py",
    "lib/commandline_unittest.py",
    "lib/completers/package_completers.py",
    "lib/compression_lib.py",
    "lib/compression_lib_unittest.py",
    "lib/constants.py",
    "lib/cros_build_lib.py",
    "lib/cros_build_lib_unittest.py",
    "lib/cros_sdk_lib.py",
    "lib/cros_sdk_lib_unittest.py",
    "lib/cros_test.py",
    "lib/cros_test_lib.py",
    "lib/cros_test_lib_unittest.py",
    "lib/cros_test_unittest.py",
    "lib/debugger.py",
    "lib/dependency_graph.py",
    "lib/dependency_lib.py",
    "lib/depgraph.py",
    "lib/depgraph_unittest.py",
    "lib/disk_layout.py",
    "lib/dlc_allowlist.py",
    "lib/dlc_allowlist_unittest.py",
    "lib/dlc_lib.py",
    "lib/dlc_lib_unittest.py",
    "lib/dot_helper.py",
    "lib/firmware/ap_firmware_config/__init__.py",
    "lib/firmware/firmware_lib.py",
    "lib/firmware/firmware_lib_unittest.py",
    "lib/flexor.py",
    "lib/fwbuddy/fwbuddy.py",
    "lib/fwbuddy/fwbuddy_unittest.py",
    "lib/gerrit_unittest.py",
    "lib/git.py",
    "lib/git_unittest.py",
    "lib/gmerge_binhost.py",
    "lib/gob_util.py",
    "lib/gob_util_unittest.py",
    "lib/gs.py",
    "lib/gs_unittest.py",
    "lib/image_lib.py",
    "lib/image_lib_unittest.py",
    "lib/kernel_builder.py",
    "lib/kernel_builder_unittest.py",
    "lib/kernel_cmdline.py",
    "lib/kernel_cmdline_unittest.py",
    "lib/loas.py",
    "lib/locking_unittest.py",
    "lib/luci/prpc/client_unittest.py",
    "lib/luci/test_support/auto_stub.py",
    "lib/metrics.py",
    "lib/metrics_lib.py",
    "lib/metrics_lib_unittest.py",
    "lib/minios_unittest.py",
    "lib/namespaces_unittest.py",
    "lib/nebraska_wrapper.py",
    "lib/nebraska_wrapper_unittest.py",
    "lib/on_device_fuzz.py",
    "lib/on_device_fuzz_unittest.py",
    "lib/operation.py",
    "lib/operation_unittest.py",
    "lib/osutils.py",
    "lib/osutils_unittest.py",
    "lib/parallel.py",
    "lib/parallel_unittest.py",
    "lib/parseelf_unittest.py",
    "lib/parser/elog_unittest.py",
    "lib/partial_mock_unittest.py",
    "lib/patch.py",
    "lib/patch_unittest.py",
    "lib/path_util.py",
    "lib/path_util_unittest.py",
    "lib/paygen/gslock.py",
    "lib/paygen/gslock_unittest.py",
    "lib/paygen/gspaths.py",
    "lib/paygen/partition_lib.py",
    "lib/paygen/partition_lib_unittest.py",
    "lib/paygen/paygen_build_lib.py",
    "lib/paygen/paygen_payload_lib.py",
    "lib/paygen/paygen_payload_lib_unittest.py",
    "lib/paygen/paygen_provision_payload.py",
    "lib/paygen/paygen_stateful_payload_lib.py",
    "lib/paygen/signer_payloads_client.py",
    "lib/paygen/signer_payloads_client_unittest.py",
    "lib/paygen/urilib.py",
    "lib/paygen/utils.py",
    "lib/paygen/utils_unittest.py",
    "lib/portage_util.py",
    "lib/portage_util_unittest.py",
    "lib/process_util_unittest.py",
    "lib/protofiles_lib.py",
    "lib/qemu.py",
    "lib/remote_access.py",
    "lib/remoteexec_lib.py",
    "lib/remoteexec_lib_unittest.py",
    "lib/repo_util_unittest.py",
    "lib/retry_stats.py",
    "lib/retry_stats_unittest.py",
    "lib/retry_util_unittest.py",
    "lib/sdk_builder_lib.py",
    "lib/sdk_builder_lib_unittest.py",
    "lib/stateful_updater.py",
    "lib/stateful_updater_unittest.py",
    "lib/subtool_lib.py",
    "lib/subtool_lib_unittest.py",
    "lib/sudo.py",
    "lib/sysroot_lib.py",
    "lib/sysroot_lib_unittest.py",
    "lib/telemetry/__init__.py",
    "lib/telemetry/config.py",
    "lib/telemetry/config_unittest.py",
    "lib/telemetry/cros_detector.py",
    "lib/telemetry/cros_detector_unittest.py",
    "lib/telemetry/telemetry_unittest.py",
    "lib/telemetry/trace/chromite_span.py",
    "lib/telemetry/trace/chromite_tracer.py",
    "lib/telemetry/trace/chromite_tracer_unittest.py",
    "lib/telemetry_publisher.py",
    "lib/telemetry_publisher_unittest.py",
    "lib/terminal.py",
    "lib/timeout_util.py",
    "lib/toolchain.py",
    "lib/toolchain_list.py",
    "lib/toolchain_unittest.py",
    "lib/toolchain_util.py",
    "lib/toolchain_util_unittest.py",
    "lib/ts_mon_config.py",
    "lib/ts_mon_config_unittest.py",
    "lib/uprev_lib.py",
    "lib/uprev_lib_unittest.py",
    "lib/verity.py",
    "lib/vm.py",
    "lib/vm_unittest.py",
    "lib/workon_helper.py",
    "lib/workon_helper_unittest.py",
    "lib/xbuddy/android_build.py",
    "lib/xbuddy/build_artifact.py",
    "lib/xbuddy/build_artifact_unittest.py",
    "lib/xbuddy/common_util.py",
    "lib/xbuddy/downloader_unittest.py",
    "lib/xbuddy/xbuddy.py",
    "lib/xbuddy/xbuddy_unittest.py",
    "licensing/licenses_lib.py",
    "licensing/licenses_lib_unittest.py",
    "lint/linters/gnlint.py",
    "lint/linters/gnlint_unittest.py",
    "lint/linters/portage_layout_conf.py",
    "lint/linters/shell.py",
    "lint/linters/upstart_unittest.py",
    "scripts/analyze_bazel_exec_logs.py",
    "scripts/autotest_quickmerge.py",
    "scripts/autotest_quickmerge_unittest.py",
    "scripts/bazel.py",
    "scripts/build_minios_unittest.py",
    "scripts/build_sdk_subtools.py",
    "scripts/chrome_chromeos_lkgm_unittest.py",
    "scripts/clang_format.py",
    "scripts/clang_format_unittest.py",
    "scripts/collect_third_party_inventory.py",
    "scripts/create_pinned_chromite_tarball.py",
    "scripts/cros_choose_profile.py",
    "scripts/cros_choose_profile_unittest.py",
    "scripts/cros_fuzz.py",
    "scripts/cros_fuzz_unittest.py",
    "scripts/cros_gdb.py",
    "scripts/cros_generate_borealis_breakpad_symbols.py",
    "scripts/cros_generate_breakpad_symbols.py",
    "scripts/cros_generate_coverage_artifacts.py",
    "scripts/cros_generate_coverage_artifacts_unittest.py",
    "scripts/cros_generate_dlc_artifacts.py",
    "scripts/cros_generate_local_binhosts.py",
    "scripts/cros_generate_os_release.py",
    "scripts/cros_generate_sysroot.py",
    "scripts/cros_generate_sysroot_unittest.py",
    "scripts/cros_generate_tidy_warnings.py",
    "scripts/cros_list_modified_packages.py",
    "scripts/cros_losetup.py",
    "scripts/cros_losetup_unittest.py",
    "scripts/cros_mark_android_as_stable.py",
    "scripts/cros_mark_as_stable.py",
    "scripts/cros_mark_as_stable_unittest.py",
    "scripts/cros_on_device_fuzz.py",
    "scripts/cros_portage_upgrade.py",
    "scripts/cros_portage_upgrade_unittest.py",
    "scripts/cros_relevancy.py",
    "scripts/cros_run_unit_tests.py",
    "scripts/cros_sdk.py",
    "scripts/cros_sdk_unittest.py",
    "scripts/cros_setup_toolchains.py",
    "scripts/cros_update_metadata_cache.py",
    "scripts/cros_vm.py",
    "scripts/cros_workon_make.py",
    "scripts/dep_tracker.py",
    "scripts/dep_tracker_unittest.py",
    "scripts/deploy_chrome.py",
    "scripts/deploy_chrome_unittest.py",
    "scripts/disk_layout_tool.py",
    "scripts/gconv_strip.py",
    "scripts/generate_reclient_inputs.py",
    "scripts/gerrit.py",
    "scripts/gerrit_unittest.py",
    "scripts/get_chromite_relevant_files.py",
    "scripts/image_to_default_key_stateful.py",
    "scripts/image_to_lvm.py",
    "scripts/install_toolchain_unittest.py",
    "scripts/lint_package.py",
    "scripts/lint_package_unittest.py",
    "scripts/loman_unittest.py",
    "scripts/package_has_missing_deps.py",
    "scripts/parallel_emerge.py",
    "scripts/pkg_size.py",
    "scripts/portage_cmd_wrapper.py",
    "scripts/publish_telemetry.py",
    "scripts/run_chroot_version_hooks.py",
    "scripts/run_tests.py",
    "scripts/run_typing.py",
    "scripts/skeleton.py",
    "scripts/sysmon/net_metrics_unittest.py",
    "scripts/sysmon/osinfo_metrics_unittest.py",
    "scripts/sysmon/proc_metrics.py",
    "scripts/sysmon/system_metrics.py",
    "scripts/tbi_build_firmware.py",
    "scripts/telemetry_poc.py",
    "scripts/test_image_unittest.py",
    "scripts/tricium_cargo_clippy.py",
    "scripts/tricium_cargo_clippy_unittest.py",
    "scripts/tricium_clang_tidy.py",
    "scripts/trigger_gsc_signing.py",
    "scripts/upload_prebuilts.py",
    "scripts/upload_prebuilts_unittest.py",
    "scripts/vpython_consistency_unittest.py",
    "scripts/vpython_wrapper.py",
    "scripts/wrapper3_unittest.py",
    "scripts/xz_auto.py",
    "scripts/xz_auto_unittest.py",
    "service/android.py",
    "service/android_unittest.py",
    "service/artifacts.py",
    "service/artifacts_unittest.py",
    "service/binhost.py",
    "service/binhost_unittest.py",
    "service/dependency.py",
    "service/image.py",
    "service/image_unittest.py",
    "service/kernel_image.py",
    "service/kernel_image_unittest.py",
    "service/observability.py",
    "service/observability_unittest.py",
    "service/packages.py",
    "service/packages_unittest.py",
    "service/payload.py",
    "service/payload_unittest.py",
    "service/sdk.py",
    "service/sdk_subtools.py",
    "service/sdk_unittest.py",
    "service/sysroot.py",
    "service/sysroot_unittest.py",
    "service/test.py",
    "service/toolchain.py",
    "service/toolchain_unittest.py",
    "signing/bin/dump_image_config_unittest.py",
    "signing/bin/update_release_keys.py",
    "signing/bin/update_release_keys_unittest.py",
    "signing/image_signing/imagefile.py",
    "signing/image_signing/imagefile_unittest.py",
    "signing/lib/firmware.py",
    "signing/lib/keys.py",
    "signing/lib/keys_unittest.py",
    "signing/lib/signer.py",
    "signing/lib/signer_unittest.py",
    "test/portage_testables.py",
    "test/portage_testables_unittest.py",
    "utils/c_blkpg_unittest.py",
    "utils/code_coverage_util.py",
    "utils/code_coverage_util_unittest.py",
    "utils/field_mask_util.py",
    "utils/key_value_store_unittest.py",
    "utils/matching_unittest.py",
    "utils/memoize_unittest.py",
    "utils/os_util_unittest.py",
    "utils/parser/ebuild_license_unittest.py",
    "utils/parser/pms_dependency.py",
    "utils/parser/portage_md5_cache.py",
    "utils/parser/upstart.py",
    "utils/prctl.py",
    "utils/prctl_unittest.py",
    "utils/repo_manifest.py",
    "utils/repo_manifest_unittest.py",
    "utils/shell_util.py",
    "utils/shell_util_unittest.py",
    "utils/telemetry/detector.py",
    "utils/telemetry/utils_unittest.py",
    "utils/xdg_util.py",
    "utils/xdg_util_unittest.py",
    # go/keep-sorted end
)


@dataclasses.dataclass(frozen=True)
class Report:
    """A single report."""

    file: str
    line: int
    severity: str
    message: str

    def __str__(self) -> str:
        """Mimic the mypy output."""
        return f"{self.file}:{self.line}: {self.severity}:{self.message}"

    def __lt__(self, other: "Report") -> bool:
        """Basic compare logic to sort results."""
        if self.file == other.file:
            return self.line < other.line
        else:
            return self.file < other.file


def parse_output(output: str) -> Iterator[Report]:
    """Parse the output into structured results."""
    lines = output.splitlines()
    if lines[-1].startswith("Found "):
        lines.pop()

    # Our current version of mypy produces output like:
    #   file.py:88: error: msg
    # Newer versions can produce JSON like:
    #   {"file": "file.py", "line": 88, "severity": "error", "message": "msg"}
    # Once we upgrade to mypy 1.11+, we can switch to the --output=json format
    # instead of parsing ourselves.  Until then, the Report object fields use
    # the same naming conventions as the newer JSON output so it's easier to
    # switch one day.
    for line in lines:
        ele = line.split(":", 3)
        if len(ele) != 4:
            logging.warning("Unknown output: %s", line)
            continue

        yield Report(
            file=ele[0],
            line=int(ele[1]),
            severity=ele[2].strip(),
            message=ele[3],
        )


def sort_results(output: str) -> Iterator[str]:
    """Sort the results by file."""
    blocks = []
    block = []
    file = None
    for report in parse_output(output):
        if file != report.file:
            if block:
                blocks.append(block)
                block = []
            file = report.file
        block.append(report)

    blocks.append(block)
    blocks.sort()
    for block in blocks:
        yield from block


def get_parser() -> commandline.ArgumentParser:
    """Build the parser for command line arguments."""
    parser = commandline.ArgumentParser(
        description=__doc__, default_log_level="notice"
    )
    parser.add_bool_argument(
        "--relaxed",
        True,
        "Ignore known issues in the codebase.",
        "Fail on all errors.",
    )
    parser.add_argument(
        "args",
        metavar="tool arguments",
        nargs="*",
        help="Arguments to pass to the type checker (use -- to help separate)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> Optional[int]:
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.freeze()

    # Hacky heuristic to see if a path was specified.  If not, use chromite.
    paths = []
    for arg in opts.args:
        if arg.startswith("-"):
            break
        paths.append(arg)
    if not paths:
        paths = [os.path.relpath(constants.CHROMITE_DIR)]
        full_run = True
    else:
        paths.clear()
        full_run = False

    # Refresh pyi files since the type checking needs it.  It only takes ~1 sec
    # to run, so doing it all the time isn't a problem.
    cros_build_lib.dbg_run(
        [
            constants.CHROMITE_DIR / "api" / "compile_build_api_proto",
            "--pyi",
        ]
    )

    # Run the tool, parse its output, sort it, then show it.
    # NB: It's important that we capture the output and post-process before we
    # print it out.  This is because scripts/run_tests.py runs us in parallel
    # and sends our output to a pipe.  If we filled the pipe, we'd block, and
    # we'd slow it down overall.  That could be fixed in run_tests to write the
    # output to a tempfile, but we also workaround it here by post-processing.
    result = cros_build_lib.run(
        [constants.CHROMITE_SCRIPTS_DIR / "mypy"] + opts.args + paths,
        check=False,
        encoding="utf-8",
        stdout=True,
    )
    # Check for stale baselines.
    stale_exceptions = set(KNOWN_ISSUES)
    new_reports = []
    known_reports = []
    for report in sort_results(result.stdout):
        stale_exceptions.discard(report.file)
        new_problem = (
            report.file not in KNOWN_ISSUES and report.severity != "note"
        )
        if new_problem:
            new_reports.append(str(report))
        else:
            known_reports.append(str(report))

    relaxed_returncode = bool(new_reports)
    # Print all known reports first since those will be "ignored".
    color = terminal.Color()
    for report in known_reports:
        print(report, color.Color(color.YELLOW, "[chromite/ignoring KI]"))
    for report in new_reports:
        print(report, color.Color(color.RED, "[chromite/NEW ERROR]"))

    if full_run and stale_exceptions:
        print(
            f"error: {__file__}: please remove old KNOWN_ISSUES:",
            " ".join(sorted(stale_exceptions)),
        )
        return 1

    return relaxed_returncode if opts.relaxed else result.returncode
