# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Signing controller."""

from chromite.api import faux
from chromite.api import validate
from chromite.service import image


@faux.all_empty
@validate.require("docker_image")
@validate.require("build_target.name")
@validate.exists("release_keys_checkout")
@validate.validation_complete
def CreatePreMPKeys(request, _response, _config) -> None:
    """Generate PreMPKeys for the specified build target."""
    entrypoint_args = []
    if request.dry_run:
        entrypoint_args.append("--dev")
    entrypoint_args.append(request.build_target.name)
    entrypoint_script = "./create_premp.sh"
    if request.add_loem:
        entrypoint_script = "./add_loem.py"

    image.CallDocker(
        request.docker_image,
        docker_args=[
            # Mount the keyset checkout as a volume.
            "-v",
            f"{request.release_keys_checkout}:/keys",
            "--entrypoint",
            entrypoint_script,
        ],
        entrypoint_args=entrypoint_args,
    )


@faux.all_empty
@validate.require("docker_image")
@validate.require("accessory")
@validate.exists("release_keys_checkout")
@validate.validation_complete
def CreateAccessoryKeys(request, _response, _config) -> None:
    """Generate Accessory keys for the specified build target."""
    entrypoint_args = [
        "-a",
        request.accessory,
    ]
    if request.build_target and request.build_target.name:
        entrypoint_args.extend(["-b", request.build_target.name])
    if request.is_pre_mp:
        entrypoint_args.append("--pre-mp")
    if request.version:
        entrypoint_args.extend(["-kv", str(request.version)])
    if request.dry_run:
        entrypoint_args.append("--dry-run")
    if request.is_staging:
        entrypoint_args.append("--dev")
    entrypoint_script = "./generate_accessory_keys.py"

    image.CallDocker(
        request.docker_image,
        docker_args=[
            # Mount the keyset checkout as a volume.
            "-v",
            f"{request.release_keys_checkout}:/keys",
            "--entrypoint",
            entrypoint_script,
        ],
        entrypoint_args=entrypoint_args,
    )


@faux.all_empty
@validate.require("project")
@validate.require("location")
@validate.require("keyring")
@validate.require("key")
@validate.require("version")
@validate.require("filename")
@validate.require("docker_image")
@validate.validation_complete
def SignTi50Paos(request, _response, _config) -> None:
    """Signs PAOs inside the provided file."""

    image.CallDocker(
        request.docker_image,
        docker_args=[
            # Mount the archive dir as a volume.
            "-v",
            f"{request.archive_dir}:/in",
            # Mount the output dir as a volume.
            "-v",
            f"{request.result_path.path.path}:/out",
            # Mount a tmp dir for docker as a volume.
            # Needed to avoid filling up our small boot partition.
            "-v",
            f"{request.tmp_path}:/tmp",
            "--entrypoint",
            "./ti50_pao_generate.sh",
        ],
        entrypoint_args=[
            request.project,
            request.location,
            request.keyring,
            request.key,
            str(request.version),
            f"/in/{request.filename}",
            f"/out/{request.filename}",
        ],
    )


@faux.all_empty
@validate.require("docker_image")
@validate.require("keyring")
@validate.require("key_name")
@validate.require("out_path")
@validate.exists("release_keys_checkout")
@validate.validation_complete
def CreateCert(request, _response, _config) -> None:
    """Generate cert keys for the specified key."""
    entrypoint_args = [
        "--keyring",
        request.keyring,
        "--key-name",
        request.key_name,
        "--out-location",
        request.out_path,
    ]

    if request.dry_run:
        entrypoint_args.append("--dry-run")
    if request.is_staging:
        entrypoint_args.append("--dev")
    entrypoint_script = "./create_cert.py"

    image.CallDocker(
        request.docker_image,
        docker_args=[
            # Mount the keyset checkout as a volume.
            "-v",
            f"{request.release_keys_checkout}:/keys",
            # Mount the output dir as a volume.
            "-v",
            f"{request.result_path.path.path}:/out",
            "--entrypoint",
            entrypoint_script,
        ],
        entrypoint_args=entrypoint_args,
    )


@faux.all_empty
@validate.require("docker_image")
@validate.validation_complete
def SignViaOnlineHsm(request, _response, _config) -> None:
    """Sign an artifact via the online HSM."""
    image.CallDocker(
        request.docker_image,
        docker_args=[
            "--entrypoint",
            "./sign_with_hsm.sh",
        ],
        entrypoint_args=["test"],
    )


@faux.all_empty
@validate.require("docker_image")
@validate.require("keyset_name")
@validate.exists("release_keys_checkout")
@validate.validation_complete
def CreateKeysHsm(request, response, _config) -> None:
    """Request key creation from the online HSM."""
    entrypoint_args = [
        "--keyset-name",
        request.keyset_name,
        "--keyset-repo",
        "/keys",
        "-o",
        "/out",
        "-p",
        "out_proto.bin",
    ]
    if request.dry_run:
        entrypoint_args.append("--mocks")

    # Exporter dry-run defaults to request.dry_run unless explicitly overridden.
    exporter_dry_run = request.dry_run
    if request.HasField("exporter_dry_run"):
        exporter_dry_run = request.exporter_dry_run

    if exporter_dry_run:
        entrypoint_args.append("--exporter-dry-run")

    response_bytes = image.CallDockerWithResponse(
        request.docker_image,
        docker_args=[
            # Mount the keyset checkout as a volume.
            "-v",
            f"{request.release_keys_checkout}:/keys",
            "--entrypoint",
            "./create_keys_with_hsm.py",
        ],
        entrypoint_args=entrypoint_args,
        output_file_name="out_proto.bin",
    )

    if response_bytes is None:
        raise ValueError(
            "No response proto found from signing container. "
            "Please check docker output for errors."
        )

    response.ParseFromString(response_bytes)
