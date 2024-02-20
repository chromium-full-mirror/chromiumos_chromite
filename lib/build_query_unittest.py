# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for query.py."""

from pathlib import Path
from typing import Dict

import pytest

from chromite.lib import build_query


# fake_build_query_overlays is a fixture, and the value need not always be used
# by the tests.
# pylint: disable=unused-argument


def test_query_overlays(fake_build_query_overlays) -> None:
    """Test listing all overlays."""
    overlays = {x.name: x for x in build_query.Overlay.find_all()}
    assert overlays["baseboard-fake"].board_name is None
    assert overlays["baseboard-fake"].is_private is False
    assert overlays["fake"].board_name == "fake"
    assert overlays["fake"].is_private is False
    assert overlays["baseboard-fake-private"].board_name is None
    assert overlays["baseboard-fake-private"].is_private is True
    assert overlays["fake-private"].board_name == "fake"
    assert overlays["fake-private"].is_private is True


def test_query_profiles(fake_build_query_overlays) -> None:
    """Test listing all profiles."""
    profiles: Dict[str, build_query.Profile] = {
        str(x): x for x in build_query.Profile.find_all()
    }
    assert profiles["baseboard-fake:base"].overlay.name == "baseboard-fake"
    assert profiles["baseboard-fake:base"].name == "base"
    assert profiles["baseboard-fake:base"].parents == []
    assert profiles["fake:base"].overlay.name == "fake"
    assert profiles["fake:base"].name == "base"
    assert profiles["fake:base"].parents == [profiles["baseboard-fake:base"]]
    assert (
        profiles["baseboard-fake-private:base"].overlay.name
        == "baseboard-fake-private"
    )
    assert profiles["baseboard-fake-private:base"].name == "base"
    assert profiles["baseboard-fake-private:base"].parents == [
        profiles["baseboard-fake:base"]
    ]
    assert profiles["fake-private:alt-profile"].overlay.name == "fake-private"
    assert profiles["fake-private:alt-profile"].name == "alt-profile"
    assert profiles["fake-private:alt-profile"].parents == [
        profiles["fake-private:base"]
    ]
    assert profiles["fake-private:base"].overlay.name == "fake-private"
    assert profiles["fake-private:base"].name == "base"
    assert profiles["fake-private:base"].parents == [
        profiles["baseboard-fake-private:base"],
        profiles["fake:base"],
    ]


def test_query_boards(fake_build_query_overlays) -> None:
    """Test listing all boards."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == "fake")
        .one()
    )
    assert board.arch == "amd64"
    overlay = [
        x for x in fake_build_query_overlays if x.name == "fake-private"
    ][0]
    assert board.top_level_overlay.path == overlay.path
    assert (
        board.top_level_profile.path == overlay.profiles[Path("base")].full_path
    )


def test_query_ebuilds(fake_build_query_overlays) -> None:
    """Test listing all ebuilds."""
    ebuilds = list(build_query.Ebuild.find_all())
    found_packages = {str(ebuild) for ebuild in ebuilds}
    assert found_packages == {
        "chromeos-base/chromeos-bsp-fake-0.0.1-r256::fake",
        "chromeos-base/chromeos-bsp-fake-9999::fake",
        "chromeos-base/chromeos-bsp-fake-private-0.0.1::fake-private",
        "chromeos-base/chromeos-bsp-fake-private-9999::fake-private",
    }
    assert all(x.eapi == 7 for x in ebuilds)
    assert all(x.eclasses == ["cros-workon", "chromeos-bsp"] for x in ebuilds)
    assert all(x.iuse == {"another", "internal", "static"} for x in ebuilds)
    assert all(x.iuse_default == {"static"} for x in ebuilds)


@pytest.mark.parametrize(
    ["board_name", "is_variant"],
    [
        ("fake", False),
        ("faux", True),
    ],
)
def test_is_variant(fake_build_query_overlays, board_name, is_variant) -> None:
    """Test the is_variant property of boards."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == board_name)
        .one()
    )
    assert board.is_variant == is_variant


@pytest.mark.parametrize(
    ["cpvr", "arch", "expected_stability"],
    [
        (
            "chromeos-base/chromeos-bsp-fake-0.0.1-r256",
            "amd64",
            build_query.Stability.STABLE,
        ),
        (
            "chromeos-base/chromeos-bsp-fake-9999",
            "amd64",
            build_query.Stability.UNSTABLE,
        ),
        (
            "chromeos-base/chromeos-bsp-fake-private-0.0.1",
            "amd64",
            build_query.Stability.UNSTABLE,
        ),
        (
            "chromeos-base/chromeos-bsp-fake-private-0.0.1",
            "arm",
            build_query.Stability.BAD,
        ),
        (
            "chromeos-base/chromeos-bsp-fake-private-9999",
            "arm",
            build_query.Stability.UNSTABLE,
        ),
        (
            "chromeos-base/chromeos-bsp-fake-private-9999",
            "amd64",
            build_query.Stability.STABLE,
        ),
    ],
)
def test_ebuild_stability(
    fake_build_query_overlays, cpvr, arch, expected_stability
) -> None:
    """Test the ebuild stability evaluator."""
    ebuild = (
        build_query.Query(build_query.Ebuild)
        .filter(lambda ebuild: ebuild.package_info.cpvr == cpvr)
        .one()
    )
    assert ebuild.get_stability(arch) == expected_stability


