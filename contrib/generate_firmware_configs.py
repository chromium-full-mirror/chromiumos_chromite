# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Generate and update the firmware configs repo from a ChromeOS board.

This is a developer-convenience tool to manage the directory for a board
in the chromeos/firmware-config repository using the data from an
existing ChromeOS board.

Convert from cros config. All version are from cros config by default.
./generate_firmware_configs -b corsola

Update EC version from cros config and preserve AP version.
./generate_firmware_configs -b corsola \\
    --ap-ro-version old_txtpb --ap-rw-version old_txtpb

Update AP version to 15194.225.185 and preserve EC version.
./generate_firmware_configs -b corsola \\
    --ap-ro-version 15194.225.185 --ap-rw-version "" \\
    --ec-ro-version old_txtpb --ec-rw-version old_txtpb

Update EC version to 16660.0.0 and preserve AP version.
./generate_firmware_configs -b rauru --model navi --no-build \\
    --ap-ro-version old_txtpb --ap-rw-version old_txtpb \\
    --ec-ro-version 16660.0.0 --ec-rw-version 16660.0.0 \\
    --ec-tot-build-id=118396-8683328236611256305
"""

from collections.abc import Callable
import enum
import functools
import hashlib
import json
import logging
from pathlib import Path
from typing import List, Optional

from chromite.third_party.google.protobuf import text_format

from chromite.api.gen.chromiumos import firmware_config_pb2
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import gs
from chromite.lib import parallel
from chromite.utils import gs_urls_util


CROS_CONFIG = "cros_config"
OLD_TXTPB = "old_txtpb"


class EcBranchType(enum.Enum):
    """The type of branches where EC version is pinned on."""

    # The pinned EC version is pinned on firmware branch.
    FIRMWARE = enum.auto()

    # The pinned EC version is pinned on release branch.
    RELEASE = enum.auto()


EC_BRANCH_CONFIG = {
    "brya": EcBranchType.FIRMWARE,
    "corsola": EcBranchType.FIRMWARE,
    "geralt": EcBranchType.FIRMWARE,
    "nissa": EcBranchType.FIRMWARE,
    "rauru": EcBranchType.FIRMWARE,
    "fatcat": EcBranchType.FIRMWARE,
    "ocelot": EcBranchType.FIRMWARE,
    "tanjiro": EcBranchType.FIRMWARE,
}


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__, jobs=True)
    parser.add_argument(
        "-b",
        "--board",
        "--build-target",
        required=True,
        help='Build target name. "brya" is still use old firmware branch. '
        "The rest of boards use new firmware branch.",
    )
    parser.add_argument(
        "--model",
        action="split_extend",
        default=[],
        help="Full model name including custom label name. "
        "Space-separated list and/or pass multiple times. "
        "If specified, only update the given models.",
    )
    parser.add_argument(
        "--ignore-models",
        action="split_extend",
        default=[],
        help="Ignore these device models while updating. "
        "Space-separated list and/or pass multiple times.",
    )
    parser.add_bool_argument(
        "--build",
        True,
        "Build chromeos-config",
        "Do not build chromeos-config",
    )
    parser.add_argument(
        "--edit-board-config",
        action="store_true",
        help="Update configs in the board directory instead of the model "
        "directory.",
    )
    parser.add_argument(
        "--fix-sha",
        action="store_true",
        help="Fix the sha256 for FirmwareVersion from the old textproto "
        "config.  Only download the firmware and update the sha256 without "
        "modifying other fields in the output .txtpb files.",
    )
    parser.add_argument(
        "--tot-build-id",
        type=str,
        default="",
        metavar="SUFFIX-ID",
        help="This is FALLBACK when the branched builder fails. Specifies the "
        "artifact from the main branch postsubmit builder. Format: 6 digit "
        "suffix - 19 digit build ID (e.g., 123456-1234567890123456789). "
        "All specified versions have to be the same version.",
    )
    parser.add_argument(
        "--ap-ro-version",
        type=str,
        default=CROS_CONFIG,
        help="The version of AP RO FW. "
        "cros_config: from cros_config. "
        "old_txtpb: from old txtpb. "
        '"": empty field. '
        "a.b.c: specify version.",
    )
    parser.add_argument(
        "--ap-rw-version",
        type=str,
        default=CROS_CONFIG,
        help="The version of AP RW FW. "
        "cros_config: from cros_config. "
        "old_txtpb: from old txtpb. "
        '"": empty field. '
        "a.b.c: specify version.",
    )
    parser.add_argument(
        "--ec-tot-build-id",
        type=str,
        default="",
        metavar="SUFFIX-ID",
        help="Specifies the artifact from the main branch Zephyr postsubmit "
        "builder. Format: 6 digit suffix - 19 digit build ID "
        "(e.g., 123456-1234567890123456789). All specified versions have to "
        "be the same version.",
    )
    parser.add_argument(
        "--ec-ro-version",
        type=str,
        default=CROS_CONFIG,
        help="The version of EC RO FW. "
        "cros_config: from cros_config. "
        "old_txtpb: from old txtpb. "
        '"": empty field. '
        "a.b.c: specify version.",
    )
    parser.add_argument(
        "--ec-rw-version",
        type=str,
        default=CROS_CONFIG,
        help="The version of EC RW FW. "
        "cros_config: from cros_config. "
        "old_txtpb: from old txtpb. "
        '"": empty field. '
        "a.b.c: specify version.",
    )
    return parser


def verify_version_number(
    parser: commandline.ArgumentParser, version: str
) -> None:
    """Verify the version number is a valid cros version."""
    numbers = version.split(".")
    if len(numbers) != 3:
        parser.error(
            "The version should be three numbers concatenated "
            "with decimal point."
        )
    if not all(x.isdecimal() for x in numbers):
        parser.error(
            "The version should be three numbers concatenated "
            "with decimal point."
        )


def parse_arguments(argv: Optional[List[str]]) -> commandline.ArgumentNamespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.freeze()

    if not opts.ap_ro_version in (CROS_CONFIG, OLD_TXTPB, ""):
        verify_version_number(parser, opts.ap_ro_version)
    if not opts.ap_rw_version in (CROS_CONFIG, OLD_TXTPB, ""):
        verify_version_number(parser, opts.ap_rw_version)
    if not opts.ec_ro_version in (CROS_CONFIG, OLD_TXTPB, ""):
        verify_version_number(parser, opts.ec_ro_version)
    if not opts.ec_rw_version in (CROS_CONFIG, OLD_TXTPB, ""):
        verify_version_number(parser, opts.ec_rw_version)
    return opts


def build_config(
    chroot: chroot_lib.Chroot, build_target: build_target_lib.BuildTarget
) -> None:
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


def get_configs_by_model(config: dict) -> dict:
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
def sha256sum_gs_uri(ctx: gs.GSContext, gs_uri: str) -> str:
    """sha256 hash the contents of a gs:// URI."""
    file_contents = ctx.Cat(gs_uri)
    return hashlib.sha256(file_contents).hexdigest()


