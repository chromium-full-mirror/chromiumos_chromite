# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests the chroot_util module."""

import itertools
from unittest import mock

import pytest

from chromite.lib import chroot_util
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib


pytestmark = pytest.mark.inside_only

if cros_build_lib.IsInsideChroot():
    from chromite.scripts import cros_list_modified_packages


class ChrootUtilTest(cros_test_lib.RunCommandTempDirTestCase):
    """Test class for the chroot_util functions."""

    def testEmerge(self) -> None:
        """Tests correct invocation of emerge."""
        packages = ["foo-app/bar", "sys-baz/clap"]
        self.PatchObject(
            cros_list_modified_packages,
            "ListModifiedWorkonPackages",
            return_value=[packages[0]],
        )

        toolchain_packages = [
            "sys-devel/binutils",
            "sys-devel/gcc",
            "sys-kernel/linux-headers",
            "sys-libs/glibc",
            "sys-devel/gdb",
        ]
        self.PatchObject(
            chroot_util,
            "_GetToolchainPackages",
            return_value=toolchain_packages,
        )
        toolchain_package_list = " ".join(toolchain_packages)

        input_values = [
            ["/", "/build/thesysrootname"],  # sysroot
            [True, False],  # with_deps
            [True, False],  # rebuild_deps
            [True, False],  # use_binary
            [0, 1, 2, 3],  # jobs
            [True, False],  # debug_output
        ]
        inputs = itertools.product(*input_values)
        for (
            sysroot,
            with_deps,
            rebuild_deps,
            use_binary,
            jobs,
            debug_output,
        ) in inputs:
            chroot_util.Emerge(
                packages,
                sysroot=sysroot,
                with_deps=with_deps,
                rebuild_deps=rebuild_deps,
                use_binary=use_binary,
                jobs=jobs,
                debug_output=debug_output,
            )
            cmd = self.rc.call_args_list[-1][0][-1]
            self.assertEqual(
                sysroot != "/", any(str(p).startswith("--sysroot") for p in cmd)
            )
            self.assertEqual(with_deps, "--deep" in cmd)
            self.assertEqual(not with_deps, "--nodeps" in cmd)
            self.assertEqual(rebuild_deps, "--rebuild-if-unbuilt" in cmd)
            self.assertEqual(use_binary, "-g" in cmd)
            self.assertEqual(use_binary, "--with-bdeps=y" in cmd)
            self.assertEqual(
                use_binary and sysroot == "/",
                "--useoldpkg-atoms=%s" % toolchain_package_list in cmd,
            )
            self.assertEqual(bool(jobs), "--jobs=%d" % jobs in cmd)
            self.assertEqual(debug_output, "--show-output" in cmd)

    @pytest.mark.usefixtures("as_root_user")
    def testRunUnittests(self) -> None:
        """Tests running unit tests invoking emerge with provided flags"""
        sysroot = self.tempdir / "sysroot"
        (sysroot / "etc" / "portage").mkdir(parents=True)
        chroot_util.RunUnittests(
            sysroot=str(sysroot),
            packages=["package1", "package2"],
            extra_env={
                "USE": "chrome_internal coverage",
                "FEATURES": "noclean",
            },
            keep_going=True,
        )
        self.rc.assertCommandCalled(
            [
                constants.CHROMITE_BIN_DIR / "parallel_emerge",
                f"--sysroot={sysroot}",
                "--keep-going=y",
                "package1",
                "package2",
            ],
            extra_env={
                "USE": "chrome_internal coverage",
                "FEATURES": "noclean",
                "PKGDIR": f"{sysroot}/tmp/test-packages",
                "PORTAGE_CONFIGROOT": mock.ANY,
            },
        )

    def testSetUpTestPortageConfig(self) -> None:
        """Tests the setup of temporary PORTAGE_CONFIGROOT."""
        # pylint: disable=protected-access
        sysroot = self.tempdir / "sysroot"
        temp_config = self.tempdir / "temp_config"
        temp_config.mkdir()

        # Should crash if /etc/portage does not exist in sysroot.
        with pytest.raises(FileNotFoundError):
            chroot_util._SetUpTestPortageConfig(
                temp_config, sysroot, {"foo-app/bar"}
            )

        # Populate mock sysroot configuration.
        sysroot_portage = sysroot / "etc" / "portage"
        sysroot_env = sysroot_portage / "env"
        sysroot_env.mkdir(parents=True)
        (sysroot / "etc" / "make.conf").write_text(
            "CFLAGS=-O2", encoding="utf-8"
        )
        (sysroot_portage / "make.profile").write_text(
            "profile", encoding="utf-8"
        )
        (sysroot_env / "custom.env").write_text("FOO=1", encoding="utf-8")
        (sysroot_portage / "package.env").write_text(
            "sys-kernel/chromeos-kernel-5_15 kernel.env\n", encoding="utf-8"
        )

        temp_config2 = self.tempdir / "temp_config2"
        temp_config2.mkdir()
        chroot_util._SetUpTestPortageConfig(
            temp_config2, sysroot, {"foo-app/bar"}
        )

        etc_dir = temp_config2 / "etc"
        portage_dir = etc_dir / "portage"
        env_dir = portage_dir / "env"

        self.assertEqual(
            (etc_dir / "make.conf").read_text(encoding="utf-8"), "CFLAGS=-O2"
        )
        self.assertEqual(
            (portage_dir / "make.profile").read_text(encoding="utf-8"),
            "profile",
        )
        self.assertEqual(
            (env_dir / "custom.env").read_text(encoding="utf-8"), "FOO=1"
        )
        self.assertEqual(
            (env_dir / "no_tests.env").read_text(encoding="utf-8"),
            'FEATURES="-test"\n',
        )
        self.assertEqual(
            (env_dir / "enable_tests.env").read_text(encoding="utf-8"),
            'FEATURES="test"\n',
        )

        expected_package_env = (
            "sys-kernel/chromeos-kernel-5_15 kernel.env\n"
            "*/* no_tests.env\n"
            "foo-app/bar enable_tests.env\n"
        )
        self.assertEqual(
            (portage_dir / "package.env").read_text(encoding="utf-8"),
            expected_package_env,
        )
