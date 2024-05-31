# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Implements ArtifactService."""

import logging
import os
import shutil
from typing import Any, NamedTuple, Optional, TYPE_CHECKING

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.controller import image as image_controller
from chromite.api.controller import sysroot as sysroot_controller
from chromite.api.controller import test as test_controller
from chromite.api.gen.chromite.api import artifacts_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import sysroot_lib
from chromite.service import artifacts
from chromite.service import test


if TYPE_CHECKING:
    from chromite.api import api_config


class RegisteredGet(NamedTuple):
    """A registered function for calling Get on an artifact type."""

    response: artifacts_pb2.GetResponse
    artifact_dict: Any


def ExampleGetResponse(_request, _response, _config) -> Optional[int]:
    """Give an example GetResponse with a minimal coverage set."""
    _response = artifacts_pb2.GetResponse(
        artifacts=common_pb2.UploadedArtifactsByService(
            image=image_controller.ExampleGetResponse(),
            sysroot=sysroot_controller.ExampleGetResponse(),
        )
    )
    return controller.RETURN_CODE_SUCCESS


@faux.empty_error
@faux.success(ExampleGetResponse)
@validate.exists("result_path.path.path")
@validate.validation_complete
def Get(
    request: artifacts_pb2.GetRequest,
    response: artifacts_pb2.GetResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Get all artifacts.

    Get all artifacts for the build.

    Note: As the individual artifact_type bundlers are added here, they *must*
    stop uploading it via the individual bundler function.
    """
    output_dir = request.result_path.path.path

    sysroot = controller_util.ParseSysroot(request.sysroot)
    # This endpoint does not currently support any artifacts that are built
    # without a sysroot being present.
    if not sysroot.path:
        return controller.RETURN_CODE_SUCCESS

    chroot = controller_util.ParseChroot(request.chroot)
    build_target = controller_util.ParseBuildTarget(
        request.sysroot.build_target
    )

    # A list of RegisteredGet tuples (request, response, get results).
    get_res_list = [
        RegisteredGet(
            response.artifacts.image,
            image_controller.GetArtifacts(
                request.artifact_info.image,
                chroot,
                sysroot,
                build_target,
                output_dir,
            ),
        ),
        RegisteredGet(
            response.artifacts.sysroot,
            sysroot_controller.GetArtifacts(
                request.artifact_info.sysroot,
                chroot,
                sysroot,
                build_target,
                output_dir,
            ),
        ),
        RegisteredGet(
            response.artifacts.test,
            test_controller.GetArtifacts(
                request.artifact_info.test,
                chroot,
                sysroot,
                build_target,
                output_dir,
            ),
        ),
    ]

    for get_res in get_res_list:
        for artifact_dict in get_res.artifact_dict:
            kwargs = {}
            # TODO(b/255838545): Remove the kwargs funkness when these fields
            # have been added for all services.
            if "failed" in artifact_dict:
                kwargs["failed"] = artifact_dict.get("failed", False)
                kwargs["failure_reason"] = artifact_dict.get("failure_reason")
            get_res.response.artifacts.add(
                artifact_type=artifact_dict["type"],
                paths=[
                    common_pb2.Path(
                        path=x, location=common_pb2.Path.Location.OUTSIDE
                    )
                    for x in artifact_dict.get("paths", [])
                ],
                **kwargs,
            )
    return controller.RETURN_CODE_SUCCESS


def _BuildSetupResponse(_request, response, _config) -> None:
    """Just return POINTLESS for now."""
    # All the artifact types we support claim that the build is POINTLESS.
    response.build_relevance = artifacts_pb2.BuildSetupResponse.POINTLESS


@faux.success(_BuildSetupResponse)
@faux.empty_error
@validate.validation_complete
def BuildSetup(
    _request: artifacts_pb2.GetRequest,
    response: artifacts_pb2.GetResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Setup anything needed for building artifacts

    If any artifact types require steps prior to building the package, they go
    here.  For example, see ToolchainService/PrepareForBuild.

    Note: crbug/1034529 introduces this method as a noop.  As the individual
    artifact_type bundlers are added here, they *must* stop uploading it via the
    individual bundler function.
    """
    # If any artifact_type says "NEEDED", the return is NEEDED.
    # Otherwise, if any artifact_type says "UNKNOWN", the return is UNKNOWN.
    # Otherwise, the return is POINTLESS.
    response.build_relevance = artifacts_pb2.BuildSetupResponse.POINTLESS
    return controller.RETURN_CODE_SUCCESS


def _GetImageDir(build_root: str, target: str) -> Optional[str]:
    """Return path containing images for the given build target.

    TODO(saklein) Expand image_lib.GetLatestImageLink to support this use case.

    Args:
        build_root: Path to checkout where build occurs.
        target: Name of the build target.

    Returns:
        Path to the latest directory containing target images or None.
    """
    image_dir = os.path.join(build_root, "src/build/images", target, "latest")
    if not os.path.exists(image_dir):
        logging.warning(
            "Expected to find image output for target %s at %s, but "
            "path does not exist",
            target,
            image_dir,
        )
        return None

    return image_dir


def _BundleImageArchivesResponse(request, response, _config) -> None:
    """Add artifact paths to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "path0.tar.xz"),
            location=common_pb2.Path.OUTSIDE,
        )
    )
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "path1.tar.xz"),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleImageArchivesResponse)
@faux.empty_error
@validate.require("sysroot.build_target.name", "sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleImageArchives(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Create a .tar.xz archive for each image that has been created."""
    build_target = controller_util.ParseBuildTarget(
        request.sysroot.build_target
    )
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)
    output_dir = request.result_path.path.path
    image_dir = _GetImageDir(constants.SOURCE_ROOT, build_target.name)
    if image_dir is None:
        return

    if not sysroot.Exists(chroot=chroot):
        logging.warning("Sysroot does not exist: %s", sysroot.path)

    archives = artifacts.ArchiveImages(chroot, sysroot, image_dir, output_dir)

    for archive in archives:
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=os.path.join(output_dir, archive),
                location=common_pb2.Path.OUTSIDE,
            )
        )


