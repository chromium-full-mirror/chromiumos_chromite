# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""build_target_lib tests."""

import os

import pytest

from chromite.api.gen.chromiumos import common_pb2
from chromite.lib import build_target_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.test import portage_testables


class BuildTargetTest(cros_test_lib.TempDirTestCase):
    """build_target_lib.BuildTarget tests."""

    def setUp(self) -> None:
        self.sysroot = os.path.join(self.tempdir, "sysroot")
        self.sysroot_denormalized = os.path.join(
            self.tempdir, "dne", "..", "sysroot"
        )
        osutils.SafeMakedirs(self.sysroot)

    def testEqual(self) -> None:
        """Sanity check for __eq__ method."""
        bt1 = build_target_lib.BuildTarget("board", profile="base")
        bt2 = build_target_lib.BuildTarget("board", profile="base")
        bt3 = build_target_lib.BuildTarget("different", profile="base")
        bt4 = build_target_lib.BuildTarget("board", profile="different")
        self.assertEqual(bt1, bt2)
        self.assertNotEqual(bt1, bt3)
        self.assertNotEqual(bt1, bt4)

    def testHostTarget(self) -> None:
        """Test host target with empty name."""
        target = build_target_lib.BuildTarget("")
        self.assertTrue(target.is_host())

    def testNormalRoot(self) -> None:
        """Test normalized sysroot path."""
        target = build_target_lib.BuildTarget("board", build_root=self.sysroot)
        self.assertEqual(self.sysroot, target.root)
        self.assertFalse(target.is_host())

    def testDenormalizedRoot(self) -> None:
        """Test a non-normal sysroot path."""
        target = build_target_lib.BuildTarget(
            "board", build_root=self.sysroot_denormalized
        )
        self.assertEqual(self.sysroot, target.root)

    def testDefaultRoot(self) -> None:
        """Test the default sysroot path."""
        target = build_target_lib.BuildTarget("board")
        self.assertEqual("/build/board", target.root)

    def testFullPath(self) -> None:
        """Test full_path functionality."""
        build_target = build_target_lib.BuildTarget("board")
        result = build_target.full_path("some/path")
        self.assertEqual(result, "/build/board/some/path")

    def testFullPathWithExtraArgs(self) -> None:
        """Test full_path functionality with extra args passed."""
        build_target = build_target_lib.BuildTarget("board")
        path1 = "some/path"
        result = build_target.full_path(path1, "/abc", "def", "/g/h/i")
        self.assertEqual(result, "/build/board/some/path/abc/def/g/h/i")


@pytest.mark.parametrize(["public"], [(True,), (False,), (None,)])
def test_find_overlays_public(tmp_path, monkeypatch, public) -> None:
    """Test find_overlays() called on a public target."""
    build_target = build_target_lib.BuildTarget("board", public=public)

    portage_path = tmp_path / "src" / "third_party" / "portage-stable"
    portage_testables.Overlay(portage_path, "portage-stable")

    cros_path = tmp_path / "src" / "third_party" / "chromiumos-overlay"
    portage_testables.Overlay(cros_path, "chromiumos")

    eclass_path = tmp_path / "src" / "third_party" / "eclass-overlay"
    portage_testables.Overlay(eclass_path, "eclass-overlay")

    public_path = tmp_path / "src" / "overlays" / "overlay-board"
    public_overlay = portage_testables.Overlay(public_path, "board")

    private_path = (
        tmp_path / "src" / "private-overlays" / "overlay-board-private"
    )
    portage_testables.Overlay(
        private_path, "board-private", parent_overlays=[public_overlay]
    )

    chromeos_path = tmp_path / "src" / "private-overlays" / "chromeos-overlay"
    portage_testables.Overlay(chromeos_path, "chromeos")

    real_find_overlays = portage_util.FindOverlays

    def fake_find_overlays(*args, **kwargs):
        kwargs["buildroot"] = tmp_path
        return real_find_overlays(*args, **kwargs)

    monkeypatch.setattr(portage_util, "FindOverlays", fake_find_overlays)

    overlays = set(build_target.find_overlays(source_root=tmp_path))

    expected_overlays = {portage_path, cros_path, eclass_path, public_path}
    if not public:
        expected_overlays.add(private_path)
        expected_overlays.add(chromeos_path)

    assert overlays == expected_overlays


def test_to_proto() -> None:
    """Test build_target_lib.BuildTarget.to_proto()."""
    target = build_target_lib.BuildTarget(
        name="some-board", profile="special-profile"
    )
    assert target.to_proto() == common_pb2.BuildTarget(
        name="some-board",
        profile=common_pb2.Profile(name="special-profile"),
    )


def test_to_from_json() -> None:
    """Test build_target_lib.BuildTarget.to/from_json()."""
    target = build_target_lib.BuildTarget(
        name="board", profile="foo", build_root="/build/root", public=True
    )

    result = build_target_lib.BuildTarget.from_json(target.to_json())

    assert result == target


def test_from_json_invalid() -> None:
    """Test an invalid serialization in from_json()."""

    with pytest.raises(build_target_lib.InvalidSerializedBuildTarget):
        build_target_lib.BuildTarget.from_json("invalid json string")