def get_firmware_version(
    ctx: gs.GSContext, gs_uri: Optional[str]
) -> Optional[firmware_config_pb2.FirmwareVersion]:
    """Download the firmware from uri and return the FirmwareVersion for it."""
    if not gs_uri:
        return None
    resolved_gs_uri = ctx.List(gs_uri)
    assert (
        len(resolved_gs_uri) == 1
    ), f"{gs_uri} is ambiguous. Found {resolved_gs_uri}"
    gs_uri = resolved_gs_uri[0].url
    return firmware_config_pb2.FirmwareVersion(
        uri=gs_uri,
        sha256=sha256sum_gs_uri(ctx, gs_uri),
    )


def get_firmware_image_archive_uri(
    board: str,
    tot_build_id: Optional[str],
    ec_tot_build_id: Optional[str],
    model: str,
    version: str,
) -> str:
    """Get firmware image archive URI."""
    branch_point = version.rsplit(".", maxsplit=1)[0]
    version_folder = version
    if board == "brya":
        bucket = "firmware-image-archive"
        branch = "firmware-android-brya-14505.885.B"
    else:
        if tot_build_id:
            bucket = "chromeos-image-archive"
            branch = "firmware-android-postsubmit"
            version_folder = f"R*-{version}-{tot_build_id}"
        elif ec_tot_build_id:
            bucket = "chromeos-image-archive"
            branch = "firmware-zephyr-postsubmit"
            version_folder = f"R*-{version}-{ec_tot_build_id}"
        else:
            bucket = "firmware-image-archive"
            branch = f"firmware-android-R*-{branch_point}.B"
    gs_uri = (
        f"gs://{bucket}/{branch}/{version_folder}/{model}.{version}.tar.bz2"
    )
    return gs_uri