def _BundleImageZipResponse(request, response, _config) -> None:
    """Add artifact zip files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "image.zip"),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleImageZipResponse)
@faux.empty_error
@validate.require("build_target.name", "result_path.path.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleImageZip(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Bundle image.zip."""
    target = request.build_target.name
    output_dir = request.result_path.path.path
    image_dir = _GetImageDir(constants.SOURCE_ROOT, target)
    if image_dir is None:
        logging.warning("Image build directory not found.")
        return None

    archive = artifacts.BundleImageZip(output_dir, image_dir)
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(output_dir, archive),
            location=common_pb2.Path.OUTSIDE,
        )
    )


def _BundleTestUpdatePayloadsResponse(request, response, _config) -> None:
    """Add test payload files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "payload1.bin"),
            location=common_pb2.Path.OUTSIDE,
        )
    )
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "payload1.json"),
            location=common_pb2.Path.OUTSIDE,
        )
    )
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "payload1.log"),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleTestUpdatePayloadsResponse)
@faux.empty_error
@validate.require("build_target.name")
@validate.validation_complete
def BundleTestUpdatePayloads(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Generate minimal update payloads for the build target for testing."""
    target = request.build_target.name
    chroot = controller_util.ParseChroot(request.chroot)
    build_root = constants.SOURCE_ROOT
    # Leave artifact output intact, for the router layer to copy it out of the
    # chroot. This may leave stray files leftover, but builders should clean
    # these up.
    output_dir = chroot.tempdir(delete=False)

    # Use the first available image to create the update payload.
    img_dir = _GetImageDir(build_root, target)
    if img_dir is None:
        return None

    img_types = [
        constants.IMAGE_TYPE_TEST,
        constants.IMAGE_TYPE_DEV,
        constants.IMAGE_TYPE_BASE,
    ]
    img_names = [constants.IMAGE_TYPE_TO_NAME[t] for t in img_types]
    img_paths = [os.path.join(img_dir, x) for x in img_names]
    valid_images = [x for x in img_paths if os.path.exists(x)]

    if not valid_images:
        cros_build_lib.Die(
            'Expected to find an image of type among %r for target "%s" '
            "at path %s.",
            img_types,
            target,
            img_dir,
        )
    image = valid_images[0]

    payloads = artifacts.BundleTestUpdatePayloads(
        chroot, image, str(output_dir)
    )
    for payload in payloads:
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=payload, location=common_pb2.Path.INSIDE
            ),
        )


def _BundleAutotestFilesResponse(request, response, _config) -> None:
    """Add test autotest files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, "autotest-a.tar.gz"
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleAutotestFilesResponse)
@faux.empty_error
@validate.require("sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleAutotestFiles(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Tar the autotest files for a build target."""
    output_dir = request.result_path.path.path
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)

    if not sysroot.Exists(chroot=chroot):
        logging.warning("Sysroot does not exist: %s", sysroot.path)
        return

    try:
        # Note that this returns the full path to *multiple* tarballs.
        archives = artifacts.BundleAutotestFiles(chroot, sysroot, output_dir)
    except artifacts.Error as e:
        logging.warning(e)
        return

    for archive in archives.values():
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=archive, location=common_pb2.Path.OUTSIDE
            )
        )


