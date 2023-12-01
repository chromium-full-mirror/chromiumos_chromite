# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the relevancy service."""

from pathlib import Path

import pytest

from chromite.lib import build_query
from chromite.lib import build_target_lib
from chromite.lib import constants
from chromite.lib import portage_util
from chromite.service import relevancy


# pylint complains about fixture usage.
# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument


@pytest.fixture
def source_root_is_tmp(monkeypatch, tmp_path):
    """Patch SOURCE_ROOT to tmp_path."""
    monkeypatch.setattr(constants, "SOURCE_ROOT", tmp_path)


@pytest.fixture
def mock_source_info(monkeypatch, tmp_path):
    """Mock out the source_info property on ebuilds to a constant."""
    fake_source_info = portage_util.SourceInfo(
        projects=["chromiumos/platform/fake"],
        srcdirs=[str(tmp_path / "src/platform/fake")],
        subdirs=[],
        subtrees=[str(tmp_path / "src/platform/fake/subdir")],
    )
    monkeypatch.setattr(build_query.Ebuild, "source_info", fake_source_info)


@pytest.mark.parametrize(
    ["path", "board", "expected_reason"],
    [
        (
            "baseboard-fake/profiles/base/make.defaults",
            "fake",
            relevancy.ReasonProfile,
        ),
        (
            "baseboard-fake/profiles/base/make.defaults",
            "faux",
            relevancy.ReasonProfile,
        ),
        (
            "overlay-fake/profiles/base/make.defaults",
            "fake",
            relevancy.ReasonProfile,
        ),
        (
            "overlay-fake/profiles/base/make.defaults",
            "faux",
            relevancy.ReasonProfile,
        ),
        ("overlay-fake/profiles/base/make.defaults", "foo", None),
        ("overlay-fake/metadata/layout.conf", "fake", relevancy.ReasonOverlay),
        (
            "overlay-fake/chromeos-base/chromeos-bsp-fake/Manifest",
            "fake",
            relevancy.ReasonPackage,
        ),
        (
            "overlay-fake/chromeos-base/chromeos-bsp-fake/Manifest",
            "faux",
            relevancy.ReasonPackage,
        ),
        ("overlay-fake/chromeos-base/chromeos-bsp-fake/Manifest", "foo", None),
        ("src/platform/fake", "fake", None),
        ("src/platform/fake/subdir", "fake", relevancy.ReasonPackage),
        ("src/platform/fake/subdir/path.c", "fake", relevancy.ReasonPackage),
        ("chromite", "fake", relevancy.ReasonFundamental),
        ("src/scripts/update_chroot.sh", "fake", relevancy.ReasonFundamental),
        ("infra/recipes/recipes.py", "fake", None),
    ],
)
def test_relevancy(
    path,
    board,
    expected_reason,
    fake_build_query_overlays,
    source_root_is_tmp,
    mock_source_info,
):
    """Test a variety of relevancy checks."""
    build_target = build_target_lib.BuildTarget(board, public=False)
    relevant_targets = list(
        relevancy.get_relevant_build_targets([build_target], [Path(path)])
    )
    if expected_reason:
        assert len(relevant_targets) == 1
        target, reason = relevant_targets[0]
        assert target == build_target
        assert isinstance(reason, expected_reason)
        assert isinstance(reason.to_proto(), relevancy.ReasonPb)
        assert str(reason)
    else:
        assert not relevant_targets
