# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sysroot controller."""

import datetime
import logging
import os
from pathlib import Path
import traceback
from typing import TYPE_CHECKING

from chromite.api import controller
from chromite.api import faux
from chromite.api import metrics
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import sysroot_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import cros_build_lib
from chromite.lib import metrics_lib
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib import remoteexec_lib
from chromite.lib import sysroot_lib
from chromite.service import sysroot


if TYPE_CHECKING:
    from chromite.api import api_config


_ACCEPTED_LICENSES = "@CHROMEOS"

DEFAULT_BACKTRACK = 30

_BUILD_PACKAGES_TIMEOUT_MARGIN = datetime.timedelta(minutes=10)


def _GetBuildLogDirectory():
    """Get build log directory based on the env variables.

    Returns:
        a string of a directory name where build log may exist, or None if no
        potential directories exist.
    """
    # TODO(crbug.com/1045001): Replace environment variable with query to
    # an object after a refactoring allows this.
    candidates = [
        "GLOG_log_dir",
        "GOOGLE_LOG_DIR",
        "TEST_TMPDIR",
        "TMPDIR",
        "TMP",
    ]
    for candidate in candidates:
        value = os.environ.get(candidate)
        if value and os.path.isdir(value):
            return value

    # "/tmp" will always exist.
    return "/tmp"


def ExampleGetResponse():
    """Give an example response to assemble upstream in caller artifacts."""
    uabs = common_pb2.UploadedArtifactsByService
    cabs = common_pb2.ArtifactsByService
    return uabs.Sysroot(
        artifacts=[
            uabs.Sysroot.ArtifactPaths(
                artifact_type=cabs.Sysroot.ArtifactType.SIMPLE_CHROME_SYSROOT,
                paths=[
                    common_pb2.Path(
                        path=(
                            "/tmp/sysroot_chromeos-base_chromeos-chrome.tar.xz"
                        ),
                        location=common_pb2.Path.OUTSIDE,
                    )
                ],
            ),
            uabs.Sysroot.ArtifactPaths(
                artifact_type=cabs.Sysroot.ArtifactType.DEBUG_SYMBOLS,
                paths=[
                    common_pb2.Path(
                        path="/tmp/debug.tgz", location=common_pb2.Path.OUTSIDE
                    )
                ],
            ),
            uabs.Sysroot.ArtifactPaths(
                artifact_type=cabs.Sysroot.ArtifactType.BREAKPAD_DEBUG_SYMBOLS,
                paths=[
                    common_pb2.Path(
                        path="/tmp/debug_breakpad.tar.xz",
                        location=common_pb2.Path.OUTSIDE,
                    )
                ],
            ),
        ]
    )