def _BundleTastFilesResponse(request, response, _config) -> None:
    """Add test tast files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, "tast_bundles.tar.gz"
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )

    # Add test tast intel private files to a successful response.
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, "tast_intel_bundles.tar.gz"
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleTastFilesResponse)
@faux.empty_error
@validate.require("sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleTastFiles(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Tar the tast files for a build target."""
    output_dir = request.result_path.path.path
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)

    tast_use_flag_path = chroot.full_path(
        sysroot.JoinPath("etc/tast_use_flags.txt")
    )

    if os.path.exists(tast_use_flag_path):
        logging.info("Found tast_use_flags.txt file at %s.", tast_use_flag_path)
        tast_use_flag_output_dir_path = os.path.join(
            output_dir, os.path.basename(tast_use_flag_path)
        )
        shutil.copy(tast_use_flag_path, tast_use_flag_output_dir_path)
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=tast_use_flag_output_dir_path,
                location=common_pb2.Path.OUTSIDE,
            )
        )
    else:
        logging.warning(
            "Found no tast_use_flags.txt file at %s.", tast_use_flag_path
        )

    if not sysroot.Exists(chroot=chroot):
        logging.warning("Sysroot does not exist: %s", sysroot.path)
        return

    # Add test tast private files to a successful response.
    archive = artifacts.BundleTastFiles(chroot, sysroot, output_dir)

    if not archive:
        logging.warning("Found no tast files for %s.", sysroot.path)
        return

    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=archive, location=common_pb2.Path.OUTSIDE
        )
    )

    # Add test tast intel private files to a successful response.
    archive = artifacts.BundleTastIntelFiles(chroot, sysroot, output_dir)

    if not archive:
        logging.warning("Found no tast intel files for %s.", sysroot.path)
        return

    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=archive, location=common_pb2.Path.OUTSIDE
        )
    )


def BundlePinnedGuestImages(_request, _response, _config) -> None:
    # TODO(crbug/1034529): Remove this endpoint
    pass


def FetchPinnedGuestImageUris(_request, _response, _config) -> None:
    # TODO(crbug/1034529): Remove this endpoint
    pass


def _FetchCentralizedSuitesResponse(
    _request: artifacts_pb2.FetchCentralizedSuitesRequest,
    response: artifacts_pb2.FetchCentralizedSuitesResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Populate the response with sample data."""
    response.suite_set_file.path.CopyFrom(
        common_pb2.Path(
            path="/centralized-suites/suite_sets.pb",
            location=common_pb2.Path.OUTSIDE,
        )
    )
    response.suite_file.path.CopyFrom(
        common_pb2.Path(
            path="/centralized-suites/suites.pb",
            location=common_pb2.Path.OUTSIDE,
        )
    )
    return controller.RETURN_CODE_SUCCESS


@faux.success(_FetchCentralizedSuitesResponse)
@faux.empty_error
@validate.exists("chroot.path")
@validate.require("sysroot.path")
@validate.validation_complete
def FetchCentralizedSuites(
    request: artifacts_pb2.FetchCentralizedSuitesRequest,
    response: artifacts_pb2.FetchCentralizedSuitesResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """FetchCentralizedSuites returns the paths to the centralized suite files.

    This implements ArtifactsService.FetchCentralizedSuites.
    """
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)
    response.suite_set_file.path.CopyFrom(
        common_pb2.Path(
            path=test.FindSuiteSetFile(chroot, sysroot),
            location=common_pb2.Path.OUTSIDE,
        )
    )
    response.suite_file.path.CopyFrom(
        common_pb2.Path(
            path=test.FindSuiteFile(chroot, sysroot),
            location=common_pb2.Path.OUTSIDE,
        )
    )
    return controller.RETURN_CODE_SUCCESS


def _FetchMetadataResponse(_request, response, _config) -> Optional[int]:
    """Populate the response with sample data."""
    for path in ("/metadata/foo.txt", "/metadata/bar.jsonproto"):
        response.filepaths.add(
            path=common_pb2.Path(path=path, location=common_pb2.Path.OUTSIDE)
        )
    return controller.RETURN_CODE_SUCCESS


@faux.success(_FetchMetadataResponse)
@faux.empty_error
@validate.exists("chroot.path")
@validate.require("sysroot.path")
@validate.validation_complete
def FetchMetadata(
    request: artifacts_pb2.FetchMetadataRequest,
    response: artifacts_pb2.FetchMetadataResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """FetchMetadata returns the paths to all build/test metadata files.

    This implements ArtifactsService.FetchMetadata.
    """
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)
    for path in test.FindAllMetadataFiles(chroot, sysroot):
        response.filepaths.add(
            path=common_pb2.Path(path=path, location=common_pb2.Path.OUTSIDE)
        )
    return controller.RETURN_CODE_SUCCESS


def _FetchTestHarnessMetadataResponse(
    _request, response, _config
) -> Optional[int]:
    """Populate the response with sample data."""
    for path in ("/metadata/foo.txt", "/metadata/bar.jsonproto"):
        response.filepaths.add(
            path=common_pb2.Path(path=path, location=common_pb2.Path.OUTSIDE)
        )
    return controller.RETURN_CODE_SUCCESS


@faux.success(_FetchTestHarnessMetadataResponse)
@faux.empty_error
@validate.exists("chroot.path")
@validate.require("sysroot.path")
@validate.validation_complete
def FetchTestHarnessMetadata(
    request: artifacts_pb2.FetchTestHarnessMetadataRequest,
    response: artifacts_pb2.FetchTestHarnessMetadataResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """FetchTestHarnessMetadata returns the paths to harness metadata files.

    This implements ArtifactsService.FetchTestHarnessMetadata.
    """
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)
    for path in test.FindAllHarnessMetadataFiles(chroot, sysroot):
        response.filepaths.add(
            path=common_pb2.Path(path=path, location=common_pb2.Path.OUTSIDE)
        )
    return controller.RETURN_CODE_SUCCESS


def _BundleFirmwareResponse(request, response, _config) -> None:
    """Add test firmware image files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "firmware.tar.gz"),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleFirmwareResponse)
