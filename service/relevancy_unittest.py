# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the relevancy service."""

from pathlib import Path
from typing import List, Optional, Type

import pytest

from chromite.lib import build_query
from chromite.lib import build_target_lib
from chromite.lib import constants
from chromite.lib import portage_util
from chromite.service import relevancy
from chromite.test import portage_testables


# pylint complains about fixture usage.
# pylint: disable=redefined-outer-name
# pylint: disable=unused-argument


@pytest.fixture
def source_root_is_tmp(
    monkeypatch: "pytest.MonkeyPatch", tmp_path: Path
) -> None:
    """Patch SOURCE_ROOT to tmp_path."""
    monkeypatch.setattr(constants, "SOURCE_ROOT", tmp_path)


@pytest.fixture
def mock_source_info(monkeypatch: "pytest.MonkeyPatch", tmp_path: Path) -> None:
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
        ("manifest-internal/default.xml", "fake", relevancy.ReasonPathRule),
        (
            "src/overlays/baseboard-fake/profiles/base/make.defaults",
            "fake",
            relevancy.ReasonProfile,
        ),
        (
            "src/overlays/baseboard-fake/profiles/base/make.defaults",
            "faux",
            relevancy.ReasonProfile,
        ),
        (
            "src/overlays/overlay-fake/profiles/base/make.defaults",
            "fake",
            relevancy.ReasonProfile,
        ),
        (
            "src/overlays/overlay-fake/profiles/base/make.defaults",
            "faux",
            relevancy.ReasonProfile,
        ),
        (
            "src/private-overlays/overlay-faux-private/profiles/symlinked/"
            "make.defaults",
            "faux",
            relevancy.ReasonProfile,
        ),
        ("src/overlays/overlay-fake/profiles/base/make.defaults", "foo", None),
        (
            "src/overlays/overlay-fake/metadata/layout.conf",
            "fake",
            relevancy.ReasonOverlay,
        ),
        (
            "src/overlays/overlay-fake/chromeos-base/chromeos-bsp-fake/"
            "Manifest",
            "fake",
            relevancy.ReasonPackage,
        ),
        (
            "src/overlays/overlay-fake/chromeos-base/chromeos-bsp-fake/"
            "Manifest",
            "faux",
            relevancy.ReasonPackage,
        ),
        (
            "src/overlays/overlay-fake/chromeos-base/chromeos-bsp-fake/"
            "Manifest",
            "foo",
            None,
        ),
        ("src/platform/fake", "fake", None),
        ("src/platform/fake/subdir", "fake", relevancy.ReasonPackage),
        ("src/platform/fake/subdir/path.c", "fake", relevancy.ReasonPackage),
        ("chromite/contrib/script.py", "fake", None),
        ("chromite/lib/cros_build_lib_unittest.py", "fake", None),
        ("chromite/lib/cros_build_lib.py", "fake", relevancy.ReasonPathRule),
        ("chromite/lib/subtool_lib.py", "fake", None),
        ("src/scripts/update_chroot.sh", "fake", relevancy.ReasonPathRule),
        ("src/third_party/kernel/v5.15/foo.c", "fake", None),
        ("src/third_party/kernel/v5.15/foo.c", "foo", relevancy.ReasonPathRule),
        ("src/third_party/kernel/v6.1/foo.c", "fake", relevancy.ReasonPathRule),
        ("src/third_party/kernel/v6.1/foo.c", "foo", None),
        ("src/third_party/coreboot/Makefile", "fake", relevancy.ReasonPathRule),
        ("src/third_party/coreboot/Makefile", "foo", None),
        ("infra/recipes/recipes.py", "fake", None),
    ],
)
def test_relevancy(
    path: str,
    board: str,
    expected_reason: Optional[Type[relevancy.Reason]],
    fake_build_query_overlays: List[portage_testables.Overlay],
    source_root_is_tmp: None,
    mock_source_info: None,
) -> None:
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
