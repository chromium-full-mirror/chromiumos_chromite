# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Main module for finding and retrieving firmware archives"""

import json
import logging
import os
from pathlib import Path
import re
import shutil
import textwrap
from typing import List, NamedTuple, Optional, Set

from chromite.lib import cros_build_lib
from chromite.lib import gs


class FwBuddyException(Exception):
    """Exception class used by this module."""


class Release(NamedTuple):
    """Tuple representation of a firmware release. e.g. R89-13606.459.0"""

    milestone: str
    major_version: str
    minor_version: str
    patch_number: str


class URI(NamedTuple):
    """All fwbuddy parameters in tuple form"""

    board: str
    model: str
    firmware_name: str
    version: str
    image_type: str
    firmware_type: Optional[str]


class FieldDoc(NamedTuple):
    """All of the information needed to generate URI field usage docs"""

    description: str
    examples: str
    required: bool
    strict: bool


class FwImage(NamedTuple):
    """All of the parameters that identify a unique firmware image"""

    board: str
    model: str
    firmware_name: str
    release: Release
    branches: Set[str]
    image_type: str
    firmware_type: Optional[str]


FWBUDDY_URI_SCHEMA = (
    "fwbuddy://<board>/<model>/<firmware-name>/<version>/<image-type>/"
    "<firmware-type>"
)

FIELD_DOCS = {
    "board": FieldDoc(
        description=(
            "A group of ChromeOS devices (models) that have similar hardware, "
            "but may vary in minor ways (e.g. screen size). ChromeOS system "
            "images are targeted to boards, and all models for a board need to "
            "be able to run the image for their respective boards."
        ),
        examples="dedede, octopus, brya, etc.",
        required=True,
        strict=False,
    ),
    "model": FieldDoc(
        description=(
            "A model generally refers to a ChromeOS device that is "
            "unique in the market. A model typically maintains the major "
            "hardware components of its parent board but may vary in minor "
            "elements of one or more of: physical design, OEM, or ODM"
        ),
        examples="galnat360, dood, redrix, etc.",
        required=True,
        strict=False,
    ),
    "firmware-name": FieldDoc(
        description=(
            "The name assigned to the firmware image used by a group of "
            "similar models. For example, Galnat, Galnat360, Galith all use "
            "the firmware image Galtic. In some situations, the firmware name "
            "may be identical to the model name (E.G. Dood), but this is not a "
            "guarantee. The firmware name for the device you're trying to "
            "flash can be found by running "
            "`chromeos-firmwareupdate --manifest` on it and looking for the "
            "version number for your model. For example, the manifest file on "
            "a Galnat360 indicates that the firmware version is "
            "`Google_Galtic.13606.459.0`, implying the firmware name is Galtic."
        ),
        examples="galtic, dood, redrix, etc.",
        required=True,
        strict=False,
    ),
    "version": FieldDoc(
        description=(
            "The version of firmware you're looking for. This could be either a"
            " pinned version or a specific release in the following format:"
            " R<MILESTONE>-<MAJOR_VERSION>.<MINOR_VERSION>.<PATCH_NUMBER>. If"
            " you don't know the milestone, you can replace it with a * and"
            " fwbuddy should be able to still find the right version."
        ),
        examples="{R99-123.456.0|R*-123.456.0}",
        required=True,
        strict=True,
    ),
    "image-type": FieldDoc(
        description=(
            "Whether the device is signed with production keys or dev keys. "
            "Signed firmware is what typically runs on consumer devices out in "
            "the real world. Unsigned firmware is what runs on most lab and "
            "test devices. If you're actively developing firmware for the "
            "device you're trying to flash, you most likely want unsigned "
            "firmware."
        ),
        examples="{signed|unsigned}",
        required=True,
        strict=True,
    ),
    "firmware-type": FieldDoc(
        description=(
            "Any additional qualifiers required to differentiate specific "
            "firmware images. AP images for example can be built with the "
            "`serial` flag, which is required to enable uart console logging."
        ),
        examples="{serial|dev|net}",
        required=False,
        strict=True,
    ),
}

