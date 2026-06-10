# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Entry point script for TBI builders.

This is intended to be run from the chromite root directory on builders,
so it will do things that may be suboptimal in a dev environment, like
writing files to arbitrary locations.
"""

import json
import logging
import os
import pwd
import shutil
import subprocess
from typing import Any, List, Optional

from chromite.third_party.google.protobuf import json_format

from chromite.api.gen.chromite.api import sdk_pb2
from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.utils import os_util


# A shorter name for some very long proto types
ARTIFACT_TYPE = common_pb2.ArtifactsByService.Firmware.ArtifactType


def get_parser() -> commandline.ArgumentParser:
    """Creates the argparse parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--location",
        type=int,
        required=True,
        # pylint: disable=line-too-long
        help="Firmware location enum (int). See https://chromium.googlesource.com/chromiumos/infra/proto/+/refs/heads/main/src/chromiumos/common.proto",
        # pylint: enable=line-too-long
    )
    parser.add_argument(
        "--targets",
        required=True,
        action="split_extend",
        help="Space-separated list of firmware target names.",
    )
    parser.add_argument(
        "-u",
        "--user",
        help="Drop privileges to this user if running as root.",
    )
    return parser


def _drop_to_user(user: str) -> None:
    """Chown parent directory and drop privileges to user."""
    try:
        pw = pwd.getpwnam(user)
    except KeyError:
        cros_build_lib.die("User %s not found", user)

    logging.info(
        "Chowning contents of %s to %s:%s",
        constants.SOURCE_ROOT,
        user,
        pw.pw_gid,
    )
    osutils.Chown(
        constants.SOURCE_ROOT, user=user, group=pw.pw_gid, recursive=True
    )

    logging.info(
        "Dropping privileges to %s (%s:%s)", user, pw.pw_uid, pw.pw_gid
    )
    os_util.switch_to_user(user, pw.pw_uid, pw.pw_gid, clear_saved_id=True)

    # Update environment
    os.environ["HOME"] = pw.pw_dir


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    parser = get_parser()
    opts = parser.parse_args(argv or [])

    if opts.user:
        os_util.assert_root_user()
        _drop_to_user(opts.user)

    chroot = common_pb2.Chroot()
    chroot.path = "cros_chroot"
    chroot.env.use_flags.append(common_pb2.UseFlag(flag="chrome_internal"))

    request = sdk_pb2.CreateRequest()
    request.chroot.CopyFrom(chroot)
    request.skip_chroot_upgrade = True
    ret = _run_build_api(
        "chromite.api.SdkService/Create",
        json_format.MessageToDict(request),
        input_file="input_sdk.json",
        output_file="output_sdk.json",
    )
    if ret != 0:
        return ret

    # pylint: disable=line-too-long
    # proto-file: https://chromium.googlesource.com/chromiumos/infra/proto/+/refs/heads/main/src/chromite/api/firmware.proto
    # proto-message: BuildAllFirmwareRequest
    # pylint: enable=line-too-long
    request = {
        "chroot": json_format.MessageToDict(chroot),
        "firmwareLocation": opts.location,
        "firmwareTargets": [{"name": t} for t in opts.targets],
    }
    ret = _run_build_api(
        "chromite.api.FirmwareService/BuildAllFirmware",
        request,
        input_file="input_build.json",
        output_file="output_build.json",
    )
    if ret != 0:
        return ret

    ret = _run_build_api(
        "chromite.api.FirmwareService/TestAllFirmware",
        request,
        input_file="input_test.json",
        output_file="output_test.json",
    )
    if ret != 0:
        return ret

    # pylint: disable=line-too-long
    # proto-file: https://chromium.googlesource.com/chromiumos/infra/proto/+/refs/heads/main/src/chromite/api/firmware.proto
    # proto-message: BundleFirmwareArtifactsRequest
    # pylint: enable=line-too-long
    request = {
        "chroot": json_format.MessageToDict(chroot),
        "artifacts": {
            "outputArtifacts": [
                {
                    "artifactTypes": [
                        ARTIFACT_TYPE.FIRMWARE_TARBALL,
                        ARTIFACT_TYPE.FIRMWARE_TARBALL_INFO,
                        ARTIFACT_TYPE.FIRMWARE_TOKEN_DATABASE,
                    ],
                    "location": opts.location,
                },
            ],
        },
        "firmwareLocation": opts.location,
        "firmwareTargets": [{"name": t} for t in opts.targets],
    }
    ret = _run_build_api(
        "chromite.api.FirmwareService/BundleFirmwareArtifacts",
        request,
        input_file="input_bundle.json",
        output_file="output_bundle.json",
    )
    if ret != 0:
        return ret

    with open("output_bundle.json", "r", encoding="utf-8") as f:
        bundle_data = json.load(f)

    artifact_dir = bundle_data["artifactDir"]["path"]
    output_dir = "tbi_build_output"

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Current dir is chromite in build environment
    out_root = os.path.abspath(os.path.join("..", "out"))

    for artifact_entry in bundle_data.get("artifacts", {}).get("artifacts", []):
        for path_entry in artifact_entry.get("paths", []):
            chroot_src_path = path_entry["path"]
            rel_path = os.path.relpath(chroot_src_path, artifact_dir)
            dest_path = os.path.join(output_dir, rel_path)
            outside_path = os.path.join(
                out_root, os.path.relpath(chroot_src_path, "/")
            )

            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            logging.info(
                "Copying artifact from %r to %r", outside_path, dest_path
            )
            shutil.copy2(outside_path, dest_path)

    return 0


def _run_build_api(
    method: str,
    request: Any,
    *,
    input_file: str = "input.json",
    output_file: str = "output.json",
) -> int:
    """Run a Build API method.

    Args:
        method: The Build API method to call.
        request: The request object to pass as input.
        input_file: Path to the input JSON file.
        output_file: Path to the output JSON file.

    Returns:
        The return code of the Build API call.
    """
    with open(input_file, "w", encoding="utf-8") as f:
        json.dump(request, f, indent=2)

    p = subprocess.run(
        [
            "bin/build_api",
            method,
            f"--input-json={input_file}",
            f"--output-json={output_file}",
        ],
        check=False,
    )
    return p.returncode
