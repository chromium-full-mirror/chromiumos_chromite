# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for the sdk_subtools service layer."""

import contextlib
from pathlib import Path
import unittest
from unittest import mock

import pytest

from chromite.lib import cros_test_lib
from chromite.lib import partial_mock
from chromite.lib import subtool_lib
from chromite.lib import sysroot_lib
from chromite.service import sdk_subtools


@unittest.mock.patch(
    "chromite.service.sdk_subtools.is_inside_subtools_chroot", return_value=True
)
@unittest.mock.patch(
    "chromite.lib.cros_sdk_lib.ChrootReadWrite",
    return_value=contextlib.nullcontext(),
)
def test_install_packages(
    _, __, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that arguments are passed correctly to emerge."""
    run_mock.SetDefaultCmdResult(0)
    sdk_subtools.update_packages(["some-category/package-name"])
    cmd = run_mock.call_args_list[0][0][0]
    assert cmd[0] == "sudo"
    assert cmd[-1] == "some-category/package-name"
    run_mock.assertCommandContains(
        [f"--rebuild-exclude={' '.join(sdk_subtools.EXCLUDE_PACKAGES)}"]
    )


@unittest.mock.patch(
    "chromite.service.sdk_subtools.is_inside_subtools_chroot", return_value=True
)
@unittest.mock.patch(
    "chromite.lib.cros_sdk_lib.ChrootReadWrite",
    return_value=contextlib.nullcontext(),
)
def test_install_packages_failure(
    _, __, run_mock: cros_test_lib.RunCommandMock
) -> None:
    """Test that PackageInstallError is raised on emerge failure."""
    run_mock.AddCmdResult(
        partial_mock.InOrder(
            [
                "/mnt/host/source/chromite/bin/parallel_emerge",
                "some-category/package-name",
            ]
        ),
        returncode=42,
    )
    with pytest.raises(sysroot_lib.PackageInstallError) as error_info:
        sdk_subtools.update_packages(["some-category/package-name"])

    assert error_info.value.result.returncode == 42


def test_bundle_private_only(tmp_path: Path) -> None:
    """Test bundle_and_prepare_upload with private_only=True."""
    dir_struct = [
        "work/",
        "config/public.textproto",
        "config/private.textproto",
    ]
    cros_test_lib.CreateOnDiskHierarchy(tmp_path, dir_struct)

    public_subtool = mock.Mock()
    public_subtool.private_packages = []

    private_subtool = mock.Mock()
    private_subtool.private_packages = ["some-category/package-0.0.1-r1"]

    def _fake_subtool_from_file(path: Path, *_args, **_kwargs):
        if path.name == "public.textproto":
            return public_subtool
        if path.name == "private.textproto":
            return private_subtool
        assert False, f"Unexpected path: {path}"

    with mock.patch.object(
        subtool_lib.Subtool,
        "from_file",
        new=_fake_subtool_from_file,
    ), mock.patch.object(
        sdk_subtools, "SUBTOOLS_EXPORTS_CONFIG_DIR", new=tmp_path / "config"
    ), mock.patch.object(
        sdk_subtools, "SUBTOOLS_BUNDLE_WORK_DIR", new=tmp_path / "work"
    ), mock.patch.object(
        sdk_subtools, "is_inside_subtools_chroot", return_value=True
    ):
        sdk_subtools.bundle_and_prepare_upload(private_only=True)

    public_subtool.prepare_upload.assert_not_called()
    private_subtool.prepare_upload.assert_called_once()