MAXIMUM_LINE_LENGTH = 80


def build_usage_string() -> str:
    """Builds documentation for fwbuddy

    Returns:
        A usage string describing all of the URI fields.
    """
    usage = FWBUDDY_URI_SCHEMA + "\n\n"
    indent = "\t"
    for field in FIELD_DOCS:
        usage += build_field_doc(field, indent, MAXIMUM_LINE_LENGTH)
    return usage


def build_field_doc(field: str, indent: str, line_length: int) -> str:
    """Builds the documentation for a single URI field

    Args:
        field: The URI field to build docs for
        indent: How much to indent each line
        line_length: The maximmum length of each line disregarding indent.

    Returns:
        The doc string for the given field.
    """
    required_state = "REQUIRED" if FIELD_DOCS[field].required else "OPTIONAL"
    description_newline = "\n" + indent + "\t"
    field_doc = f"{indent}{field} ({required_state}):\n"
    field_doc += description_newline
    description = description_newline.join(
        textwrap.wrap(FIELD_DOCS[field].description, line_length)
    )
    field_doc += f"{description}\n\n"
    field_doc += description_newline
    field_doc += "One of: " if FIELD_DOCS[field].strict else "Examples: "
    field_doc += f"{FIELD_DOCS[field].examples}\n\n"
    return field_doc


USAGE = build_usage_string()

BUG_SUBMIT_URL = (
    "https://issuetracker.google.com/issues/new?component="
    "1094001&template=1670797"
)

# If a user passes just "fwbuddy" as a URI then prompt the user for each field
# one by one.
INTERACTIVE_MODE = ["fwbuddy", "fwbuddy://"]

# TODO(b/280096504) Add support for channel specific versions.
STABLE = "stable"
STABLE_RO = "stable-ro"
LATEST = "latest"
PINNED_VERSIONS = [STABLE, STABLE_RO, LATEST]

SIGNED = "signed"
UNSIGNED = "unsigned"
IMAGE_TYPES = [SIGNED, UNSIGNED]

# The name of the firmware tar file containing the unsigned firmware image in
# Google Storage. All unsigned release archives have exactly this name.
UNSIGNED_ARCHIVE_NAME = "firmware_from_source.tar.bz2"

# The GS bucket that contains our unsigned firmware archives.
UNSIGNED_ARCHIVE_BUCKET = "gs://chromeos-image-archive"

# The GS bucket that contains our signed firmware archives.
SIGNED_ARCHIVE_BUCKET = "gs://chromeos-releases"

# Where to temporarily store files downloaded from Google Storage.
TMP_STORAGE_FOLDER = "/tmp/fwbuddy"

# Where firmware archives are extracted to when a folder isn't specified.
DEFAULT_EXTRACTED_ARCHIVE_PATH = f"{TMP_STORAGE_FOLDER}/archive"

# Where firmware images are exported to when a folder isn't specified.
DEFAULT_EXPORTED_FIRMWARE_PATH = f"{TMP_STORAGE_FOLDER}/exported"

# Some AP Firmware Images are compiled with different flags to enable features
# like additional logging. In the firmware archives, this images would show up
# as image-galtic.serial.bin or image-galtic.dev.bin.
SERIAL = "serial"
DEV = "dev"
NET = "net"
AP_FIRMWARE_TYPES = [SERIAL, DEV, NET]

# The currently supported chip types.
AP = "ap"
EC = "ec"
CHIP_TYPES = [AP, EC]

# A small JSON file containing a (board, model) -> branch_name mapping populated
# with data from DLM
BRANCH_MAP_LOCAL_PATH = Path(f"{TMP_STORAGE_FOLDER}/firmware_quals.json")
BRANCH_MAP_URI = "gs://chromeos-build-release-console/firmware_quals.json"

