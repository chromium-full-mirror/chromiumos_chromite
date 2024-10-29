# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Main module for finding and retrieving firmware archives"""

from __future__ import annotations

import atexit
import enum
import json
import logging
import os
from pathlib import Path
import re
import textwrap
import types
from typing import List, NamedTuple, Optional, Set, Type, Union

from chromite.lib import cros_build_lib
from chromite.lib import gs
from chromite.lib import osutils


class FwBuddyException(Exception):
    """Exception class used by this module."""


class Release(NamedTuple):
    """Tuple representation of a firmware release. e.g. 13606.459.0"""

    major_version: str
    minor_version: str
    patch_number: str


class URI(NamedTuple):
    """All fwbuddy parameters in tuple form"""

    board: str
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
    firmware_name: str
    release: Release
    branches: Set[str]
    image_type: str
    firmware_type: Optional[str]


FWBUDDY_URI_SCHEMA = (
    "fwbuddy://<board>/<firmware-name>/<version>/<image-type>/"
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
            "a specific Galnat360 might indicate that the firmware version is "
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
            " <MAJOR_VERSION>.<MINOR_VERSION>.<PATCH_NUMBER>."
        ),
        examples="{123.456.0}",
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
            ""
            "NOTE: Only unsigned firmware is supported currently. b/318776361"
        ),
        examples="{unsigned}",
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
LATEST = "latest"
PINNED_VERSIONS = [LATEST]

UNSIGNED = "unsigned"
IMAGE_TYPES = [UNSIGNED]

# The name of the firmware tar file containing the unsigned firmware image in
# Google Storage. All unsigned release archives have exactly this name.
UNSIGNED_ARCHIVE_NAME = "firmware_from_source.tar.bz2"

# The GS bucket that contains our unsigned firmware archives.
UNSIGNED_ARCHIVE_BUCKET = "gs://chromeos-image-archive"

# Some AP Firmware Images are compiled with different flags to enable features
# like additional logging. In the firmware archives, this images would show up
# as image-galtic.serial.bin or image-galtic.dev.bin.
SERIAL = "serial"
DEV = "dev"
NET = "net"
AP_FIRMWARE_TYPES = [SERIAL, DEV, NET]

# A small JSON file containing a (board, model) -> branch_name mapping populated
# with data from DLM
BRANCH_MAP_URI = "gs://chromeos-build-release-console/firmware_quals.json"

# All known file path schemas that unsigned firmware archives may be stored
# underneath. This list may grow over time as more schemas are discovered.
UNSIGNED_GSPATH_SCHEMAS_WITHOUT_BRANCH = [
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/firmware-%(board)s-%(major_version)s."
        f"B-branch-firmware/R*-%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/firmware-%(board)s-%(major_version)s."
        f"B-branch-firmware/R*-%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/%(board)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(board)s-firmware/R*-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s/"
        f"{UNSIGNED_ARCHIVE_NAME}"
    ),
]
# Schemas that incorporate firmware branch directly.
UNSIGNED_GSPATH_SCHEMAS_WITH_BRANCH = [
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(branch)s-branch-firmware/R*-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s/"
        f"{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(branch)s-branch-firmware/R*-"
        f"%(major_version)s.%(minor_version)s.%(patch_number)s/%(board)s/"
        f"{UNSIGNED_ARCHIVE_NAME}"
    ),
]

# Schemas used to generate the local file path for firmware images.
AP_PATH_SCHEMA = "%(directory)s/image-%(firmware_name)s.bin"
AP_PATH_SCHEMA_WITH_FIRMWARE_TYPE = (
    "%(directory)s/image-%(firmware_name)s.%(firmware_type)s.bin"
)
EC_PATH_SCHEMA = "%(directory)s/%(firmware_name)s/ec.bin"

# Example: R89-13606.459.0
RELEASE_STRING_REGEX_PATTERN = re.compile(r"(\d+)\.(\d+)\.(\d+)")

# Example: fwbuddy://dedede/galnat360/galtic/latest/unsigned/serial
FWBUDDY_URI_REGEX_PATTERN = re.compile(
    r"fwbuddy:\/\/(\w+)\/(\w+)\/([\w\-\.\*]+)\/(\w+)\/?(\w+)?"
)