@metrics_lib.timed("api.controller.sysroot.GetArtifacts")
def GetArtifacts(
    in_proto: common_pb2.ArtifactsByService.Sysroot,
    chroot: chroot_lib.Chroot,
    sysroot_class: sysroot_lib.Sysroot,
    build_target: build_target_lib.BuildTarget,
    output_dir: str,
) -> list:
    """Builds and copies sysroot artifacts to specified output_dir.

    Copies sysroot artifacts to output_dir, returning a list of
    (output_dir: str) paths to the desired files.

    Args:
        in_proto: Proto request defining reqs.
        chroot: The chroot class used for these artifacts.
        sysroot_class: The sysroot class used for these artifacts.
        build_target: The build target used for these artifacts.
        output_dir: The path to write artifacts to.

    Returns:
        A list of dictionary mappings of ArtifactType to list of paths.
    """

    def _BundleBreakpadSymbols(chroot, sysroot_class, build_target, output_dir):
        # pylint: disable=line-too-long
        ignore_breakpad_symbol_generation_expected_files = [
            common_pb2.ArtifactsByService.Sysroot.BreakpadSymbolGenerationExpectedFile.Name(
                x
            )
            for x in in_proto.ignore_breakpad_symbol_generation_expected_files
            if x
            != common_pb2.ArtifactsByService.Sysroot.BreakpadSymbolGenerationExpectedFile.EXPECTED_FILE_UNSET
            and x
            in common_pb2.ArtifactsByService.Sysroot.BreakpadSymbolGenerationExpectedFile.values()
        ]
        # pylint: enable=line-too-long

        ignore_breakpad_symbol_generation_expected_files = [
            x[len("EXPECTED_FILE_") :]
            for x in ignore_breakpad_symbol_generation_expected_files
        ]

        return sysroot.BundleBreakpadSymbols(
            chroot,
            sysroot_class,
            build_target,
            output_dir,
            in_proto.ignore_breakpad_symbol_generation_errors,
            ignore_breakpad_symbol_generation_expected_files,
        )

    generated = []
    # pylint: disable=line-too-long
    artifact_types = {
        in_proto.ArtifactType.SIMPLE_CHROME_SYSROOT: sysroot.CreateSimpleChromeSysroot,
        in_proto.ArtifactType.CHROME_EBUILD_ENV: sysroot.CreateChromeEbuildEnv,
        in_proto.ArtifactType.BREAKPAD_DEBUG_SYMBOLS: _BundleBreakpadSymbols,
        in_proto.ArtifactType.DEBUG_SYMBOLS: sysroot.BundleDebugSymbols,
        in_proto.ArtifactType.FUZZER_SYSROOT: sysroot.CreateFuzzerSysroot,
        in_proto.ArtifactType.SYSROOT_ARCHIVE: sysroot.ArchiveSysroot,
        in_proto.ArtifactType.BAZEL_PERFORMANCE_ARTIFACTS: sysroot.CollectBazelPerformanceArtifacts,
    }
    # pylint: enable=line-too-long

    for output_artifact in in_proto.output_artifacts:
        for artifact_type, func in artifact_types.items():
            if artifact_type in output_artifact.artifact_types:
                artifact_name = (
                    common_pb2.ArtifactsByService.Sysroot.ArtifactType.Name(
                        artifact_type
                    )
                )
                timer_name = f"sysroot.GetArtifacts.{artifact_name}"
                try:
                    with metrics_lib.timer(timer_name):
                        result = func(
                            chroot, sysroot_class, build_target, output_dir
                        )
                except Exception as e:
                    generated.append(
                        {
                            "type": artifact_type,
                            "failed": True,
                            "failure_reason": str(e),
                        }
                    )
                    logging.warning(
                        "%s artifact generation failed with exception %s",
                        artifact_name,
                        e,
                    )
                    logging.warning("traceback:\n%s", traceback.format_exc())
                    continue
                if result:
                    generated.append(
                        {
                            "paths": [str(result)]
                            if isinstance(result, (os.PathLike, str))
                            else result,
                            "type": artifact_type,
                        }
                    )

    return generated


@faux.all_empty
@validate.require("build_target.name")
@validate.validation_complete
def Create(request, response, _config):
    """Create or replace a sysroot."""
    update_chroot = not request.flags.chroot_current
    replace_sysroot = request.flags.replace
    use_cq_prebuilts = request.flags.use_cq_prebuilts
    binhost_lookup_service_data = request.binhost_lookup_service_data

    build_target = controller_util.ParseBuildTarget(
        request.build_target, request.profile
    )
    run_configs = sysroot.SetupBoardRunConfig(
        force=replace_sysroot,
        upgrade_chroot=update_chroot,
        use_cq_prebuilts=use_cq_prebuilts,
        backtrack=DEFAULT_BACKTRACK,
        binhost_lookup_service_data=binhost_lookup_service_data,
    )

    try:
        created = sysroot.Create(
            build_target, run_configs, accept_licenses=_ACCEPTED_LICENSES
        )
    except sysroot.Error as e:
        cros_build_lib.Die(e)

    response.sysroot.path = created.path
    response.sysroot.build_target.name = build_target.name
    response.sysroot.build_target.profile.name = build_target.profile

    return controller.RETURN_CODE_SUCCESS


