# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the kernel_builder module."""

import os

from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import kernel_builder
from chromite.lib import osutils


class BuilderTest(cros_test_lib.RunCommandTempDirTestCase):
    """Test Builder."""

    def setUp(self) -> None:
        """Sets up common objects for testing."""
        self._kb = kernel_builder.Builder(
            "foo-board", self.tempdir, "foo-root", "777"
        )

    def testCreateCustomKernel(self) -> None:
        """Tests CreateCustomKernel()."""
        self.PatchDict(os.environ, {"USE": "z"})
        self.rc.AddCmdResult(
            [
                "portageq-foo-board",
                "expand_virtual",
                "/build/foo-board",
                "virtual/linux-sources",
            ],
            stdout="kernel",
        )

        safe_makedirs_mock = self.PatchObject(osutils, "SafeMakedirs")
        self._kb.CreateCustomKernel(["x", "y"])
        safe_makedirs_mock.assert_called_once_with(
            self.tempdir / "packages", sudo=True
        )

        emerge_board = "emerge-foo-board"
        extra_env = {
            "PKGDIR": str(self.tempdir / "packages"),
            "USE": "z x y",
        }
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "chromeos-base/chromeos-initramfs",
            ],
            enter_chroot=True,
            extra_env=extra_env,
        )
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "--onlydeps",
                "kernel",
            ],
            enter_chroot=True,
            extra_env=extra_env,
            clear_env=["INSTALL_MASK"],
        )
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "--buildpkgonly",
                "kernel",
            ],
            enter_chroot=True,
            extra_env=extra_env,
        )
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "--usepkgonly",
                "--root=foo-root",
                "kernel",
            ],
            enter_chroot=True,
            extra_env=extra_env,
        )

    def testCreateCustomKernelOverrideUseFlag(self) -> None:
        """Tests CreateCustomKernel()."""
        self.rc.AddCmdResult(
            [
                "portageq-foo-board",
                "expand_virtual",
                "/build/foo-board",
                "virtual/linux-sources",
            ],
            stdout="kernel",
        )

        safe_makedirs_mock = self.PatchObject(osutils, "SafeMakedirs")
        self._kb.CreateCustomKernel(["x", "y"], ["foo"])
        safe_makedirs_mock.assert_called_once_with(
            self.tempdir / "packages", sudo=True
        )

        emerge_board = "emerge-foo-board"
        extra_env = {
            "PKGDIR": str(self.tempdir / "packages"),
            "USE": "foo x y",
        }
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "chromeos-base/chromeos-initramfs",
            ],
            enter_chroot=True,
            extra_env=extra_env,
        )
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "--onlydeps",
                "kernel",
            ],
            enter_chroot=True,
            extra_env=extra_env,
            clear_env=["INSTALL_MASK"],
        )
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "--buildpkgonly",
                "kernel",
            ],
            enter_chroot=True,
            extra_env=extra_env,
        )
        self.assertCommandCalled(
            [
                emerge_board,
                "--verbose",
                "--jobs=777",
                "--usepkgonly",
                "--root=foo-root",
                "kernel",
            ],
            enter_chroot=True,
            extra_env=extra_env,
        )

    def testCreateKernelImageDefaultArgs(self) -> None:
        """Tests CreateKernelImage() with default arguments."""
        self.rc.AddCmdResult(
            ["portageq-foo-board", "envvar", "ARCH"], stdout="foo-arch"
        )

        self._kb.CreateKernelImage("output")

        self.assertCommandCalled(
            [
                constants.CROSUTILS_DIR / "build_kernel_image.sh",
                "--board=foo-board",
                "--arch=foo-arch",
                "--to=output",
                "--vmlinuz=foo-root/boot/vmlinuz",
                f"--working_dir={self.tempdir}",
                "--keep_work",
                f"--keys_dir={constants.VBOOT_DEVKEYS_DIR}",
                f"--public={constants.KERNEL_PUBLIC_SUBKEY}",
                f"--private={constants.KERNEL_DATA_PRIVATE_KEY}",
                f"--keyblock={constants.KERNEL_KEYBLOCK}",
            ],
            enter_chroot=True,
        )

    def testCreateKernelImageWithArgs(self) -> None:
        """Tests CreateKernelImage() with default arguments."""
        self.rc.AddCmdResult(
            ["portageq-foo-board", "envvar", "ARCH"], stdout="foo-arch"
        )

        self._kb.CreateKernelImage(
            "output",
            keys_dir=constants.VBOOT_DEVKEYS_DIR,
            public_key=constants.RECOVERY_PUBLIC_KEY,
            private_key=constants.RECOVERY_DATA_PRIVATE_KEY,
            keyblock=constants.RECOVERY_KEYBLOCK,
            boot_args="x y=foo",
            serial="ttyfoo",
            disable_rootfs_verification=True,
        )

        self.assertCommandCalled(
            [
                constants.CROSUTILS_DIR / "build_kernel_image.sh",
                "--board=foo-board",
                "--arch=foo-arch",
                "--to=output",
                "--vmlinuz=foo-root/boot/vmlinuz",
                f"--working_dir={self.tempdir}",
                "--keep_work",
                f"--keys_dir={constants.VBOOT_DEVKEYS_DIR}",
                f"--public={constants.RECOVERY_PUBLIC_KEY}",
                f"--private={constants.RECOVERY_DATA_PRIVATE_KEY}",
                f"--keyblock={constants.RECOVERY_KEYBLOCK}",
                "--noenable_rootfs_verification",
                "--boot_args=x y=foo",
                "--enable_serial=ttyfoo",
            ],
            enter_chroot=True,
        )
