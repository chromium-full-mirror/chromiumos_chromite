# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Main module for finding and retrieving firmware archives"""

import logging
import os
import re
import shutil
from typing import List, NamedTuple

from chromite.lib import cros_build_lib
from chromite.lib import gs


USAGE = """
fwbuddy://<board>/<model>/<firmware-name>/<version>/<image-type>/<firmware-type>
        board: {dedede, atlas, etc}
        model: {galnat360, drawcia, etc.}
        firmware-name: {galtic, dood, etc.}
        version: {stable|stable-ro|latest|R99-123.456.0|R*-123.456.0}
        image-type: {signed|unsigned}
        firmware-type: {serial, dev, etc} OPTIONAL
"""

BUG_SUBMIT_URL = (
    "https://issuetracker.google.com/issues/"
    "new?component=1094001&template=1670797"
)

# TODO(b/280096504) Add support for channel specific versions, like 'latest-canary'
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

# Some AP Firmware Images are compiled with different flags to enable features
# like additional logging. In the firmware archives, this images would show up
# as image-galtic.serial.bin or image-galtic.dev.bin.
SERIAL = "serial"
DEV = "dev"
NET = "net"
AP_FIRMWARE_TYPES = [SERIAL, DEV, NET]
# All known file path schemas that unsigned firmware archives may be stored
# underneath. This list may grow over time as more schemas are discovered.
UNSIGNED_GSPATH_SCHEMAS = [
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/firmware-%(board)s-%(major_version)s."
        "B-branch-firmware/R%(milestone)s-%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/firmware-%(board)s-%(major_version)s."
        "B-branch-firmware/R%(milestone)s-%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/%(board)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
    (
        f"{UNSIGNED_ARCHIVE_BUCKET}/%(board)s-firmware/R%(milestone)s-"
        "%(major_version)s.%(minor_version)s."
        f"%(patch_number)s/{UNSIGNED_ARCHIVE_NAME}"
    ),
]

# All known file path schemas that signed firmware archives may be stored
# underneath. This list may grow over time as more schemas are discovered.
SIGNED_GSPATH_SCHEMAS = [
    f"{SIGNED_ARCHIVE_BUCKET}/canary-channel/%(board)s/%(major_version)s."
    "%(minor_version)s.%(patch_number)s/ChromeOS-firmware-R%(milestone)s-"
    "%(major_version)s.%(minor_version)s.%(patch_number)s-%(board)s.tar.bz2"
]

# Example: R89-13606.459.0
RELEASE_STRING_REGEX_PATTERN = re.compile(r"[R|r](\d+|\*)-(\d+)\.(\d+)\.(\d+)")

# Example: fwbuddy://dedede/galnat360/galtic/latest/signed/serial
FWBUDDY_URI_REGEX_PATTERN = re.compile(
    r"fwbuddy:\/\/(\w+)\/(\w+)\/(\w+)\/([\w\-\.\*]+)\/(\w+)\/?(\w+)?"
)


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
    firmware_type: str


class FwImage(NamedTuple):
    """All of the parameters that identify a unique firmware image"""

    board: str
    model: str
    firmware_name: str
    release: Release
    branch: str
    image_type: str
    firmware_type: str


class FwBuddy:
    """Class that manages firmware archive retrieval from Google Storage"""

    def __init__(self, uri: str):
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
        self.archive_path = ""
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
            branch=self.lookup_branch(),
            image_type=self.uri.image_type,
            firmware_type=self.uri.firmware_type,
        )

    # TODO(b/280096504) Implement
    def lookup_branch(self) -> str:
        """Gets the firmware branch for the given board/model combination from DLM

        Some firmware archives are stored underneath branches that do not match
        the name of their board. For those scenarios, we need to retrieve the
        branch name as well and build our GS schemas using it.

        Returns:
            The firmware branch
        """
        return None

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
        logging.notice("Attempting to locate the firmware archive...")
        possible_gspaths = generate_gspaths(self.fw_image)
        for gspath in possible_gspaths:
            try:
                self.gs.CheckPathAccess(gspath)
                gspath = self.gs.LS(gspath)[0]
                logging.notice(
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
        logging.notice(
            "Downloading firmware archive from: %s "
            "This may take a few minutes...",
            self.gspath,
        )
        self.gs.CheckPathAccess(self.gspath)
        self.gs.Copy(self.gspath, TMP_STORAGE_FOLDER)
        logging.notice(
            "Successfully downloaded the firmware archive from: %s ",
            self.gspath,
        )
        file_name = self.gspath.split("/")[-1]

        # Store the file path in self rather than return it as a string
        # as there's no real reason to expose this information to the API User.
        self.archive_path = f"{TMP_STORAGE_FOLDER}/{file_name}"

    def extract(self, directory=DEFAULT_EXTRACTED_ARCHIVE_PATH) -> None:
        """Extracts the firmware archive to a given directory

        Args:
            directory: Where to extract the firmware contents.
        """
        logging.notice("Extracting firmware contents to: %s...", directory)
        cros_build_lib.run(
            ["tar", "-xf", self.archive_path, f"--directory={directory}"],
            capture_output=True,
            encoding="utf-8",
        )
        logging.notice(
            "Successfully extracted firmware contents to: %s", directory
        )


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


def generate_gspaths(fw_image: FwImage) -> List[str]:
    """Generates all possible GS paths the firmware archive may be stored at

    Args:
        fw_image: The FwImage that contains all the data we need to populate the
            schemas

    Returns:
        A list of all possible paths the archive may be.
    """
    # TODO(b/280096504) Add support for boards with different firmware branch names
    gspaths = []
    schemas = (
        SIGNED_GSPATH_SCHEMAS
        if fw_image.image_type == "signed"
        else UNSIGNED_GSPATH_SCHEMAS
    )
    for schema in schemas:
        gspaths.append(
            schema
            % {
                "board": fw_image.board,
                "milestone": fw_image.release.milestone,
                "major_version": fw_image.release.major_version,
                "minor_version": fw_image.release.minor_version,
                "patch_number": fw_image.release.patch_number,
            }
        )

    return gspaths