@validate.require("build_target.name")
@validate.validation_complete
def GetTargetArchitecture(
    request: sysroot_pb2.GetTargetArchitectureRequest,
    response: sysroot_pb2.GetTargetArchitectureResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Determine the target architecture for the given build target."""
    build_target = build_target_lib.BuildTarget(request.build_target.name)
    architecture = build_target.board.arch
    if architecture:
        response.architecture = architecture


@faux.all_empty
@validate.require("build_target.name", "packages")
@validate.require_each("packages", ["category", "package_name"])
@validate.validation_complete
def GenerateArchive(request, response, _config) -> None:
    """Generate a sysroot. Typically used by informational builders."""
    build_target_name = request.build_target.name
    pkg_list = []
    for package in request.packages:
        pkg_list.append("%s/%s" % (package.category, package.package_name))

    with osutils.TempDir(delete=False) as temp_output_dir:
        sysroot_tar_path = sysroot.GenerateArchive(
            temp_output_dir, build_target_name, pkg_list
        )

    # By assigning this Path variable to the tar path, the tar file will be
    # copied out to the request's ResultPath location.
    response.sysroot_archive.path = sysroot_tar_path
    response.sysroot_archive.location = common_pb2.Path.INSIDE


@faux.all_empty
@validate.exists("sysroot_archive.path")
@validate.require("build_target.name")
@validate.validation_complete
def ExtractArchive(request, response, _config) -> None:
    """Extract archive to sysroot."""
    chroot = controller_util.ParseChroot(request.chroot)
    board = request.build_target.name
    sysroot_path = build_target_lib.get_default_sysroot_path(board)
    sysroot_archive = request.sysroot_archive.path

    result = sysroot.ExtractSysroot(
        chroot, sysroot_lib.Sysroot(sysroot_path), sysroot_archive
    )
    response.sysroot_archive.path = str(result)
    response.sysroot_archive.location = common_pb2.Path.INSIDE


def _MockFailedPackagesResponse(_request, response, _config) -> None:
    """Mock error response that populates failed packages."""
    fail = response.failed_package_data.add()
    fail.name.package_name = "package"
    fail.name.category = "category"
    fail.name.version = "1.0.0_rc-r1"
    fail.log_path.path = (
        "/path/to/package:category-1.0.0_rc-r1:20210609-1337.log"
    )
    fail.log_path.location = common_pb2.Path.INSIDE

    fail2 = response.failed_package_data.add()
    fail2.name.package_name = "bar"
    fail2.name.category = "foo"
    fail2.name.version = "3.7-r99"
    fail2.log_path.path = "/path/to/foo:bar-3.7-r99:20210609-1620.log"
    fail2.log_path.location = common_pb2.Path.INSIDE


@faux.empty_success
@faux.error(_MockFailedPackagesResponse)
@validate.require("sysroot.path", "sysroot.build_target.name")
@validate.exists("sysroot.path")
@validate.validation_complete
def InstallToolchain(request, response, _config):
    """Install the toolchain into a sysroot."""
    compile_source = (
        request.flags.compile_source or request.flags.toolchain_changed
    )

    sysroot_path = request.sysroot.path

    build_target = controller_util.ParseBuildTarget(
        request.sysroot.build_target
    )
    target_sysroot = sysroot_lib.Sysroot(sysroot_path)
    run_configs = sysroot.SetupBoardRunConfig(usepkg=not compile_source)

    _LogBinhost(build_target.name)

    try:
        sysroot.InstallToolchain(build_target, target_sysroot, run_configs)
    except sysroot_lib.ToolchainInstallError as e:
        controller_util.retrieve_package_log_paths(
            e.failed_toolchain_info, response, target_sysroot
        )

        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE

    return controller.RETURN_CODE_SUCCESS


@faux.empty_success
@faux.error(_MockFailedPackagesResponse)
@validate.require("sysroot.build_target.name")
@validate.exists("sysroot.path")
@validate.require_each("packages", ["category", "package_name"])
@validate.require_each("use_flags", ["flag"])
@validate.validation_complete
@metrics_lib.collect_metrics
def InstallPackages(
    request: sysroot_pb2.InstallPackagesRequest,
    response: sysroot_pb2.InstallPackagesResponse,
    _config: "api_config.ApiConfig",
):
    """Install packages into a sysroot, building as necessary and permitted."""
    compile_source = (
        request.flags.compile_source or request.flags.toolchain_changed
    )

    use_remoteexec = request.HasField("remoteexec_config")
    reproxy_cfg_file = ""
    if use_remoteexec:
        reproxy_cfg_file = request.remoteexec_config.reproxy_cfg_file

    target_sysroot = sysroot_lib.Sysroot(request.sysroot.path)
    build_target = controller_util.ParseBuildTarget(
        request.sysroot.build_target
    )
    build_target.profile = request.sysroot.build_target.profile.name

    # Get the package atom for each specified package. The field is optional, so
    # error only when we cannot parse an atom for each of the given packages.
    packages = [
        controller_util.deserialize_package_info(x).atom
        for x in request.packages
    ]

    # Calculate which packages would have been merged, but don't install
    # anything.
    dryrun = request.flags.dryrun

    # Allow cros workon packages to build from the unstable ebuilds.
    workon = request.flags.workon

    # Use Bazel to build packages.
    bazel = request.flags.bazel

    # Lite build restricts the set of packages that will be built.
    bazel_lite = (
        request.bazel_targets == sysroot_pb2.InstallPackagesRequest.LITE
    )

    # Execute Bazel actions remotely (for actions not set as no-remote-exec)
    bazel_use_remote_execution = request.flags.bazel_use_remote_execution

    noclean = request.flags.skip_clean_package_dirs
    binhost_lookup_service_data = request.binhost_lookup_service_data

    timeout = None
    # Ignore invalid timestamps (e.g. the internal value of the timestamp is 0
    # when the proto is filled with default values)
    if request.timeout_timestamp and request.timeout_timestamp.ToSeconds() != 0:
        timeout = (
            request.timeout_timestamp.ToDatetime()
            - _BUILD_PACKAGES_TIMEOUT_MARGIN
        )

    if not target_sysroot.IsToolchainInstalled():
        cros_build_lib.Die("Toolchain must first be installed.")

    _LogBinhost(build_target.name)

    use_flags = [u.flag for u in request.use_flags]
    build_packages_config = sysroot.BuildPackagesRunConfig(
        use_any_chrome=False,
        usepkg=not compile_source,
        packages=packages,
        use_flags=use_flags,
        use_remoteexec=use_remoteexec,
        reproxy_cfg_file=reproxy_cfg_file,
        incremental_build=False,
        dryrun=dryrun,
        backtrack=DEFAULT_BACKTRACK,
        workon=workon,
        bazel=bazel,
        bazel_lite=bazel_lite,
        noclean=noclean,
        binhost_lookup_service_data=binhost_lookup_service_data,
        timeout=timeout,
        bazel_use_remote_execution=bazel_use_remote_execution,
    )

    try:
        sysroot.BuildPackages(
            build_target,
            target_sysroot,
            build_packages_config,
        )
    except sysroot_lib.PackageInstallError as e:
        if not e.failed_packages:
            # No packages to report, so just exit with an error code.
            return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY

        controller_util.retrieve_package_log_paths(
            e.failed_packages, response, target_sysroot
        )

        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
    finally:
        if request.remoteexec_config.log_dir.dir:
            archiver = remoteexec_lib.LogsArchiver(
                dest_dir=Path(request.remoteexec_config.log_dir.dir),
            )
            archived_logs = archiver.archive()
            response.remoteexec_artifacts.log_files[:] = [
                str(x) for x in archived_logs
            ]

    # Return without populating the response if it is a dryrun.
    if dryrun:
        return controller.RETURN_CODE_SUCCESS

    # Read metric events log and pipe them into response.events.
    metrics.deserialize_metrics_log(response.events, prefix=build_target.name)


def _LogBinhost(board) -> None:
    """Log the portage binhost for the given board."""
    binhost = portage_util.PortageqEnvvar(
        "PORTAGE_BINHOST", board=board, allow_undefined=True
    )
    if not binhost:
        logging.warning("Portage Binhost not found.")
    else:
        logging.info("Portage Binhost: %s", binhost)