def get_bcs_uri(bcs_overlay: str, bcs_uri: Optional[str]) -> Optional[str]:
    """Get GS URI from BCS URI."""
    if not bcs_uri:
        return None
    if gs_urls_util.PathIsGs(bcs_uri):
        return bcs_uri
    if not bcs_uri.startswith("bcs://"):
        cros_build_lib.die(
            f"Invalid uri, must start with gs:// or bcs://, was {bcs_uri}"
        )
    bcs_name = bcs_overlay.removeprefix("overlay-")
    ebuild_name = bcs_name.split("-")[0]
    file_name = bcs_uri.removeprefix("bcs://")
    gs_uri = (
        f"gs://chromeos-binaries/HOME/bcs-{bcs_name}/{bcs_overlay}/"
        f"chromeos-base/chromeos-firmware-{ebuild_name}/{file_name}"
    )
    return gs_uri


def get_cros_config_dict(board: str, build: bool) -> dict:
    """Get the firmware config from the full cros config."""
    chroot = chroot_lib.Chroot()
    build_target = build_target_lib.BuildTarget(board)
    if build:
        build_config(chroot, build_target)
    cros_config_path = Path(
        chroot.full_path(
            Path(build_target.root)
            / "usr"
            / "share"
            / "chromeos-config"
            / "yaml"
            / "config.yaml"
        )
    )
    with cros_config_path.open(encoding="utf-8") as f:
        cros_config = json.load(f)

    configs_by_model = get_configs_by_model(cros_config)
    if not board in EC_BRANCH_CONFIG:
        cros_build_lib.die(
            f"No config for {board}. "
            "Can't determine the source of ec branch."
        )
    ec_branch = EC_BRANCH_CONFIG[board]

    cros_config_dict = {}
    for model_name, config in configs_by_model.items():
        bcs_overlay = config["firmware"]["bcs-overlay"]
        ap_ro_image = config["firmware"]["main-ro-image"]
        ap_rw_image = config["firmware"].get("main-rw-image")
        ec_ro_image = config["firmware"]["ec-ro-image"]
        ec_rw_image = config["firmware"].get("ec-rw-image")

        ap_firmware_for_ec = None
        if not ec_rw_image:
            # We always specify EC_RW in txtpb.
            if ec_branch == EcBranchType.RELEASE:
                # In cros config, AP is always from the firmware branch .
                # EC and AP are from different branches.
                # We can only insert Zephyr EC from EC binary to AP. Since only
                # platforms using Zephyr EC use EC from release branch. This
                # isn't an issue.
                ec_rw_image = ec_rw_image or ec_ro_image
            elif ec_branch == EcBranchType.FIRMWARE:
                # EC and AP are from the same branch.
                ap_firmware_for_ec = ap_rw_image or ap_ro_image

        model_dict = {
            "model": model_name,
            "signing": {
                "key_id": config["firmware-signing"]["key-id"],
                "brand_code": config["brand-code"],
            },
            "ap_firmware": {
                "ro_firmware": get_bcs_uri(bcs_overlay, ap_ro_image),
                "rw_firmware": get_bcs_uri(bcs_overlay, ap_rw_image),
            },
            "ec_firmware": {
                "ro_firmware": get_bcs_uri(bcs_overlay, ec_ro_image),
                "rw_firmware": get_bcs_uri(bcs_overlay, ec_rw_image),
            },
            "ap_firmware_for_ec_rw": get_bcs_uri(
                bcs_overlay, ap_firmware_for_ec
            ),
        }
        cros_config_dict[model_name] = model_dict
    return cros_config_dict


