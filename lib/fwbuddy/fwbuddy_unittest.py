# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for fwbuddy.py."""

# This is to prevent pylint from complaining about us including, but not
# using the `setup` fixture.
# pylint: disable=unused-argument


import builtins
import os
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from chromite.lib import cros_test_lib
from chromite.lib import gs
from chromite.lib.fwbuddy import fwbuddy


GENERIC_VALID_URI = "fwbuddy://dedede/galtic/123.456.0/unsigned/serial"

FAKE_FIRMWARE_QUALS_DATA = """{
    "firmware_quals": [
        {
            "board_name": "dedede",
            "model_name": "galnat360",
            "branch_name": "firmware-dedede-13606.B"
        }
    ]
}
"""


def mock_read_text(*args: Any, **kwargs: Any) -> str:
    return FAKE_FIRMWARE_QUALS_DATA


@pytest.fixture(name="setup")
def fixture_setup(monkeypatch: "pytest.MonkeyPatch") -> None:
    monkeypatch.setattr(gs.GSContext, "LS", lambda *_,: ["some/path"])
    monkeypatch.setattr(gs.GSContext, "Copy", lambda *_,: None)
    monkeypatch.setattr(gs.GSContext, "CheckPathAccess", lambda *_,: None)
    monkeypatch.setattr(fwbuddy.FwBuddy, "setup_temp_dirs", lambda *_,: None)
    monkeypatch.setattr(Path, "read_text", mock_read_text)


def test_context_manager(setup: Path) -> None:
    """Tests that we can manage an FwBuddy object within a context manager"""
    temp_dir_path = Path("")
    with fwbuddy.FwBuddy(GENERIC_VALID_URI) as f:
        temp_dir_path = f.temp_dir_path
        assert os.path.exists(temp_dir_path)

    # Temp directory should be cleaned up after we exit the with block.
    assert not os.path.exists(temp_dir_path)


def test_usage_string(setup: Path) -> None:
    """Test that all of the URI fields are include in the usage doc."""
    for field in fwbuddy.FIELD_DOCS:
        assert field in fwbuddy.USAGE


def test_parse_uri(setup: Path) -> None:
    """Tests that we can properly convert a uri string into a URI object"""
    assert fwbuddy.parse_uri(GENERIC_VALID_URI) == fwbuddy.URI(
        board="dedede",
        firmware_name="galtic",
        version="123.456.0",
        image_type="unsigned",
        firmware_type="serial",
    )

    assert fwbuddy.parse_uri(
        "fwbuddy://dedede/galtic/123.456.0/unsigned"
    ) == fwbuddy.URI(
        board="dedede",
        firmware_name="galtic",
        version="123.456.0",
        image_type="unsigned",
        firmware_type=None,
    )

    # Missing image_type
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_uri("fwbuddy://dedede/galtic/123.456.0")

    # Wrong header
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_uri("fwbozo://dedede/galtic/123.456.0/unsigned")


def test_parse_release_string(setup: Path) -> None:
    """Tests that versions can be parsed into Release Objects"""
    assert fwbuddy.Release("123", "456", "0") == fwbuddy.parse_release_string(
        "123.456.0"
    )

    assert fwbuddy.Release("123", "456", "0") == fwbuddy.parse_release_string(
        "R89-123.456.0"
    )

    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_release_string("some junk")

    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_release_string("123.0")


def test_determine_image_type(setup: Path) -> None:
    """Tests that we properly check for valid image types"""

    uri_template = "fwbuddy://dedede/galtic/123.456.0/{image_type}/serial"
    assert (
        fwbuddy.FwBuddy(
            uri_template.format(image_type="unsigned")
        ).fw_image.image_type
        == "unsigned"
    )
    assert (
        fwbuddy.FwBuddy(
            uri_template.format(image_type="UNsignED")
        ).fw_image.image_type
        == "unsigned"
    )
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.FwBuddy(uri_template.format(image_type="some junk"))
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.FwBuddy(uri_template.format(image_type="signed"))


def test_generate_unsigned_gspaths(setup: Path) -> None:
    """Tests that we can generate unsigned gspaths using our schemas."""

    fw_image = fwbuddy.FwImage(
        board="dedede",
        firmware_name="galtic",
        release=fwbuddy.parse_release_string("13606.459.0"),
        branches=set(["some-branch-name"]),
        image_type="unsigned",
        firmware_type="",
    )

    expected_gspaths = set(
        [
            (
                "gs://chromeos-image-archive/firmware-dedede-13606.B-branch-"
                "firmware/R*-13606.459.0/firmware_from_source.tar.bz2"
            ),
            (
                "gs://chromeos-image-archive/firmware-dedede-13606.B-branch-"
                "firmware/R*-13606.459.0/dedede/firmware_from_source.tar.bz2"
            ),
            (
                "gs://chromeos-image-archive/dedede-firmware/R*-13606.459.0/"
                "firmware_from_source.tar.bz2"
            ),
            (
                "gs://chromeos-image-archive/some-branch-name-branch-"
                "firmware/R*-13606.459.0/firmware_from_source.tar.bz2"
            ),
            (
                "gs://chromeos-image-archive/some-branch-name-branch-"
                "firmware/R*-13606.459.0/dedede/firmware_from_source.tar.bz2"
            ),
        ]
    )

    assert fwbuddy.generate_gspaths(fw_image) == expected_gspaths