# All known file path schemas that unsigned firmware archives may be stored
# underneath. This list may grow over time as more schemas are discovered.
UNSIGNED_GSPATH_SCHEMAS_WITHOUT_BRANCH = [
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/firmware-%(board)s-%(major_version)s."
        f"B-branch-firmware/R%(milestone)s-%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/firmware-%(board)s-%(major_version)s."
        f"B-branch-firmware/R%(milestone)s-%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/%(board)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(board)s-firmware/R%(milestone)s-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s/"
        f"{UNSIGNED_ARCHIVE_NAME}"
    ),
]
# Schemas that incorporate firmware branch directly.
UNSIGNED_GSPATH_SCHEMAS_WITH_BRANCH = [
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(branch)s-branch-firmware/R%(milestone)s-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s/"
        f"{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(branch)s-branch-firmware/R%(milestone)s-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s/%(board)s/"
        f"{UNSIGNED_ARCHIVE_NAME}"
    ),
]

# All known file path schemas that signed firmware archives may be stored
# underneath. This list may grow over time as more schemas are discovered.
SIGNED_GSPATH_SCHEMAS = [
    (
        f"{SIGNED_ARCHIVE_BUCKET}/canary-channel/%(board)s/%(major_version)s."
        f"%(minor_version)s.%(patch_number)s/ChromeOS-firmware-R%(milestone)s-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s-"
        f"%(board)s.tar.bz2"
    )
]

# Schemas used to generate the local file path for firmware images.
AP_PATH_SCHEMA = "%(directory)s/image-%(firmware_name)s.bin"
AP_PATH_SCHEMA_WITH_FIRMWARE_TYPE = (
    "%(directory)s/image-%(firmware_name)s.%(firmware_type)s.bin"
)
EC_PATH_SCHEMA = "%(directory)s/%(firmware_name)s/ec.bin"

# Example: R89-13606.459.0
RELEASE_STRING_REGEX_PATTERN = re.compile(r"[R|r](\d+|\*)-(\d+)\.(\d+)\.(\d+)")

# Example: fwbuddy://dedede/galnat360/galtic/latest/signed/serial
FWBUDDY_URI_REGEX_PATTERN = re.compile(
    r"fwbuddy:\/\/(\w+)\/(\w+)\/(\w+)\/([\w\-\.\*]+)\/(\w+)\/?(\w+)?"
)


