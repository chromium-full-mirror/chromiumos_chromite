# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Payload API Service."""

from typing import Dict, Tuple, TYPE_CHECKING, Union

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import payload_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import cros_build_lib
from chromite.lib.paygen import paygen_payload_lib
from chromite.service import payload


if TYPE_CHECKING:
    from chromite.api import api_config

_VALID_IMAGE_PAIRS = (
    ("src_signed_image", "tgt_signed_image"),
    ("src_unsigned_image", "tgt_unsigned_image"),
    ("src_dlc_image", "tgt_dlc_image"),
    ("full_update", "tgt_unsigned_image"),
    ("full_update", "tgt_signed_image"),
    ("full_update", "tgt_dlc_image"),
)
_VALID_MINIOS_PAIRS = (
    ("src_signed_image", "tgt_signed_image"),
    ("src_unsigned_image", "tgt_unsigned_image"),
    ("full_update", "tgt_unsigned_image"),
    ("full_update", "tgt_signed_image"),
)

# TODO: Remove to use the standard cache directory if possible, otherwise
#  document why it cannot be used and preferably move outside of the repo.
_DEFAULT_PAYGEN_CACHE_DIR = ".paygen_cache"


def _ValidateImages(
    request: Union[
        payload_pb2.GenerationRequest,
        payload_pb2.GenerateUnsignedPayloadRequest,
        payload_pb2.FinalizePayloadRequest,
    ]
) -> Tuple[
    Union[
        payload_pb2.UnsignedImage,
        payload_pb2.SignedImage,
        payload_pb2.DLCImage,
    ],
    Union[
        payload_pb2.UnsignedImage,
        payload_pb2.SignedImage,
        payload_pb2.DLCImage,
    ],
]:
    """Validate src and tgt image fields.

    Args:
        request: The BAPI input proto.

    Returns:
        Tuple of src_image, tgt_image.
    """

    # Resolve the tgt image oneof.
    tgt_name = request.WhichOneof("tgt_image_oneof")
    try:
        tgt_image = getattr(request, tgt_name)
    except AttributeError:
        cros_build_lib.Die("%s is not a known tgt image type", tgt_name)

    # Resolve the src image oneof.
    src_name = request.WhichOneof("src_image_oneof")

    # If the source image is 'full_update' we lack a source entirely.
    if src_name == "full_update":
        src_image = None
    # Otherwise we have an image.
    else:
        try:
            src_image = getattr(request, src_name)
        except AttributeError:
            cros_build_lib.Die("%s is not a known src image type", src_name)

    # Ensure they are compatible oneofs.
    if (src_name, tgt_name) not in _VALID_IMAGE_PAIRS:
        cros_build_lib.Die(
            "%s and %s are not valid image pairs", src_image, tgt_image
        )

    # Ensure that miniOS payloads are only requested for compatible image types.
    if request.minios and (src_name, tgt_name) not in _VALID_MINIOS_PAIRS:
        cros_build_lib.Die(
            "%s and %s are not valid image pairs for miniOS",
            src_image,
            tgt_image,
        )

    return src_image, tgt_image


# We have more fields we might validate however, they're either
# 'oneof' or allowed to be the empty value by design. If @validate
# gets more complex in the future we can add more here.
@faux.empty_success
@faux.empty_completed_unsuccessfully_error
@validate.require("bucket")
def GeneratePayload(
    request: payload_pb2.GenerationRequest,
    response: payload_pb2.GenerationResponse,
    config: "api_config.ApiConfig",
) -> int:
    """Generate a update payload ('do paygen').

    Args:
        request: Input proto.
        response: Output proto.
        config: The API call config.

    Returns:
        A controller return code (e.g. controller.RETURN_CODE_SUCCESS).
    """
    src_image, tgt_image = _ValidateImages(request)

    if request.use_local_signing:
        cros_build_lib.Die("local signing not supported for this endpoint")

    # Find the value of bucket or default to 'chromeos-releases'.
    destination_bucket = request.bucket or "chromeos-releases"

    chroot = controller_util.ParseChroot(request.chroot)

    # There's a potential that some paygen_lib library might raise here, but
    # since we're still involved in config we'll keep it before the
    # validate_only.
    payload_config = payload.PayloadConfig(
        chroot,
        tgt_image,
        src_image,
        destination_bucket,
        request.minios,
        request.verify,
        upload=not request.dryrun,
        cache_dir=_DEFAULT_PAYGEN_CACHE_DIR,
    )

    # If configured for validation only we're done here.
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    # Do payload generation.
    artifacts = {}
    try:
        unsigned_payloads = payload_config.GenerateUnsignedPayload()
        artifacts = payload_config.FinalizePayload(unsigned_payloads.values())
    except paygen_payload_lib.PayloadGenerationSkippedException as e:
        # If paygen was skipped, provide a reason if possible.
        if isinstance(e, paygen_payload_lib.MiniOSException):
            reason = e.return_code()
            response.failure_reason = reason

    _SetGeneratePayloadOutputProto(response, artifacts)
    if _SuccessfulPaygen(artifacts, request.dryrun):
        return controller.RETURN_CODE_SUCCESS
    elif response.failure_reason:
        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
    else:
        return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY


def _SuccessfulPaygen(
    artifacts: Dict[int, Tuple[str, str]], dryrun: bool
) -> bool:
    """Check to see if the payload generation was successful.

    Args:
        artifacts: a dict containing an artifact tuple keyed by its
            version. Artifacts tuple is (local_path, remote_uri).
        dryrun: whether or not this was a dry run job.
    """
    if not artifacts:
        return False
    for _, artifact in artifacts.items():
        if not (artifact[1] or dryrun and artifact[0]):
            return False
    return True