class Chip(enum.Enum):
    """The firmware chip to retrieve firmware for"""

    EC = "EC"
    AP = "AP"
    ALL = "ALL"

    @classmethod
    def from_str(cls, chip: Optional[str]) -> Optional[Chip]:
        """Converts a str to a Chip enum

        Args:
            chip: The chip. E.G. AP or EC

        Returns:
            A lowercase copy of the chip

        Raises:
            FwBuddyException: If the chip is not supported
        """
        if chip is None:
            return None
        chip = chip.upper()
        if chip in cls.__members__:
            return Chip[chip]
        raise FwBuddyException(
            "Unrecognized or unsupported chip type: "
            f'"{chip}" Expected one of {cls.__members__}'
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
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

        # Where to temporarily store files downloaded from Google Storage.
        self.temp_dir = osutils.TempDir()
        self.temp_dir_path = Path(str(self.temp_dir))

        # Where to extract firmware archives when a folder isn't specified.
        self.default_extracted_archive_path = (
            Path(self.temp_dir_path) / "archive"
        )

        self.setup_temp_dirs()

        # Registering cleanup using atexit allows us to still cleanup after
        # a CTRL+C and other, less fatal interrupts (wont' do anything in face
        # of a `kill -9`).
        atexit.register(self.temp_dir.Cleanup)

        # Where to store the branch map json file retrieved from GS
        self.branch_map_local_path = (
            Path(self.temp_dir_path) / "firmware_quals.json"
        )

        self.archive_path: Optional[Path] = None
        self.ec_path: Optional[Path] = None
        self.ap_path: Optional[Path] = None

        self.gs = gs.GSContext()

        if uri in INTERACTIVE_MODE:
            uri = get_uri_interactive()
        self.uri = parse_uri(uri)
        self.fw_image = self.build_fw_image()
        self.gspath = self.determine_gspath()

    def __enter__(self) -> FwBuddy:
        """Allows FwBuddy to be used as a context manager ("with" keyword)

        Returns:
            The FwBuddy object
        """
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> None:
        """Cleans up temp dirs when exiting the context manager"""
        self.temp_dir.Cleanup()

    def setup_temp_dirs(self) -> None:
        """Create the folder that will contain our tmp data."""
        os.makedirs(self.default_extracted_archive_path, exist_ok=True)

    def build_fw_image(self) -> FwImage:
        """Builds a new FwImage with information from the URI and DLM

        Returns:
            The FwImage
        """
        return FwImage(
            board=self.uri.board,
            firmware_name=self.uri.firmware_name,
            release=self.determine_release(),
            branches=self.lookup_branches(),
            image_type=self.determine_image_type(),
            firmware_type=parse_firmware_type(self.uri.firmware_type),
        )

    def lookup_branches(self) -> Set[str]:
        """Gets the firmware branches for the given board combination.

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

        self.gs.Copy(BRANCH_MAP_URI, self.temp_dir_path)
        branches: Set[str] = set()
        branch_map = json.loads(
            self.branch_map_local_path.read_text(encoding="utf-8")
        )
        for entry in branch_map["firmware_quals"]:
            if (
                "board_name" in entry
                and "branch_name" in entry
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

    def determine_image_type(self) -> Release:
        """Gets the image type from the uri as lower case

        Returns:
            The image type

        Raises:
            FwBuddyException: If the image type isn't supported
        """
        # TODO(b/318776361) Implement support for signed images
        image_type = self.uri.image_type.lower()
        if image_type not in IMAGE_TYPES:
            raise FwBuddyException(
                f'Unrecognized image type: "{image_type}". Must be one of '
                f"{IMAGE_TYPES}",
            )
        return image_type

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
        self.gs.Copy(self.gspath, self.temp_dir_path)
        self.logger.info(
            "Successfully downloaded the firmware archive from: %s ",
            self.gspath,
        )
        file_name = self.gspath.split("/")[-1]

        # Store the file path in self rather than return it as a string
        # as there's no real reason to expose this information to the API User.
        self.archive_path = Path(self.temp_dir_path) / file_name

    def extract(self, directory: Union[str, Path] = "") -> None:
        """Extracts the firmware archive to a given directory

        Args:
            directory: Where to extract the firmware contents.

        Raises:
            FwBuddyException: If extract contents fails.
        """
        directory = directory or self.default_extracted_archive_path
        os.makedirs(directory, exist_ok=True)
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
        self.ap_path = Path(
            ap_path_schema
            % {
                "directory": directory,
                "firmware_name": self.fw_image.firmware_name,
                "firmware_type": self.fw_image.firmware_type,
            }
        )
        self.ec_path = Path(
            EC_PATH_SCHEMA
            % {
                "directory": directory,
                "firmware_name": self.fw_image.firmware_name,
            }
        )

    def export(self, chip: Chip, directory: str) -> None:
        """Locates the firmware image for the chip and copies it to directory

        Args:
            chip: The firmware chip, E.G. AP or EC
            directory: Where to copy the image to

        Raises:
            FwBuddyException: If the firmware was not extracted.
        """
        if (
            chip is None
            or (self.ec_path is None and chip in [Chip.EC, Chip.ALL])
            or (self.ap_path is None and chip in [Chip.AP, Chip.ALL])
        ):
            raise FwBuddyException(
                "Attempted to export firmware from an unextracted"
                " archive. Please first extract the firmware archive by running"
                " fwbuddy.extract"
            )
        # Get the absolute path, expanding any user or system
        # variables, like `~` to reference $HOME
        directory = os.path.abspath(
            os.path.expanduser(os.path.expandvars(directory))
        )
        os.makedirs(directory, exist_ok=True)

        if chip in [Chip.EC, Chip.ALL]:
            self.export_firmware_image(self.ec_path, directory)
        if chip in [Chip.AP, Chip.ALL]:
            self.export_firmware_image(self.ap_path, directory)

        self.logger.info("Exported firmware to %s", directory)

    def export_firmware_image(
        self, firmware_image_path: str, directory: str
    ) -> None:
        """Copies the firmware image at `firmware_image_path` to `directory`

        Args:
            firmware_image_path: The path to the firmware image
            directory: Where to copy the image to

        Raises:
            FwBuddyException: If the firmware was unable to be exported.
        """
        result = cros_build_lib.run(
            ["cp", firmware_image_path, directory],
            check=False,
            capture_output=True,
            encoding="utf-8",
        )
        if result.returncode == 1:
            raise FwBuddyException(
                "Encountered a fatal error while exporting firmware: "
                f" {result.stderr}"
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
    firmware_name = fields[0][1]
    version = fields[0][2]
    image_type = fields[0][3]
    firmware_type = None
    if len(fields[0]) == 5 and fields[0][4] != "":
        firmware_type = fields[0][4]

    return URI(
        board=board,
        firmware_name=firmware_name,
        version=version,
        image_type=image_type,
        firmware_type=firmware_type,
    )


def parse_release_string(release_str: str) -> Release:
    """Converts a release string into a Release

    Args:
        release_str: A release string like '13606.459.0'

    Returns:
        A Release containing data from the release string.

    Raises:
        FwBuddyException: If the release string is malformed.
    """
    fields = RELEASE_STRING_REGEX_PATTERN.findall(release_str)
    if len(fields) == 0 or (len(fields) == 1 and len(fields[0]) != 3):
        raise FwBuddyException(
            "Unrecognized or unsupported firmware version format: "
            f'"{release_str}" Expected either one of {PINNED_VERSIONS} or a '
            'full release string like "123.456.0"'
        )
    return Release(fields[0][0], fields[0][1], fields[0][2])


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
        "major_version": fw_image.release.major_version,
        "minor_version": fw_image.release.minor_version,
        "patch_number": fw_image.release.patch_number,
        "branch": branch,
    }


def parse_firmware_type(firmware_type: Optional[str]) -> Optional[str]:
    """Checks if the firmware_type is supported and returns a lowercase copy

    Args:
        firmware_type: The firmware_type. E.G. serial, dev, or net

    Returns:
        A lowercase copy of firmware_type

    Raises:
        FwBuddyException: If the firmware_type is not supported
    """
    if firmware_type is None:
        return None
    if firmware_type.lower() in AP_FIRMWARE_TYPES:
        return firmware_type.lower()
    raise FwBuddyException(
        "Unrecognized or unsupported firmware type: "
        f'"{firmware_type}" Expected one of {AP_FIRMWARE_TYPES}'
    )