@faux.empty_error
@validate.require("sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleFirmware(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Tar the firmware images for a build target."""
    output_dir = request.result_path.path.path
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)

    if not chroot.exists():
        logging.warning("Chroot does not exist: %s", chroot.path)
        return
    elif not sysroot.Exists(chroot=chroot):
        logging.warning("Sysroot does not exist: %s", sysroot.path)
        return

    # Bundle firmware_from_source.tar.bz2
    archive = artifacts.BuildFirmwareArchive(chroot, sysroot, output_dir)

    if not archive:
        logging.warning(
            "Could not create firmware archive. No firmware found for %s.",
            sysroot.path,
        )
    else:
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=archive, location=common_pb2.Path.OUTSIDE
            )
        )

    # Bundle pinned_firmware.tar.bz2
    archive = artifacts.BuildPinnedFirmwareArchive(chroot, sysroot, output_dir)

    if not archive:
        logging.warning(
            "Pinned firmware not found for %s.",
            sysroot.path,
        )
    else:
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=archive, location=common_pb2.Path.OUTSIDE
            )
        )


def _BundleFpmcuUnittestsResponse(request, response, _config) -> None:
    """Add fingerprint MCU unittest binaries to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, "fpmcu_unittests.tar.gz"
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleFpmcuUnittestsResponse)
@faux.empty_error
@validate.require("sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleFpmcuUnittests(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Tar the fingerprint MCU unittest binaries for a build target."""
    output_dir = request.result_path.path.path
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)

    if not chroot.exists():
        logging.warning("Chroot does not exist: %s", chroot.path)
        return
    elif not sysroot.Exists(chroot=chroot):
        logging.warning("Sysroot does not exist: %s", sysroot.path)
        return

    archive = artifacts.BundleFpmcuUnittests(chroot, sysroot, output_dir)

    if not archive:
        logging.warning("No fpmcu unittests found for %s.", sysroot.path)
        return

    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=archive, location=common_pb2.Path.OUTSIDE
        )
    )


def _BundleEbuildLogsResponse(request, response, _config) -> None:
    """Add test log files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, "ebuild-logs.tar.gz"
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleEbuildLogsResponse)
@faux.empty_error
@validate.require("sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleEbuildLogs(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Tar the ebuild logs for a build target."""
    output_dir = request.result_path.path.path
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)

    if not sysroot.Exists(chroot=chroot):
        logging.warning("Sysroot does not exist: %s", sysroot.path)
        return

    archive = artifacts.BundleEBuildLogsTarball(chroot, sysroot, output_dir)

    if not archive:
        logging.warning(
            "Could not create ebuild logs archive. No logs found for %s.",
            sysroot.path,
        )
        return

    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(output_dir, archive),
            location=common_pb2.Path.OUTSIDE,
        )
    )


