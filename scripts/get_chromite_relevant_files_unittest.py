# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_chromite_relevant_files."""

from chromite.scripts import get_chromite_relevant_files


def test_main() -> None:
    """Smoke test."""
    result = get_chromite_relevant_files.main()
    assert result == 0