def test_make_conf_vars(fake_build_query_overlays) -> None:
    """Test reading make.conf variables from an overlay."""
    overlay = (
        build_query.Query(build_query.Overlay)
        .filter(lambda overlay: overlay.name == "fake-private")
        .one()
    )
    assert overlay.make_conf_vars == {
        "CHOST": "x86_64-pc-linux-gnu",
        "USE": "internal",
    }


def test_overlay_parents(fake_build_query_overlays) -> None:
    overlays = {x.name: x for x in build_query.Overlay.find_all()}
    assert list(overlays["baseboard-fake-private"].parents) == [
        overlays["portage-stable"],
        overlays["chromiumos"],
        overlays["eclass-overlay"],
        overlays["baseboard-fake"],
    ]


def test_use_flags(fake_build_query_overlays) -> None:
    """Test getting the USE flags on a board."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == "fake")
        .one()
    )
    assert board.use_flags == {
        "amd64",
        "board_use_fake",
        "not_masked",
        "some",
        "fake",
        "internal",
        "some_var_board_val",
        "some_var_private_val",
        "another_var_one_val",
        "another_var_another_val",
        "kernel-6_1",
        "bootimage",
    }


def test_use_flags_set(fake_build_query_overlays) -> None:
    """Test querying the flags set by a profile."""
    overlay = (
        build_query.Query(build_query.Overlay)
        .filter(lambda overlay: overlay.name == "baseboard-fake")
        .one()
    )
    profile = overlay.profiles[0]
    assert profile.use_flags_set == {
        "amd64",
        "some",
        "another",
        "masked",
        "not_masked",
        "some_var_baseboard_val",
        "bootimage",
    }


def test_use_flags_unset(fake_build_query_overlays) -> None:
    """Test querying the flags unset by a profile."""
    overlay = (
        build_query.Query(build_query.Overlay)
        .filter(lambda overlay: overlay.name == "fake")
        .one()
    )
    profile = overlay.profiles[0]
    assert profile.use_flags_unset == {
        "another",
        "baseboard_fake_private",
        "some_var_*",
    }


def test_masked_use_flags(fake_build_query_overlays) -> None:
    """Test getting the masked_use_flags on a profile."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == "fake")
        .one()
    )
    assert board.top_level_profile.masked_use_flags == {"masked"}


def test_board_get(fake_build_query_overlays) -> None:
    """Test Board.get() convenience classmethod."""
    board = build_query.Board.get("fake")
    assert board.name == "fake"


def test_board_get_fail(fake_build_query_overlays) -> None:
    """Test Board.get() convenience classmethod on a bad board name."""
    with pytest.raises(ValueError):
        build_query.Board.get("notfake")


def test_board_get_profile(fake_build_query_overlays) -> None:
    """Test Board.get() with a profile."""
    board = build_query.Board.get("fake", profile="alt-profile")
    assert board.name == "fake"
    assert "alt_profile" in board.use_flags


def test_query_one(fake_build_query_overlays) -> None:
    """Test .one() on a query which yields one result."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == "fake")
        .one()
    )
    assert board.name == "fake"


def test_query_one_fail_zero(fake_build_query_overlays) -> None:
    """Test .one() on a query which yields zero results fails."""
    with pytest.raises(StopIteration):
        build_query.Query(build_query.Board).filter(
            lambda x: x.name == "notfake"
        ).one()


def test_query_one_fail_multiple(fake_build_query_overlays) -> None:
    """Test .one() on a query which yields multiple results fails."""
    with pytest.raises(ValueError):
        build_query.Query(build_query.Ebuild).one()


def test_query_one_or_none(fake_build_query_overlays) -> None:
    """Test .one_or_none() on a query which yields no results returns None."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == "notfake")
        .one_or_none()
    )
    assert not board


def test_query_all(fake_build_query_overlays) -> None:
    """Test .all() on a query."""
    boards = build_query.Query(build_query.Board).all()
    assert [str(x) for x in boards] == ["fake", "faux", "foo"]


def test_resolve_incremental_variable(fake_build_query_overlays) -> None:
    """Test correctness Profile.resolve_incremental_variable."""
    board = (
        build_query.Query(build_query.Board)
        .filter(lambda x: x.name == "fake")
        .one()
    )
    assert board.top_level_profile.resolve_var_incremental("SOME_VAR") == {
        "board_val",
        "private_val",
    }