def _BundleChromeOSConfigResponse(request, response, _config) -> None:
    """Add test config files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(request.result_path.path.path, "config.yaml"),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleChromeOSConfigResponse)
@faux.empty_error
@validate.require("sysroot.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleChromeOSConfig(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Output the ChromeOS Config payload for a build target."""
    output_dir = request.result_path.path.path
    chroot = controller_util.ParseChroot(request.chroot)
    sysroot = controller_util.ParseSysroot(request.sysroot)

    chromeos_config = artifacts.BundleChromeOSConfig(
        chroot, sysroot, output_dir
    )

    if not chromeos_config:
        logging.warning(
            "Could not create ChromeOS Config for %s.", sysroot.path
        )
        return

    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(output_dir, chromeos_config),
            location=common_pb2.Path.OUTSIDE,
        )
    )


def _BundleSimpleChromeArtifactsResponse(request, response, _config) -> None:
    """Add test simple chrome files to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, "simple_chrome.txt"
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleSimpleChromeArtifactsResponse)
@faux.empty_error
@validate.require(
    "result_path.path.path", "sysroot.build_target.name", "sysroot.path"
)
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleSimpleChromeArtifacts(request, response, _config) -> Optional[int]:
    """Create the simple chrome artifacts."""
    sysroot_path = request.sysroot.path
    output_dir = request.result_path.path.path

    # Build out the argument instances.
    build_target = controller_util.ParseBuildTarget(
        request.sysroot.build_target
    )
    chroot = controller_util.ParseChroot(request.chroot)
    # Sysroot.path needs to be the fully qualified path, including the chroot.
    full_sysroot_path = chroot.full_path(sysroot_path)
    sysroot = sysroot_lib.Sysroot(full_sysroot_path)

    # Check that the sysroot exists before we go on.
    if not sysroot.Exists():
        logging.warning("The sysroot does not exist.")
        return

    try:
        results = artifacts.BundleSimpleChromeArtifacts(
            chroot, sysroot, build_target, output_dir
        )
    except artifacts.Error as e:
        logging.warning(
            "Error %s raised in BundleSimpleChromeArtifacts: %s", type(e), e
        )
        return

    for file_name in results:
        response.artifacts.add(
            artifact_path=common_pb2.Path(
                path=file_name, location=common_pb2.Path.OUTSIDE
            )
        )


def _BundleVmFilesResponse(request, response, _config) -> None:
    """Add test vm files to a successful response."""
    response.artifacts.add().path = os.path.join(request.output_dir, "f1.tar")


@faux.success(_BundleVmFilesResponse)
@faux.empty_error
@validate.require("chroot.path", "test_results_dir", "output_dir")
@validate.exists("output_dir")
@validate.validation_complete
def BundleVmFiles(
    request: artifacts_pb2.BundleVmFilesRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> None:
    """Tar VM disk and memory files."""
    chroot = controller_util.ParseChroot(request.chroot)
    test_results_dir = request.test_results_dir
    output_dir = request.output_dir

    archives = artifacts.BundleVmFiles(chroot, test_results_dir, output_dir)
    for archive in archives:
        response.artifacts.add().path = archive


def _BundleGceTarballResponse(request, response, _config) -> None:
    """Add artifact tarball to a successful response."""
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=os.path.join(
                request.result_path.path.path, constants.TEST_IMAGE_GCE_TAR
            ),
            location=common_pb2.Path.OUTSIDE,
        )
    )


@faux.success(_BundleGceTarballResponse)
@faux.empty_error
@validate.require("build_target.name", "result_path.path.path")
@validate.exists("result_path.path.path")
@validate.validation_complete
def BundleGceTarball(
    request: artifacts_pb2.BundleRequest,
    response: artifacts_pb2.BundleResponse,
    _config: "api_config.ApiConfig",
) -> Optional[int]:
    """Bundle the test image into a tarball suitable for importing into GCE."""
    target = request.build_target.name
    output_dir = request.result_path.path.path
    image_dir = _GetImageDir(constants.SOURCE_ROOT, target)
    if image_dir is None:
        return None

    tarball = artifacts.BundleGceTarball(output_dir, image_dir)
    response.artifacts.add(
        artifact_path=common_pb2.Path(
            path=tarball, location=common_pb2.Path.OUTSIDE
        )
    )
