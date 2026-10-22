# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for cros_clean_outdated_pkgs."""

from pathlib import Path
from typing import Optional
from unittest import mock

import pytest  # pylint: disable=import-error

import chromite
from chromite.cli.cros import cros_clean_outdated_pkgs
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import portage_util
from chromite.lib.parser import package_info
from chromite.utils.parser import pms_dependency


def _make_cmd(
    cmd_args: Optional[list[str]] = None,
) -> cros_clean_outdated_pkgs.CleanOutdatedCommand:
    """Create a CleanOutdatedCommand instance."""
    if cmd_args is None:
        cmd_args = ["--host"]
    parser = commandline.ArgumentParser()
    cros_clean_outdated_pkgs.CleanOutdatedCommand.AddParser(parser)
    opts = parser.parse_args(cmd_args)
    cros_clean_outdated_pkgs.CleanOutdatedCommand.ProcessOptions(parser, opts)
    return cros_clean_outdated_pkgs.CleanOutdatedCommand(opts)


def _make_pkg(
    cpf: str,
    repo: str = "chromiumos",
    depend: str = "",
    rdepend: str = "",
) -> mock.MagicMock:
    """Create a mock InstalledPackage."""
    pkg_info = package_info.parse(cpf)
    pkg = mock.MagicMock(spec=portage_util.InstalledPackage)
    pkg.package_info = pkg_info
    pkg.category = pkg_info.category
    pkg.package = pkg_info.package
    pkg.version = pkg_info.vr
    pkg.repository = repo
    pkg.depend = (
        pms_dependency.parse(depend) if depend else pms_dependency.RootNode()
    )
    pkg.rdepend = (
        pms_dependency.parse(rdepend) if rdepend else pms_dependency.RootNode()
    )
    return pkg


def test_find_outdated_packages_reasons(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Verify find_outdated_packages records the reason for each package."""
    cmd = _make_cmd(["--host"])
    overlay_dir = tmp_path / "chromiumos-overlay"
    # cat/up-to-date has matching ebuild 1.0-r1.
    (overlay_dir / "cat" / "up-to-date").mkdir(parents=True)
    (overlay_dir / "cat" / "up-to-date" / "up-to-date-1.0-r1.ebuild").touch()
    # cat/wrong-ver has 2.0, 2.1, while 1.0 is installed.
    (overlay_dir / "cat" / "wrong-ver").mkdir(parents=True)
    (overlay_dir / "cat" / "wrong-ver" / "wrong-ver-2.0.ebuild").touch()
    (overlay_dir / "cat" / "wrong-ver" / "wrong-ver-2.1.ebuild").touch()
    # cat/empty-dir exists but has no ebuilds.
    (overlay_dir / "cat" / "empty-dir").mkdir(parents=True)

    finder = mock.MagicMock(spec=cros_clean_outdated_pkgs.OverlayPathFinder)

    def _repo_to_path(repo: str) -> Path:
        if repo == "chromiumos":
            return overlay_dir
        raise KeyError(repo)

    finder.repo_to_path.side_effect = _repo_to_path
    monkeypatch.setattr(
        cros_clean_outdated_pkgs,
        "OverlayPathFinder",
        lambda _board: finder,
    )

    pkgs: list[portage_util.InstalledPackage] = [
        _make_pkg("cat/up-to-date-1.0-r1", repo="chromiumos"),
        _make_pkg("cat/missing-overlay-1.0", repo="gone-overlay"),
        _make_pkg("cat/missing-dir-1.0", repo="chromiumos"),
        _make_pkg("cat/empty-dir-1.0", repo="chromiumos"),
        _make_pkg("cat/wrong-ver-1.0", repo="chromiumos"),
        _make_pkg("sys-devel/gcc-10.0", repo="crossdev"),
    ]

    outdated = cmd.find_outdated_packages(None, pkgs)
    assert outdated == {
        "cat/missing-overlay-1.0": "overlay gone-overlay not found",
        "cat/missing-dir-1.0": (
            "package cat/missing-dir not found in overlay chromiumos"
        ),
        "cat/empty-dir-1.0": "no ebuilds found in overlay chromiumos",
        "cat/wrong-ver-1.0": (
            "installed version 1.0 not in overlay chromiumos "
            "(available: 2.0, 2.1)"
        ),
    }


def test_find_slot_conflicted_packages_reasons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify find_slot_conflicted_packages records unsatisfied deps."""
    cmd = _make_cmd(["--host"])
    monkeypatch.setattr(
        cros_clean_outdated_pkgs,
        "is_dep_satisfiable",
        lambda dep, _root, _board: dep == "dev-libs/ok:0/1=",
    )
    # Mock multiprocessing.Pool so starmap runs in-process with the mock.
    pool_mock = mock.MagicMock()
    pool_mock.__enter__.return_value.starmap.side_effect = (
        lambda func, iterable: [func(*args) for args in iterable]
    )
    monkeypatch.setattr(
        cros_clean_outdated_pkgs.multiprocessing,
        "Pool",
        lambda **_kwargs: pool_mock,
    )

    pkgs: list[portage_util.InstalledPackage] = [
        _make_pkg("cat/ok-pkg-1.0", depend="dev-libs/ok:0/1="),
        _make_pkg(
            "cat/bad-pkg-1.0",
            depend="dev-libs/ok:0/1=",
            rdepend="dev-libs/bad:0/2=",
        ),
    ]

    conflicted = cmd.find_slot_conflicted_packages("/", None, pkgs)
    assert conflicted == {
        "cat/bad-pkg-1.0": (
            "unable to satisfy slot dependencies: dev-libs/bad:0/2="
        ),
    }


def test_filter_packages_to_purge() -> None:
    """Verify filter_packages_to_purge filters system and chrome pkgs."""
    cmd = _make_cmd(["--host", "--keep-chrome-packages"])
    pkgs = {
        "app-admin/sudo-1.9": "overlay chromiumos not found",
        "chromeos-base/chromeos-chrome-120.0": (
            "no ebuilds found in overlay chromiumos"
        ),
        "dev-util/foo-1.0": (
            "installed version 1.0 not in overlay chromiumos (available: 2.0)"
        ),
    }
    filtered = cmd.filter_packages_to_purge(None, pkgs)
    assert filtered == {
        "dev-util/foo-1.0": (
            "installed version 1.0 not in overlay chromiumos (available: 2.0)"
        ),
    }


def test_purge_packages_logs_reason(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    run_mock: cros_test_lib.RunCommandMock,
) -> None:
    """Verify purge_packages logs the unmerge reason for each package."""
    cmd = _make_cmd(["--host"])
    monkeypatch.setattr(
        cros_build_lib,
        "GetSysrootToolPath",
        lambda _sysroot, _tool: "/bin/qmerge",
    )

    pkgs = {
        "dev-util/foo-1.0": "overlay gone-overlay not found",
        "app-misc/bar-2.0": (
            "unable to satisfy slot dependencies: dev-libs/icu:0/73="
        ),
    }
    with caplog.at_level(chromite.NOTICE):
        cmd.purge_packages(None, pkgs)

    assert (
        "Unmerging app-misc/bar-2.0: unable to satisfy slot dependencies: "
        "dev-libs/icu:0/73=" in caplog.text
    )
    assert (
        "Unmerging dev-util/foo-1.0: overlay gone-overlay not found"
        in caplog.text
    )
    run_mock.assertCommandContains(
        [
            "/bin/qmerge",
            "--unmerge",
            "--quiet",
            "--yes",
            "=app-misc/bar-2.0",
            "=dev-util/foo-1.0",
        ],
    )