def get_firmware_version_from_option(
    ctx: gs.GSContext,
    option_value: Optional[str],
    cros_uri: str,
    fix_sha: bool,
    old_firmware: Optional[firmware_config_pb2.FirmwareVersion],
    get_version_uri: Optional[Callable],
) -> Optional[firmware_config_pb2.FirmwareVersion]:
    """Retrieves a FirmwareVersion object based on the provided option value.

    Args:
        ctx: GSContext for Google Storage operations.
        option_value: Source of the firmware version:
            'CROS_CONFIG': Use URI from 'cros_uri'.
            'OLD_TXTPB'  : Use FirmwareVersion from the 'old_firmware'.
                           Use only URI if fix_sha.
            ''           : Returns None.
            Otherwise    : Version string -> get_version_uri -> URI.
        cros_uri: URI from CrOS config.
        fix_sha: Fetch from old_firmware.uri if True and
            option_value is 'OLD_TXTPB'.
        old_firmware: Existing FirmwareVersion from textproto config.
        get_version_uri: Callable to get URI from Version string.

    Returns:
        FirmwareVersion or None if:
            'option_value' is 'CROS_CONFIG' and 'cros_uri' is None.
            'option_value' is 'OLD_TXTPB' and 'old_firmware' is None or has
              no URI.
            'option_value' is ''.

    Raises:
        cros_build_lib.die: If 'option_value' is not 'CROS_CONFIG', 'OLD_TXTPB',
            or '', and 'get_version_uri' is None.
    """

    if option_value == CROS_CONFIG:
        return get_firmware_version(ctx, cros_uri)
    if option_value == OLD_TXTPB:
        if old_firmware.uri:
            if fix_sha:
                return get_firmware_version(ctx, old_firmware.uri)
            return old_firmware
        return None
    if option_value == "":
        return None
    if not get_version_uri:
        cros_build_lib.die("Can't get the version URI.")
    version = option_value
    gs_uri = get_version_uri(version)
    return get_firmware_version(ctx, gs_uri)


def process_model(
    model: str,
    cros_config_dict: dict,
    opts: commandline.ArgumentNamespace,
    config_path: Path,
    ctx: gs.GSContext,
) -> None:
    """Process a model."""
    if config_path.exists():
        old_message = text_format.Parse(
            config_path.read_text(),
            firmware_config_pb2.FirmwareConfigForModel(),
        )
    elif OLD_TXTPB in (
        opts.ap_ro_version,
        opts.ap_rw_version,
        opts.ec_ro_version,
        opts.ec_rw_version,
    ):
        cros_build_lib.die(
            f"Trying to copy from old config but {model} doesn't have "
            "config yet."
        )
    else:
        old_message = firmware_config_pb2.FirmwareConfigForModel()

    # TODO get the old image name. The image name is the same between
    # old branch and new branch.

    # Getting the AP build target.  Assume the AP build target is same.

    # chromeos-binaries (BCS):
    # .../chromeos-firmware-brya/Anahera.14505.586.0.tbz2
    # firmware-image-archive:
    # .../14505.782.118/anahera.14505.782.118.tar.bz2
    #
    # We want to construct gs_uri in firmware-image-archive so make it
    # lower case.
    old_uri = cros_config_dict[model]["ap_firmware"]["ro_firmware"]
    ap_image_name = old_uri.split("/")[-1].split(".")[0].lower()

    if opts.board == "brya":
        get_ap_uri = functools.partial(
            get_firmware_image_archive_uri,
            opts.board,
            None,
            None,
            ap_image_name,
        )
        get_ec_uri = functools.partial(
            get_firmware_image_archive_uri,
            opts.board,
            None,
            None,
            ap_image_name + ".EC",
        )
    else:
        get_ap_uri = functools.partial(
            get_firmware_image_archive_uri,
            opts.board,
            opts.tot_build_id,
            None,
            ap_image_name,
        )
        get_ec_uri = functools.partial(
            get_firmware_image_archive_uri,
            opts.board,
            None,
            opts.ec_tot_build_id,
            ap_image_name + ".EC",
        )

    ap_ro_firmware = get_firmware_version_from_option(
        ctx,
        opts.ap_ro_version,
        cros_config_dict[model]["ap_firmware"]["ro_firmware"],
        opts.fix_sha,
        old_message.ap_firmware.ro_firmware,
        get_ap_uri,
    )
    ap_rw_firmware = get_firmware_version_from_option(
        ctx,
        opts.ap_rw_version,
        cros_config_dict[model]["ap_firmware"]["rw_firmware"],
        opts.fix_sha,
        old_message.ap_firmware.rw_firmware,
        get_ap_uri,
    )
    ap_firmware = firmware_config_pb2.FirmwareConfig(
        ro_firmware=ap_ro_firmware,
        rw_firmware=ap_rw_firmware,
    )

    ec_ro_firmware = get_firmware_version_from_option(
        ctx,
        opts.ec_ro_version,
        cros_config_dict[model]["ec_firmware"]["ro_firmware"],
        opts.fix_sha,
        old_message.ec_firmware.ro_firmware,
        get_ec_uri,
    )
    ec_rw_firmware = get_firmware_version_from_option(
        ctx,
        opts.ec_rw_version,
        cros_config_dict[model]["ec_firmware"]["rw_firmware"],
        opts.fix_sha,
        old_message.ec_firmware.rw_firmware,
        get_ec_uri,
    )
    ec_firmware = firmware_config_pb2.FirmwareConfig(
        ro_firmware=ec_ro_firmware,
        rw_firmware=ec_rw_firmware,
    )

    ap_firmware_for_ec_rw = get_firmware_version_from_option(
        ctx,
        (
            opts.ec_rw_version
            if opts.ec_rw_version in (CROS_CONFIG, OLD_TXTPB)
            else ""
        ),
        cros_config_dict[model]["ap_firmware_for_ec_rw"],
        opts.fix_sha,
        old_message.ap_firmware_for_ec_rw,
        get_ap_uri,
    )

    message = firmware_config_pb2.FirmwareConfigForModel(
        model=model,
        signing=firmware_config_pb2.ModelSigningConfig(
            key_id=cros_config_dict[model]["signing"]["key_id"],
            brand_code=cros_config_dict[model]["signing"]["brand_code"],
        ),
        ap_firmware=ap_firmware,
        ec_firmware=ec_firmware,
        ap_firmware_for_ec_rw=ap_firmware_for_ec_rw,
    )

    config_path.write_text(
        text_format.MessageToString(message), encoding="utf-8"
    )


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    opts = parse_arguments(argv)

    firmware_config_repo = (
        constants.SOURCE_ROOT / "src" / "platform" / "firmware-config"
    )

    cros_config_dict = get_cros_config_dict(opts.board, opts.build)

    target_models = []
    if opts.model:
        target_models.extend(opts.model)
    else:
        target_models.extend(cros_config_dict.keys())

    # Remove the following to build only device model specified?
    target_models = [x for x in target_models if x not in opts.ignore_models]

    ctx = gs.GSContext()

    if opts.edit_board_config:
        board_config_dir = firmware_config_repo / opts.board
        board_config_dir.mkdir(parents=True, exist_ok=True)

    possible_prefix = [str(p.name) for p in firmware_config_repo.iterdir()]
    possible_prefix.sort(reverse=True)
    funcs = []
    for model in target_models:
        if opts.edit_board_config:
            config_dir = board_config_dir
        else:
            dir_path = model
            for prefix in possible_prefix:
                if dir_path.startswith(prefix):
                    if dir_path != prefix:
                        logging.info("Update %s in %s/.", dir_path, prefix)
                        dir_path = prefix
                    break
            config_dir = firmware_config_repo / dir_path
            config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / f"{model}.txtpb"
        func = functools.partial(
            process_model, model, cros_config_dict, opts, config_path, ctx
        )
        funcs.append(func)
    parallel.RunParallelSteps(funcs, max_parallel=opts.jobs, halt_on_error=True)