def test_generate_gspaths_no_branches(setup: Path) -> None:
    """Tests that we can generate unsigned gspaths using our schemas."""

    fw_image = fwbuddy.FwImage(
        board="dedede",
        firmware_name="galtic",
        release=fwbuddy.parse_release_string("13606.459.0"),
        branches=set(),
        image_type="unsigned",
        firmware_type="",
    )

    expected_gspaths = set(
        [
            (
                "gs://chromeos-image-archive/firmware-dedede-13606.B-branch-"
                "firmware/R*-13606.459.0/firmware_from_source.tar.bz2"
            ),
            (
                "gs://chromeos-image-archive/firmware-dedede-13606.B-branch-"
                "firmware/R*-13606.459.0/dedede/firmware_from_source.tar.bz2"
            ),
            (
                "gs://chromeos-image-archive/dedede-firmware/R*-13606.459.0/"
                "firmware_from_source.tar.bz2"
            ),
        ]
    )

    assert fwbuddy.generate_gspaths(fw_image) == expected_gspaths


def test_lookup_branches(
    setup: Path,
) -> None:
    """Tests that we correctly parse the SQL output from the branch lookup"""
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)
    assert f.lookup_branches() == set(["firmware-dedede-13606.B"])


def test_lookup_branches_fails(setup: Path) -> None:
    """Tests that we return an empty set when we can't access the branch map"""
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)

    with mock.patch(
        "chromite.lib.gs.GSContext.CheckPathAccess",
        side_effect=Exception("No Access"),
    ):
        assert f.lookup_branches() == set()


def test_determine_gspath(
    setup: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)
    assert f.determine_gspath() == "some/path"

    monkeypatch.setattr(fwbuddy, "generate_gspaths", lambda *_,: [])
    with pytest.raises(fwbuddy.FwBuddyException):
        f.determine_gspath()


def test_download(setup: Path) -> None:
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)
    f.download()
    assert f.archive_path == Path(f.temp_dir_path) / "path"


def test_extract(setup: Path, run_mock: cros_test_lib.RunCommandMock) -> None:
    run_mock.SetDefaultCmdResult(0)
    # Ap image path extraction with firmware_type
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)
    f.archive_path = Path("/unused")
    f.extract("tmp")
    assert f.ap_path == Path("tmp/image-galtic.serial.bin")

    # AP and EC image path extraction
    f = fwbuddy.FwBuddy("fwbuddy://dedede/galtic/123.456.0/unsigned")
    f.archive_path = Path("/unused")
    f.extract("tmp")
    assert f.ap_path == Path("tmp/image-galtic.bin")
    assert f.ec_path == Path("tmp/galtic/ec.bin")

    # Some error while extracting archive contents.
    run_mock.SetDefaultCmdResult(1, stderr="some error")
    with pytest.raises(fwbuddy.FwBuddyException):
        f.extract()


def test_export(setup: Path, run_mock: cros_test_lib.RunCommandMock) -> None:
    run_mock.SetDefaultCmdResult(0)
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)
    f.archive_path = Path("/unused")
    f.export_firmware_image = mock.Mock()
    f.extract("tmp")

    f.export(fwbuddy.Chip.ALL, "tmp")

    f.export_firmware_image.assert_has_calls(
        [
            mock.call(f.ec_path, mock.ANY),
            mock.call(f.ap_path, mock.ANY),
        ]
    )


def test_export_exceptions(
    setup: Path, run_mock: cros_test_lib.RunCommandMock
) -> None:
    run_mock.SetDefaultCmdResult(0)
    f = fwbuddy.FwBuddy(GENERIC_VALID_URI)
    f.archive_path = Path("/unused")

    # Unsupported chip
    f.extract("tmp")
    with pytest.raises(fwbuddy.FwBuddyException):
        f.export(None, "tmp")

    # Export without extraction
    f.ec_path = None
    with pytest.raises(fwbuddy.FwBuddyException):
        f.export(fwbuddy.Chip.EC, "tmp")

    # Some failure while exporting
    f.extract("tmp")
    run_mock.SetDefaultCmdResult(1)
    with pytest.raises(fwbuddy.FwBuddyException):
        f.export(fwbuddy.Chip.EC, "tmp")


def test_chip_from_str(setup: Path) -> None:
    assert fwbuddy.Chip.EC == fwbuddy.Chip.from_str("EC")
    assert fwbuddy.Chip.AP == fwbuddy.Chip.from_str("ap")
    assert None is fwbuddy.Chip.from_str(None)

    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.Chip.from_str("junk")


def test_parse_firmware_type(setup: Path) -> None:
    assert "serial" == fwbuddy.parse_firmware_type("SERIAL")
    assert None is fwbuddy.parse_firmware_type(None)
    with pytest.raises(fwbuddy.FwBuddyException):
        fwbuddy.parse_firmware_type("junk")


def test_get_uri_interactive(
    setup: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Test that we can build an fwbuddy URI from an interactive prompt."""
    num = 0

    def increment_num() -> int:
        nonlocal num
        num += 1
        return num

    monkeypatch.setattr(
        builtins, "input", lambda *args, **kwargs: f"{increment_num()}"
    )

    assert fwbuddy.get_uri_interactive() == "fwbuddy://1/2/3/4/5/"


def test_interactive_mode(
    setup: Path, monkeypatch: "pytest.MonkeyPatch"
) -> None:
    """Test that we can trigger interactive mode"""
    mock_input = GENERIC_VALID_URI
    monkeypatch.setattr(
        fwbuddy,
        "get_uri_interactive",
        lambda *args, **kwargs: f"{mock_input}",
    )
    f = fwbuddy.FwBuddy("fwbuddy://")
    assert f.fw_image.board == "dedede"