class FwBuddy:
    """Class that manages firmware archive retrieval from Google Storage"""

    def __init__(self, uri: str) -> None:
        """Initialize fwbuddy from an fwbuddy URI

        This constructor performs all manner of URI validation and resolves
        any ambiguous version identifiers (such as "stable") to locate the
        Google Storage path for the firmware archive. This constructor calls
        out to DLM and Google Storage to accomplish this.

        This constructor will error if it is unable to determine the
        complete Google Storage path defined by the fwbuddy URI for any reason.

        Args:
            uri: An fwbuddy URI used to identify a specific firmware archive.
        """

        # These paths are not populated until after we've downloaded and
        # extracted the contents of the firmware archive.
        self.archive_path: Optional[str] = None
        self.ec_path: Optional[str] = None
        self.ap_path: Optional[str] = None
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        if uri in INTERACTIVE_MODE:
            uri = get_uri_interactive()
        self.cleanup()
        self.setup()
        self.gs = gs.GSContext()
        self.uri = parse_uri(uri)
        self.fw_image = self.build_fw_image()
        self.gspath = self.determine_gspath()

    def cleanup(self) -> None:
        """Deletes any temporarily downloaded files"""
        if os.path.isdir(TMP_STORAGE_FOLDER):
            shutil.rmtree(TMP_STORAGE_FOLDER)

    def setup(self) -> None:
        """Create the folder that will contain our tmp data."""
        os.makedirs(DEFAULT_EXTRACTED_ARCHIVE_PATH, exist_ok=True)
        os.makedirs(DEFAULT_EXPORTED_FIRMWARE_PATH, exist_ok=True)

    def build_fw_image(self) -> FwImage:
        """Builds a new FwImage with information from the URI and DLM

        Returns:
            The FwImage
        """
        return FwImage(
            board=self.uri.board,
            model=self.uri.model,
            firmware_name=self.uri.firmware_name,
            release=self.determine_release(),
            branches=self.lookup_branches(),
            image_type=self.uri.image_type,
            firmware_type=parse_firmware_type(self.uri.firmware_type),
        )

    def lookup_branches(self) -> Set[str]:
        """Gets the firmware branches for the given board/model combination.

        Some firmware archives are stored underneath branches that do not match
        the name of their board. For those scenarios, we need to retrieve the
        branch name as well and populate our GS schemas using it.

        Returns:
            The possible firmware branches.
        """

        try:
            self.gs.CheckPathAccess(BRANCH_MAP_URI)
        except Exception as e:
            self.logger.warning(
                (
                    "Unable to identify the firmware branch for %s: %s"
                    " This may not be an issue, since the firmware branch is"
                    " only needed on rare occasions. Continuing on for the time"
                    " being..."
                ),
                self.uri,
                e,
            )
            return set()

        self.gs.Copy(BRANCH_MAP_URI, TMP_STORAGE_FOLDER)
        branches: Set[str] = set()
        branch_map = json.loads(
            BRANCH_MAP_LOCAL_PATH.read_text(encoding="utf-8")
        )
        for entry in branch_map["firmware_quals"]:
            if (
                "model_name" in entry
                and "board_name" in entry
                and "branch_name" in entry
                and entry["model_name"] == self.uri.model
                and entry["board_name"] == self.uri.board
            ):
                branches.add(entry["branch_name"])
        return branches

    def determine_release(self) -> Release:
        """Generates a Release from a pinned version or release string

        Queries DLM if the version included in the URI is a pinned version.
        Otherwise just parses the version into a Release.

        Returns:
            The Release

        Raises:
            FwBuddyException: If a pinned version is supplied (WIP)
        """
        # TODO(b/280096504) Implement support for pinned versions
        if self.uri.version.lower() in PINNED_VERSIONS:
            raise FwBuddyException(
                "Support for pinned versions is still under development and "
                "is not supported at this time."
            )
        return parse_release_string(self.uri.version)

    def determine_gspath(self) -> str:
        """Determines where in GS our firmware archive is located.

        Returns:
            The first gs path we check that actually exists.

        Raises:
            FwbuddyException: If we couldn't find any real gspaths.
        """
        self.logger.info("Attempting to locate the firmware archive...")
        possible_gspaths = generate_gspaths(self.fw_image)
        for gspath in possible_gspaths:
            try:
                self.logger.info("Checking %s...", gspath)
                self.gs.CheckPathAccess(gspath)
                gspath = self.gs.LS(gspath)[0]
                self.logger.info(
                    "Succesfully located the firmware archive at %s", gspath
                )
                return gspath
            except gs.GSNoSuchKey:
                pass

        raise FwBuddyException(
            f"Unable to locate the firmware archive for: {self.uri} Please"
            " double check your fwbuddy uri. If you are confident that the"
            " firmware you are looking for exists, please submit a bug at"
            f" {BUG_SUBMIT_URL}"
        )

    def download(self) -> None:
        """Downloads the firmware archive from Google Storage to tmp"""
        self.logger.info(
            (
                "Downloading firmware archive from: %s "
                "This may take a few minutes..."
            ),
            self.gspath,
        )
        self.gs.CheckPathAccess(self.gspath)
        self.gs.Copy(self.gspath, TMP_STORAGE_FOLDER)
        self.logger.info(
            "Successfully downloaded the firmware archive from: %s ",
            self.gspath,
        )
        file_name = self.gspath.split("/")[-1]

        # Store the file path in self rather than return it as a string
        # as there's no real reason to expose this information to the API User.
        self.archive_path = f"{TMP_STORAGE_FOLDER}/{file_name}"

    def extract(self, directory: str = DEFAULT_EXTRACTED_ARCHIVE_PATH) -> None:
        """Extracts the firmware archive to a given directory

        Args:
            directory: Where to extract the firmware contents.

        Raises:
            FwBuddyException: If extract contents fails.
        """
        self.logger.info("Extracting firmware contents to: %s...", directory)
        result = cros_build_lib.run(
            ["tar", "-xf", self.archive_path, f"--directory={directory}"],
            check=False,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode == 1:
            raise FwBuddyException(
                "Encountered a fatal error while extracting firmware archive"
                f" contents: {result.stderr}"
            )
        self.logger.info(
            "Successfully extracted firmware contents to: %s", directory
        )
        ap_path_schema = (
            AP_PATH_SCHEMA_WITH_FIRMWARE_TYPE
            if self.fw_image.firmware_type
            else AP_PATH_SCHEMA
        )
        self.ap_path = ap_path_schema % {
            "directory": directory,
            "firmware_name": self.fw_image.firmware_name,
            "firmware_type": self.fw_image.firmware_type,
        }
        self.ec_path = EC_PATH_SCHEMA % {
            "directory": directory,
            "firmware_name": self.fw_image.firmware_name,
        }

    def export_firmware_image(self, chip: str, directory: str) -> None:
        """Locates the firmware image for the chip and copies it to directory

        Args:
            chip: The firmware chip, E.G. AP or EC
            directory: Where to copy the image to

        Raises:
            FwBuddyException: If firmware unexported or failed to copy image.
        """
        chip_name = parse_chip(chip)
        if (self.ec_path is None and chip == EC) or (
            self.ap_path is None and chip == AP
        ):
            raise FwBuddyException(
                "Attempted to export firmware from an unextracted"
                " archive. Please first extract the firmware archive by running"
                " fwbuddy.extract"
            )

        firmware_image_path = self.ec_path if chip == EC else self.ap_path
        image_name = ""
        if firmware_image_path is not None:
            image_name = firmware_image_path.split("/")[-1]

        # Get the absolute path, expanding any user or system
        # variables, like `~` to reference $HOME
        directory = os.path.abspath(
            os.path.expanduser(os.path.expandvars(directory))
        )

        result = cros_build_lib.run(
            ["cp", firmware_image_path, directory],
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode == 1:
            raise FwBuddyException(
                "Encountered a fatal error while exporting the firmware image:"
                f" {result.stderr}"
            )
        self.logger.info(
            "Exported the %s firmware image to %s/%s",
            chip_name,
            directory,
            image_name,
        )


def get_uri_interactive() -> str:
    """Prompts for each field of the fwbuddy uri individually

    Returns:
        The complete fwbuddy URI
    """
    print(
        "You have enabled interactive mode. Prompting for each part of the"
        " fwbuddy URI individually..."
    )
    uri = "fwbuddy://"
    for field_name, field in FIELD_DOCS.items():
        print(build_field_doc(field_name, "", MAXIMUM_LINE_LENGTH))
        user_input = input(f"{field_name}: ")
        while field.required and user_input == "":
            print(
                f"{field_name} is a required field. Please enter a"
                f" {field_name}\n"
            )
            user_input = input(f"{field_name}: ")
        if user_input != "":
            uri += f"{user_input}/"

        print(f"\nURI: {uri}\n")

    return uri


def parse_uri(uri: str) -> URI:
    """Creates a new URI object from an fwbuddy URI string

    Args:
        uri: The fwbuddy uri in string format.

    Returns:
        A URI object with all of the fields from the fwbuddy uri string.

    Raises:
        FwBuddyException: If the fwbuddy uri is malformed.
    """

    fields = FWBUDDY_URI_REGEX_PATTERN.findall(uri)
    if len(fields) == 0 or (len(fields) == 1 and (len(fields[0]) < 5)):
        raise FwBuddyException(
            f"Unable to parse fwbuddy URI: {uri} Expected something "
            f"matching the following format: {USAGE}"
        )

    board = fields[0][0]
    model = fields[0][1]
    firmware_name = fields[0][2]
    version = fields[0][3]
    image_type = fields[0][4]
    firmware_type = None
    if len(fields[0]) == 6 and fields[0][5] != "":
        firmware_type = fields[0][5]

    return URI(
        board=board,
        model=model,
        firmware_name=firmware_name,
        version=version,
        image_type=image_type,
        firmware_type=firmware_type,
    )


def parse_release_string(release_str: str) -> Release:
    """Converts a release string into a Release

    Args:
        release_str: A release string like 'R89-13606.459.0'

    Returns:
        A Release containing data from the release string.

    Raises:
        FwBuddyException: If the release string is malformed.
    """
    fields = RELEASE_STRING_REGEX_PATTERN.findall(release_str)
    if len(fields) == 0 or (len(fields) == 1 and len(fields[0]) != 4):
        raise FwBuddyException(
            "Unrecognized or unsupported firmware version format: "
            f'"{release_str}" Expected either one of {PINNED_VERSIONS} or a '
            'full release string like "R99-123.456.0"'
        )
    return Release(fields[0][0], fields[0][1], fields[0][2], fields[0][3])


def generate_gspaths(fw_image: FwImage) -> Set[str]:
    """Generates all possible GS paths the firmware archive may be stored at

    Args:
        fw_image: The FwImage that contains all the data we need to populate the
            schemas

    Returns:
        A list of all possible paths the archive may be located at.
    """
    gspaths: Set[str] = set()
    schemas: List[str] = []
    if fw_image.image_type == "signed":
        schemas += SIGNED_GSPATH_SCHEMAS
    else:
        if fw_image.branches:
            schemas.extend(UNSIGNED_GSPATH_SCHEMAS_WITH_BRANCH)
        schemas.extend(UNSIGNED_GSPATH_SCHEMAS_WITHOUT_BRANCH)

    if len(fw_image.branches) > 0:
        for branch in fw_image.branches:
            for schema in schemas:
                gspaths.add(build_gspath(schema, fw_image, branch))
    else:
        for schema in schemas:
            gspaths.add(build_gspath(schema, fw_image))

    return gspaths


def build_gspath(schema: str, fw_image: FwImage, branch: str = "") -> str:
    """Populates and returns a gspath schema with supplied data

    Args:
        schema: The gspath schema to populate
        fw_image: The FwImage with the data we need to populate the schema
        branch: The branch to use to populate the schema

    Returns:
        The gspath
    """
    return schema % {
        "board": fw_image.board,
        "milestone": fw_image.release.milestone,
        "major_version": fw_image.release.major_version,
        "minor_version": fw_image.release.minor_version,
        "patch_number": fw_image.release.patch_number,
        "branch": branch,
    }


def parse_chip(chip: Optional[str]) -> Optional[str]:
    """Checks if the chip is supported and returns a lowercase copy of it.

    Args:
        chip: The chip. E.G. AP or EC

    Returns:
        A lowercase copy of the chip

    Raises:
        FwBuddyException: If the chip is not supported
    """
    if chip is None:
        return None
    if chip.lower() in CHIP_TYPES:
        return chip.lower()
    raise FwBuddyException(
        "Unrecognized or unsupported chip type: "
        f'"{chip}" Expected one of {CHIP_TYPES}'
    )


def parse_firmware_type(firmware_type: Optional[str]) -> Optional[str]:
    """Checks if the firmware_type is supported and returns a lowercase copy

    Args:
        firmware_type: The firmware_type. E.G. serial, dev, or net

    Returns:
        A lowercase copy of firmware_type

    Raises:
        FwBuddyException: If the frimware_type is not supported
    """
    if firmware_type is None:
        return None
    if firmware_type.lower() in AP_FIRMWARE_TYPES:
        return firmware_type.lower()
    raise FwBuddyException(
        "Unrecognized or unsupported firmware type: "
        f'"{firmware_type}" Expected one of {AP_FIRMWARE_TYPES}'
    )