def _SetGeneratePayloadOutputProto(
    response: payload_pb2.GenerationResponse,
    artifacts: Dict[int, Tuple[str, str]],
) -> None:
    """Set the output proto with the results from the service class.

    Args:
        response: The output proto.
        artifacts: a dict containing an artifact tuple keyed by its
            version. Artifacts tuple is (local_path, remote_uri).
    """
    for version, artifact in artifacts.items():
        versioned_artifact = response.versioned_artifacts.add()
        versioned_artifact.version = version
        if artifact[0]:
            versioned_artifact.file_path.path = artifact[0]
            versioned_artifact.file_path.location = (
                common_pb2.Path.INSIDE
                if cros_build_lib.IsInsideChroot()
                else common_pb2.Path.OUTSIDE
            )
        versioned_artifact.remote_uri = artifact[1] or ""


# We have more fields we might validate however, they're either
# 'oneof' or allowed to be the empty value by design. If @validate
# gets more complex in the future we can add more here.
@faux.empty_success
@faux.empty_completed_unsuccessfully_error
def GenerateUnsignedPayload(
    request: payload_pb2.GenerateUnsignedPayloadRequest,
    response: payload_pb2.GenerateUnsignedPayloadResponse,
    config: "api_config.ApiConfig",
) -> int:
    """Generate an unsigned payload.

    Args:
        request: Input proto.
        response: Output proto.
        config: The API call config.

    Returns:
        A controller return code (e.g. controller.RETURN_CODE_SUCCESS).
    """
    src_image, tgt_image = _ValidateImages(request)

    chroot = controller_util.ParseChroot(request.chroot)

    # There's a potential that some paygen_lib library might raise here, but
    # since we're still involved in config we'll keep it before the
    # validate_only.
    payload_config = payload.PayloadConfig(
        chroot,
        tgt_image,
        src_image,
        minios=request.minios,
        verify=False,
        upload=False,
        cache_dir=_DEFAULT_PAYGEN_CACHE_DIR,
    )

    # If configured for validation only we're done here.
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    # Do payload generation.
    unsigned_payloads = None
    try:
        unsigned_payloads = payload_config.GenerateUnsignedPayload()
        response.unsigned_payloads.extend(unsigned_payloads.values())
    except paygen_payload_lib.PayloadGenerationSkippedException as e:
        # If paygen was skipped, provide a reason if possible.
        if isinstance(e, paygen_payload_lib.MiniOSException):
            reason = e.return_code()
            response.failure_reason = reason

    if _SuccessfulUnsignedPaygen(unsigned_payloads):
        return controller.RETURN_CODE_SUCCESS
    elif response.failure_reason:
        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
    else:
        return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY


def _SuccessfulUnsignedPaygen(
    unsigned_payloads: Dict[int, payload_pb2.UnsignedPayload]
) -> bool:
    """Check to see if the payload generation was successful.

    Args:
        unsigned_payloads: a dict containing an UnsignedPayload keyed by its
            version.
        dryrun: whether or not this was a dry run job.
    """
    if not unsigned_payloads:
        return False
    for unsigned_payload in unsigned_payloads.values():
        if (
            not unsigned_payload.payload_file_path.path
            or not unsigned_payload.partition_names
            or not unsigned_payload.tgt_partitions
        ):
            return False
    return True


@faux.empty_success
@faux.empty_completed_unsuccessfully_error
@validate.require("payloads")
def FinalizePayload(
    request: payload_pb2.FinalizePayloadRequest,
    response: payload_pb2.FinalizePayloadResponse,
    config: "api_config.ApiConfig",
) -> int:
    """Sign, verify, and upload an unsigned payload.

    Args:
        request: Input proto.
        response: Output proto.
        config: The API call config.

    Returns:
        A controller return code (e.g. controller.RETURN_CODE_SUCCESS).
    """
    src_image, tgt_image = _ValidateImages(request)

    if request.use_local_signing:
        if not request.docker_image:
            cros_build_lib.Die(
                "local signing enabled but no docker image specified"
            )
        if not request.keyset:
            cros_build_lib.Die("local signing enabled but no keyset specified")

    # Find the value of bucket or default to 'chromeos-releases'.
    destination_bucket = request.bucket or "chromeos-releases"

    chroot = controller_util.ParseChroot(request.chroot)

    local_signing_kwargs = {}
    if request.use_local_signing:
        local_signing_kwargs["use_local_signing"] = True
        local_signing_kwargs["signing_docker_image"] = request.docker_image
        local_signing_kwargs["keyset"] = request.keyset

    # There's a potential that some paygen_lib library might raise here, but
    # since we're still involved in config we'll keep it before the
    # validate_only.
    payload_config = payload.PayloadConfig(
        chroot,
        tgt_image=tgt_image,
        src_image=src_image,
        minios=request.minios,
        dest_bucket=destination_bucket,
        verify=request.verify,
        upload=not request.dryrun,
        cache_dir=_DEFAULT_PAYGEN_CACHE_DIR,
        **local_signing_kwargs,
    )

    # If configured for validation only we're done here.
    if config.validate_only:
        return controller.RETURN_CODE_VALID_INPUT

    # Finalize payloads.
    artifacts = payload_config.FinalizePayload(request.payloads)

    _SetGeneratePayloadOutputProto(response, artifacts)
    if _SuccessfulPaygen(artifacts, request.dryrun):
        return controller.RETURN_CODE_SUCCESS
    elif response.failure_reason:
        return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
    else:
        return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY
