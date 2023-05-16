# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for fwbuddy.py."""

# This is to prevent pylint from complaining about us including, but not
# using the `setup` fixture.
# pylint: disable=unused-argument
import pytest

from chromite.lib import gs
from chromite.lib.fwbuddy import fwbuddy


@pytest.fixture(name="setup")
def fixture_setup(monkeypatch):
    monkeypatch.setattr(gs.GSContext, "LS", lambda *_,: ["some/path"])
    monkeypatch.setattr(gs.GSContext, "Copy", lambda *_,: None)
    monkeypatch.setattr(gs.GSContext, "CheckPathAccess", lambda *_,: None)
    monkeypatch.setattr(fwbuddy.FwBuddy, "setup", lambda *_,: None)
    monkeypatch.setattr(fwbuddy.FwBuddy, "cleanup", lambda *_,: None)


def test_parse_uri(setup):
    """Tests that we can properly convert a uri string into a URI object"""
    assert fwbuddy.parse_uri(
        "fwbuddy://dedede/galnat360/galtic/R99-123.456.0/signed/serial"
    ) == fwbuddy.URI(
        board="dedede",
        model="galnat360",
        firmware_name="galtic",
        version="R99-123.456.0",
        image_type="signed",
        firmware_type="serial",
    )

    assert fwbuddy.parse_uri(
        "fwbuddy://dedede/galnat360/galtic/R99-123.456.0/signed"
    ) == fwbuddy.URI(
        board="dedede",
        model="galnat360",
        firmware_name="galtic",
        version="R99-123.456.0",
        image_type="signed",
        firmware_type=None,
    )

    # Missing image_type
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_uri("fwbuddy://dedede/galtic/R99-123.456.0")

    # Wrong header
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_uri(
            "fwbozo://dedede/galnat360/galtic/R99-123.456.0/unsigned"
        )


def test_parse_release_string(setup):
    """Tests that versions can be parsed into Release Objects"""
    assert fwbuddy.Release(
        "99", "123", "456", "0"
    ) == fwbuddy.parse_release_string("R99-123.456.0")

    assert fwbuddy.Release(
        "99", "123", "456", "0"
    ) == fwbuddy.parse_release_string("r99-123.456.0")

    assert fwbuddy.Release(
        "*", "123", "456", "0"
    ) == fwbuddy.parse_release_string("R*-123.456.0")

    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_release_string("99-123.456.0")
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_release_string("R99-123.456")


def test_generate_unsigned_gspaths(setup):
    """Tests that we can generate unsigned gspaths using our schemas."""

    fw_image = fwbuddy.FwImage(
        board="dedede",
        model="",
        firmware_name="galtic",
        release=fwbuddy.parse_release_string("R89-13606.459.0"),
        branch="",
        image_type="unsigned",
        firmware_type="",
    )

    expected_gspaths = [
        (
            "gs://chromeos-image-archive/firmware-dedede-13606.B-branch-"
            "firmware/R89-13606.459.0/firmware_from_source.tar.bz2"
        ),
        (
            "gs://chromeos-image-archive/firmware-dedede-13606.B-branch-"
            "firmware/R89-13606.459.0/dedede/firmware_from_source.tar.bz2"
        ),
        (
            "gs://chromeos-image-archive/dedede-firmware/R89-13606.459.0/"
            "firmware_from_source.tar.bz2"
        ),
    ]

    # This could be neater if https://github.com/pytest-dev/pytest/issues/10032
    # is fixed.
    result = fwbuddy.generate_gspaths(fw_image)
    result.sort()
    expected_gspaths.sort()

    assert result == expected_gspaths


def test_generate_signed_gspaths(setup):
    """Tests that we can generate signed gspaths using our schemas."""
    fw_image = fwbuddy.FwImage(
        board="dedede",
        model="",
        firmware_name="galtic",
        release=fwbuddy.parse_release_string("R89-13606.459.0"),
        branch="",
        image_type="signed",
        firmware_type="",
    )

    expected_gspaths = [
        "gs://chromeos-releases/canary-channel/dedede/13606.459.0/ChromeOS-"
        "firmware-R89-13606.459.0-dedede.tar.bz2"
    ]

    assert fwbuddy.generate_gspaths(fw_image) == expected_gspaths


def test_determine_gspath(setup, monkeypatch):
    f = fwbuddy.FwBuddy(
        "fwbuddy://dedede/galnat360/galtic/R99-123.456.0/signed/serial"
    )
    assert f.determine_gspath() == "some/path"

    monkeypatch.setattr(fwbuddy, "generate_gspaths", lambda *_,: [])
    with pytest.raises(fwbuddy.FwBuddyException):
        f.determine_gspath()


def test_download(setup):
    f = fwbuddy.FwBuddy(
        "fwbuddy://dedede/galnat360/galtic/R99-123.456.0/signed/serial"
    )
    f.download()
    assert f.archive_path == f"{fwbuddy.TMP_STORAGE_FOLDER}/path"
