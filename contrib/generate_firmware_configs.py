# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Pre-populate the firmware configs repo from a ChromeOS board.

This is a developer-convenience tool to pre-populate the directory for a board
in the chromeos/firmware-config repository using the data from an
existing ChromeOS board.
"""

import functools
import hashlib
import json
from pathlib import Path
from typing import List, Optional

from chromite.third_party.google.protobuf import text_format

from chromite.api.gen.chromiumos import firmware_config_pb2
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import gs
from chromite.lib import osutils


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-b",
        "--board",
        "--build-target",
        required=True,
        help="Build target name.",
    )
    parser.add_argument(
        "--output",
        type="dir_exists",
        default=constants.SOURCE_ROOT / "src" / "platform" / "firmware-config",
        help="Path to the firmware-config repository.",
    )
    return parser


def parse_arguments(argv: Optional[List[str]]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()
    return opts


def build_config(
    chroot: chroot_lib.Chroot, build_target: build_target_lib.BuildTarget
) -> Path:
    """Build the model configuration JSON and return the path to it."""
    chroot.run(
        [
            chroot.chroot_path(constants.CHROMITE_BIN_DIR / "setup_board"),
            "--board",
            build_target.name,
        ]
    )
    chroot.run(
        [
            build_target.get_command("emerge"),
            "-guj",
            "--deep",
            "--newuse",
            "chromeos-base/chromeos-config",
        ]
    )
    return Path(
        chroot.full_path(
            Path(build_target.root)
            / "usr"
            / "share"
            / "chromeos-config"
            / "yaml"
            / "config.yaml"
        )
    )


def get_configs_by_model(config):
    """Transform a chromeos-config JSON into per-model configs."""
    result = {}
    for model_config in config["chromeos"]["configs"]:
        if "firmware" not in model_config:
            continue
        if "firmware-signing" not in model_config:
            continue
        if "main-ro-image" not in model_config["firmware"]:
            continue
        if "ec-ro-image" not in model_config["firmware"]:
            continue
        result[model_config["firmware-signing"]["signature-id"]] = model_config
    return result


@functools.lru_cache(maxsize=None)
def sha256sum_gs_uri(gs_context: gs.GSContext, gs_uri: str) -> str:
    """sha256 hash the contents of a gs:// URI."""
    with osutils.TempDir() as tmp_dir:
        output_file = Path(tmp_dir) / "download"
        gs_context.Copy(gs_uri, output_file)
        file_contents = output_file.read_bytes()
    return hashlib.sha256(file_contents).hexdigest()


def load_bcs(
    gs_context: gs.GSContext, bcs_overlay: str, bcs_uri: Optional[str]
) -> Optional[firmware_config_pb2.FirmwareVersion]:
    """Load a file from a BCS uri and return the FirmwareVersion for it."""
    if not bcs_uri:
        return None
    bcs_name = bcs_overlay.removeprefix("overlay-")
    ebuild_name = bcs_name.split("-")[0]
    file_name = bcs_uri.removeprefix("bcs://")
    gs_uri = (
        f"gs://chromeos-binaries/HOME/bcs-{bcs_name}/{bcs_overlay}/"
        f"chromeos-base/chromeos-firmware-{ebuild_name}/{file_name}"
    )
    return firmware_config_pb2.FirmwareVersion(
        uri=gs_uri,
        sha256=sha256sum_gs_uri(gs_context, gs_uri),
    )


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    opts = parse_arguments(argv)

    output_dir = opts.output / opts.board
    output_dir.mkdir(parents=True, exist_ok=True)

    chroot = chroot_lib.Chroot()
    gs_context = gs.GSContext()

    build_target = build_target_lib.BuildTarget(opts.board)
    config_path = build_config(chroot, build_target)
    with config_path.open(encoding="utf-8") as f:
        cros_config = json.load(f)

    configs_by_model = get_configs_by_model(cros_config)
    for model_name, config in configs_by_model.items():
        bcs_overlay = config["firmware"]["bcs-overlay"]
        ap_ro_image = config["firmware"]["main-ro-image"]
        ap_rw_image = config["firmware"].get("main-rw-image")
        ec_ro_image = config["firmware"]["ec-ro-image"]
        ec_rw_image = config["firmware"].get("ec-rw-image")
        message = firmware_config_pb2.FirmwareConfigForModel(
            model=model_name,
            signing=firmware_config_pb2.ModelSigningConfig(
                key_id=config["firmware-signing"]["key-id"],
                brand_code=config["brand-code"],
            ),
            ap_firmware=firmware_config_pb2.FirmwareConfig(
                ro_firmware=load_bcs(gs_context, bcs_overlay, ap_ro_image),
                rw_firmware=load_bcs(gs_context, bcs_overlay, ap_rw_image),
            ),
            ec_firmware=firmware_config_pb2.FirmwareConfig(
                ro_firmware=load_bcs(gs_context, bcs_overlay, ec_ro_image),
                rw_firmware=load_bcs(gs_context, bcs_overlay, ec_rw_image),
            ),
        )

        output_path = output_dir / f"{model_name}.txtpb"
        output_path.write_text(
            text_format.MessageToString(message), encoding="utf-8"
        )
