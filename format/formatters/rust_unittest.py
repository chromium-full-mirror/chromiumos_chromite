# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the rust formatter module."""

# pylint: disable=protected-access

from pathlib import Path

from chromite.format import formatters


def test_find_edition_current_dir(tmp_path: Path) -> None:
    """Test finding edition when Cargo.toml is in the current directory."""
    cargo_toml = tmp_path / "Cargo.toml"
    cargo_toml.write_text('edition = "2024"\n', encoding="utf-8")
    assert formatters.rust._find_edition(tmp_path) == "2024"


def test_find_edition_parent_dir(tmp_path: Path) -> None:
    """Test finding edition when Cargo.toml is in a parent directory."""
    parent = tmp_path
    child = parent / "child" / "grandchild"
    child.mkdir(parents=True)

    cargo_toml = parent / "Cargo.toml"
    cargo_toml.write_text('edition = "2018"\n', encoding="utf-8")
    assert formatters.rust._find_edition(child) == "2018"


def test_find_edition_missing(tmp_path: Path) -> None:
    """Test that default edition is returned when Cargo.toml is missing."""
    assert (
        formatters.rust._find_edition(tmp_path)
        == formatters.rust.DEFAULT_EDITION
    )


def test_find_edition_no_match(tmp_path: Path) -> None:
    """Test that default edition is returned when Cargo.toml has no edition."""
    cargo_toml = tmp_path / "Cargo.toml"
    cargo_toml.write_text('foo = "bar"\n', encoding="utf-8")
    assert (
        formatters.rust._find_edition(tmp_path)
        == formatters.rust.DEFAULT_EDITION
    )


def test_find_edition_no_match_but_parent_has_it(tmp_path: Path) -> None:
    """Test that we continue to parent if current Cargo.toml has no edition."""
    parent = tmp_path
    child = parent / "child"
    child.mkdir()

    parent_cargo = parent / "Cargo.toml"
    parent_cargo.write_text('edition = "2024"\n', encoding="utf-8")

    child_cargo = child / "Cargo.toml"
    child_cargo.write_text('foo = "bar"\n', encoding="utf-8")

    assert formatters.rust._find_edition(child) == "2024"
