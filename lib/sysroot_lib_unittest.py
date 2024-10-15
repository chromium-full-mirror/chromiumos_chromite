# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the sysroot library."""

import os
from typing import Iterable, List, Optional, Tuple

from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import sysroot_lib
from chromite.lib import toolchain
from chromite.lib import unittest_lib
from chromite.lib.parser import package_info
from chromite.utils import os_util


class SysrootLibTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for sysroot_lib.py"""

    def setUp(self) -> None:
        """Setup the test environment."""
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        # Fake being root to avoid running all filesystem commands with
        # sudo_run.
        self.PatchObject(os_util, "is_root_user", return_value=True)
        sysroot_path = os.path.join(self.tempdir, "sysroot")
        osutils.SafeMakedirs(sysroot_path)
        self.sysroot = sysroot_lib.Sysroot(sysroot_path)
        self.relative_sysroot = sysroot_lib.Sysroot("sysroot")
        # make.conf needs to exist to correctly read back config.
        unittest_lib.create_stub_make_conf(sysroot_path)

    def testGetBaseArchBoard(self) -> None:
        """Tests that we can get the base arch board."""
        self.PatchObject(
            self.sysroot, "GetStandardField", return_value="test_arch"
        )
        self.PatchDict(
            sysroot_lib._ARCH_MAPPING,  # pylint: disable=protected-access
            {"test_arch": "test_board"},
        )
        self.assertEqual(self.sysroot.GetBaseArchBoard(), "test_board")

    def _writeOverlays(
        self,
        board_overlays: Optional[Iterable[str]] = None,
        portdir_overlays: Optional[Iterable[str]] = None,
        board: str = None,
    ) -> Tuple[List[str], List[str]]:
        """Helper function to write board and portdir overlays for the sysroot.

        By default, uses one fake board overlay, and the chromiumos and portage
        stable overlays. Set the arguments to an empty list to set no values for
        that field. When not explicitly set, |portdir_overlays| includes all
        values in |board_overlays|.

        Returns:
            The board overlays, and the portdir overlays.
        """
        if board_overlays is None:
            board_overlays = ["overlay/board"]
        if portdir_overlays is None:
            portdir_overlays = [
                constants.CHROMIUMOS_OVERLAY_DIR,
                constants.PORTAGE_STABLE_OVERLAY_DIR,
            ] + board_overlays

        board_overlays_field = sysroot_lib.STANDARD_FIELD_BOARD_OVERLAY
        portdir_field = sysroot_lib.STANDARD_FIELD_PORTDIR_OVERLAY
        board_field = sysroot_lib.STANDARD_FIELD_BOARD_USE

        board_values = [
            f"{constants.CHROOT_SOURCE_ROOT}/{x}" for x in board_overlays
        ]
        board_value = "\n".join(board_values)

        portdir_values = [
            f"{constants.CHROOT_SOURCE_ROOT}/{x}" for x in portdir_overlays
        ]
        portdir_value = "\n".join(portdir_values)

        config_values = {}
        if board_values:
            config_values[board_overlays_field] = board_value
        if portdir_values:
            config_values[portdir_field] = portdir_value
        if board:
            config_values[board_field] = board

        config = "\n".join(f'{k}="{v}"' for k, v in config_values.items())
        self.sysroot.WriteConfig(config)

        return board_values, portdir_values

    def testGetStandardField(self) -> None:
        """Tests that standard field can be fetched correctly."""
        self.sysroot.WriteConfig('FOO="bar"')
        self.assertEqual("bar", self.sysroot.GetStandardField("FOO"))

        # Works with multiline strings
        multiline = """foo
bar
baz
"""
        self.sysroot.WriteConfig('TEST="%s"' % multiline)
        self.assertEqual(multiline, self.sysroot.GetStandardField("TEST"))

    def testReadWriteCache(self) -> None:
        """Tests that we can write and read to the cache."""
        # If a field is not defined we get None.
        self.assertEqual(None, self.sysroot.GetCachedField("foo"))

        # If we set a field, we can get it.
        self.sysroot.SetCachedField("foo", "bar")
        self.assertEqual("bar", self.sysroot.GetCachedField("foo"))

        # Setting a field in an existing cache preserve the previous values.
        self.sysroot.SetCachedField("hello", "bonjour")
        self.assertEqual("bar", self.sysroot.GetCachedField("foo"))
        self.assertEqual("bonjour", self.sysroot.GetCachedField("hello"))

        # Setting a field to None unsets it.
        self.sysroot.SetCachedField("hello", None)
        self.assertEqual(None, self.sysroot.GetCachedField("hello"))

    def testErrorOnBadCachedValue(self) -> None:
        """Tests that we detect bad value for the sysroot cache."""
        forbidden = [
            'hello"bonjour',
            "hello\\bonjour",
            "hello\nbonjour",
            "hello$bonjour",
            "hello`bonjour",
        ]
        for value in forbidden:
            with self.assertRaises(ValueError):
                self.sysroot.SetCachedField("FOO", value)

    def testGenerateConfigNoToolchainRaisesError(self) -> None:
        """Tests _GenerateConfig() with no toolchain raises an error."""
        self.PatchObject(
            toolchain, "FilterToolchains", autospec=True, return_value={}
        )

        with self.assertRaises(sysroot_lib.ConfigurationError):
            # pylint: disable=protected-access
            self.sysroot._GenerateConfig(
                {}, ["foo_overlay"], ["foo_overlay"], "", use_internal=False
            )

    def testExists(self) -> None:
        """Tests the Exists method."""
        self.assertTrue(self.sysroot.Exists())

        dne_sysroot = sysroot_lib.Sysroot(os.path.join(self.tempdir, "DNE"))
        self.assertFalse(dne_sysroot.Exists())

    def testExistsInChroot(self) -> None:
        """Test the Exists method with a chroot."""
        chroot = chroot_lib.Chroot(self.tempdir, out_path=self.tempdir / "out")
        self.assertTrue(self.relative_sysroot.Exists(chroot=chroot))

    def testEquals(self) -> None:
        """Basic checks for the __eq__ methods."""
        sysroot1 = sysroot_lib.Sysroot(self.tempdir)
        sysroot2 = sysroot_lib.Sysroot(self.tempdir)
        self.assertEqual(sysroot1, sysroot2)
        self.assertNotEqual(sysroot1, None)

    def testProfileName(self) -> None:
        """Test the profile_name property when a value is set."""
        profile = "foo"
        self.sysroot.SetCachedField(
            sysroot_lib.CACHED_FIELD_PROFILE_OVERRIDE, profile
        )
        self.assertEqual(profile, self.sysroot.profile_name)

    def testProfileNameDefault(self) -> None:
        """Test the profile_name property when no value is set."""
        self.assertEqual(sysroot_lib.DEFAULT_PROFILE, self.sysroot.profile_name)

    def test_build_target(self) -> None:
        """Test the build_target property."""
        build_target = build_target_lib.BuildTarget(
            name="board", profile="profile", build_root=self.sysroot.path
        )
        self.sysroot.write_build_target_config(build_target)
        self.assertEqual(build_target, self.sysroot.build_target)

    def test_build_target_no_config(self) -> None:
        """Test the build_target raises exception when no config written."""
        with self.assertRaises(sysroot_lib.NoBuildTargetFileError):
            _ = self.sysroot.build_target

    def testBoardOverlay(self) -> None:
        """Test the board_overlay property."""
        board_overlays, _portdir_overlays = self._writeOverlays()

        self.assertEqual(
            sorted(board_overlays), sorted(self.sysroot.board_overlay)
        )

    def testBuildTargetOverlays(self) -> None:
        """Tests for populated _build_target_overlay[s]."""
        private = "/path/to/overlay-x-private"
        expected = ["/path/to/overlay-x", private]
        overlays = expected + ["/path/to/chromeos-overlay"]
        self._writeOverlays(overlays, board="x")

        # pylint: disable=protected-access
        results = [str(x) for x in self.sysroot._build_target_overlays]
        self.assertEqual(len(expected), len(results))
        for current in expected:
            self.assertTrue(any(result.endswith(current) for result in results))

        self.assertTrue(
            str(self.sysroot.build_target_overlay).endswith(private)
        )

    def testNoBuildTargetOverlay(self) -> None:
        """Test for no standard build target overlay."""
        self._writeOverlays(["/path/to/chromeos-overlay", "/path/to/chipset-x"])

        # pylint: disable=protected-access
        self.assertEqual(0, len(self.sysroot._build_target_overlays))
        self.assertIsNone(self.sysroot.build_target_overlay)

    def testChipset(self) -> None:
        """Test for extracting a valid chipset."""
        expected = "foo"
        chipsets = [
            f"/path/to/chipset-{expected}",
            f"/path/to/chipset-{expected}-private",
        ]
        all_overlays = chipsets + ["/path/to/chromeos-overlay"]
        self._writeOverlays(all_overlays)

        self.assertEqual(expected, self.sysroot.chipset)

    def testNoChipset(self) -> None:
        """Test for handling no retrievable chipset value."""
        self._writeOverlays(
            ["/path/to/chromeos-overlay", "/path/to/overlay-board"]
        )
        self.assertIsNone(self.sysroot.chipset)

    def testOverlays(self) -> None:
        """Test the overlays property."""
        _board_overlays, portdir_overlays = self._writeOverlays()

        self.assertEqual(portdir_overlays, self.sysroot.portdir_overlay)

    def testGetOverlays(self) -> None:
        """Test the get_overlays function."""
        board_overlays, portdir_overlays = self._writeOverlays()

        self.assertEqual(
            board_overlays,
            [str(x) for x in self.sysroot.get_overlays(build_target_only=True)],
        )
        self.assertEqual(
            portdir_overlays, [str(x) for x in self.sysroot.get_overlays()]
        )

    def testGetOverlaysRelative(self) -> None:
        portdir_overlays = [
            constants.CHROMIUMOS_OVERLAY_DIR,
            constants.PORTAGE_STABLE_OVERLAY_DIR,
        ]
        self._writeOverlays(portdir_overlays=portdir_overlays)

        self.assertEqual(
            portdir_overlays,
            [str(x) for x in self.sysroot.get_overlays(relative=True)],
        )


class ProfileTest(cros_test_lib.TestCase):
    """Tests for Profile."""

    def testEquality(self) -> None:
        """Test that equality functions work."""
        profile = sysroot_lib.Profile("profile")
        self.assertEqual(profile, sysroot_lib.Profile("profile"))
        self.assertNotEqual(profile, sysroot_lib.Profile("other"))
        self.assertNotEqual(profile, sysroot_lib.Profile(""))
        self.assertNotEqual(profile, None)


class SysrootLibInstallConfigTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for sysroot_lib.py"""

    # pylint: disable=protected-access

    def setUp(self) -> None:
        """Setup the test environment."""
        # Fake being root to avoid running all filesystem commands with
        # sudo_run.
        self.PatchObject(os_util, "is_root_user", return_value=True)
        self.sysroot = sysroot_lib.Sysroot(self.tempdir)
        self.make_conf_generic_target = os.path.join(
            self.tempdir, "make.conf.generic-target"
        )
        self.make_conf_user = os.path.join(self.tempdir, "make.conf.user")

        D = cros_test_lib.Directory
        filesystem = (
            D("etc", ()),
            "make.conf.generic-target",
            "make.conf.user",
        )

        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, filesystem)

    def testInstallMakeConf(self) -> None:
        """Test make.conf installation."""
        self.PatchObject(
            sysroot_lib,
            "_GetMakeConfGenericPath",
            return_value=self.make_conf_generic_target,
        )

        self.sysroot.InstallMakeConf(
            build_target_lib.BuildTarget("amd64-generic")
        )

        filepath = os.path.join(self.tempdir, sysroot_lib._MAKE_CONF)
        self.assertExists(filepath)

    def testInstallMakeConfBoard(self) -> None:
        """Test make.conf.board installation."""
        self.PatchObject(
            self.sysroot, "GenerateBoardMakeConf", return_value="#foo"
        )
        self.PatchObject(
            self.sysroot, "GenerateBinhostConf", return_value="#bar"
        )

        self.sysroot.InstallMakeConfBoard()

        filepath = os.path.join(self.tempdir, sysroot_lib._MAKE_CONF_BOARD)
        content = "#foo\n#bar\n"
        self.assertExists(filepath)
        self.assertFileContents(filepath, content)

    def testInstallMakeConfBoardSetup(self) -> None:
        """Test make.conf.board_setup installation."""
        self.PatchObject(
            self.sysroot, "GenerateBoardSetupConfig", return_value="#foo"
        )

        build_target = build_target_lib.BuildTarget("board")
        self.sysroot.InstallMakeConfBoardSetup(build_target)

        filepath = os.path.join(
            self.tempdir, sysroot_lib._MAKE_CONF_BOARD_SETUP
        )
        content = "#foo"
        self.assertExists(filepath)
        self.assertFileContents(filepath, content)

    def testInstallMakeConfUser(self) -> None:
        """Test make.conf.user installation."""
        self.PatchObject(
            sysroot_lib,
            "_GetChrootMakeConfUserPath",
            return_value=self.make_conf_user,
        )

        self.sysroot.InstallMakeConfUser()

        filepath = os.path.join(self.tempdir, sysroot_lib._MAKE_CONF_USER)
        self.assertExists(filepath)

    def test_write_build_target_config(self) -> None:
        """Test write_build_target_config."""
        target = build_target_lib.BuildTarget(name="board", profile="profile")
        self.sysroot.write_build_target_config(target)

        path = self.tempdir / sysroot_lib._BUILD_TARGET_CONFIG
        self.assertExists(path)

        retrieved = build_target_lib.BuildTarget.from_json(
            osutils.ReadFile(path, sudo=True)
        )

        assert retrieved == target == self.sysroot.build_target


class SysrootGenerateBinhostConfTest(cros_test_lib.MockTempDirTestCase):
    """Unittests for GenerateBinhostConf method in sysroot_lib.py"""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.PatchObject(os_util, "is_root_user", return_value=True)

        sysroot_path = os.path.join(self.tempdir, "sysroot")
        osutils.SafeMakedirs(sysroot_path)
        self.sysroot = sysroot_lib.Sysroot(sysroot_path)
        self.sysroot.WriteConfig('BOARD_USE="foofoo"')

        unittest_lib.create_stub_make_conf(sysroot_path)

        self.external_binhost_dir = os.path.join(
            self.tempdir,
            constants.PUBLIC_BINHOST_CONF_DIR,
            "target",
        )

        self.internal_binhost_file_path = os.path.join(
            self.tempdir,
            constants.PRIVATE_BINHOST_CONF_DIR,
            "target",
        )

        self.external_cq_binhost_file_path = os.path.join(
            self.external_binhost_dir, "foofoo-CQ_BINHOST.conf"
        )

        self.external_postsubmit_binhost_file_path = os.path.join(
            self.external_binhost_dir, "foofoo-POSTSUBMIT_BINHOST.conf"
        )

        self.internal_cq_binhost_file_path = os.path.join(
            self.internal_binhost_file_path, "foofoo-CQ_BINHOST.conf"
        )

        self.internal_postsubmit_binhost_file_path = os.path.join(
            self.internal_binhost_file_path, "foofoo-POSTSUBMIT_BINHOST.conf"
        )

    def _removeCommentAndEmptyLines(self, lines):
        # Remove comment and empty lines.
        return [
            line for line in lines if line != "" and not line.startswith("#")
        ]

    def testFullBinhost(self) -> None:
        config = self.sysroot.GenerateBinhostConf(source_root=self.tempdir)

        lines = self._removeCommentAndEmptyLines(config.splitlines())
        self.assertEqual(len(lines), 1)
        self.assertTrue('PORTAGE_BINHOST="$FULL_BINHOST"' in lines)

    def testCqBinhost(self) -> None:
        content = 'CQ_BINHOST="gs://bar/bar"'
        osutils.WriteFile(
            self.external_cq_binhost_file_path, content, makedirs=True
        )

        config = self.sysroot.GenerateBinhostConf(
            source_root=self.tempdir, use_cq_prebuilts=True
        )
        lines = self._removeCommentAndEmptyLines(config.splitlines())
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], 'PORTAGE_BINHOST="$FULL_BINHOST"')
        self.assertEqual(
            lines[1], f"source {self.external_cq_binhost_file_path}"
        )
        self.assertEqual(
            lines[2], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $CQ_BINHOST"'
        )

    def testPostsubmitBinhost(self) -> None:
        content = 'POSTSUBMIT_BINHOST="gs://bar/bar"'
        osutils.WriteFile(
            self.internal_postsubmit_binhost_file_path, content, makedirs=True
        )

        config = self.sysroot.GenerateBinhostConf(source_root=self.tempdir)
        lines = self._removeCommentAndEmptyLines(config.splitlines())
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0], 'PORTAGE_BINHOST="$FULL_BINHOST"')
        self.assertEqual(
            lines[1], f"source {self.internal_postsubmit_binhost_file_path}"
        )
        self.assertEqual(
            lines[2], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $POSTSUBMIT_BINHOST"'
        )

    def testAllBinhost(self) -> None:
        content = 'CQ_BINHOST="gs://bar/bar"'
        osutils.WriteFile(
            self.external_cq_binhost_file_path, content, makedirs=True
        )
        osutils.WriteFile(
            self.internal_cq_binhost_file_path, content, makedirs=True
        )
        content = 'POSTSUBMIT_BINHOST="gs://bar/bar"'
        osutils.WriteFile(
            self.external_postsubmit_binhost_file_path, content, makedirs=True
        )
        osutils.WriteFile(
            self.internal_postsubmit_binhost_file_path, content, makedirs=True
        )

        config = self.sysroot.GenerateBinhostConf(source_root=self.tempdir)
        lines = self._removeCommentAndEmptyLines(config.splitlines())
        self.assertEqual(len(lines), 5)
        self.assertEqual(lines[0], 'PORTAGE_BINHOST="$FULL_BINHOST"')
        self.assertEqual(
            lines[1], f"source {self.external_postsubmit_binhost_file_path}"
        )
        self.assertEqual(
            lines[2], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $POSTSUBMIT_BINHOST"'
        )
        self.assertEqual(
            lines[3], f"source {self.internal_postsubmit_binhost_file_path}"
        )
        self.assertEqual(
            lines[4], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $POSTSUBMIT_BINHOST"'
        )

    def testAllBinhostWithCqBinhosts(self) -> None:
        content = 'CQ_BINHOST="gs://bar/bar"'
        osutils.WriteFile(
            self.external_cq_binhost_file_path, content, makedirs=True
        )
        osutils.WriteFile(
            self.internal_cq_binhost_file_path, content, makedirs=True
        )
        content = 'POSTSUBMIT_BINHOST="gs://bar/bar"'
        osutils.WriteFile(
            self.external_postsubmit_binhost_file_path, content, makedirs=True
        )
        osutils.WriteFile(
            self.internal_postsubmit_binhost_file_path, content, makedirs=True
        )

        config = self.sysroot.GenerateBinhostConf(
            source_root=self.tempdir, use_cq_prebuilts=True
        )
        lines = self._removeCommentAndEmptyLines(config.splitlines())
        self.assertEqual(len(lines), 9)
        self.assertEqual(lines[0], 'PORTAGE_BINHOST="$FULL_BINHOST"')
        self.assertEqual(
            lines[1], f"source {self.external_postsubmit_binhost_file_path}"
        )
        self.assertEqual(
            lines[2], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $POSTSUBMIT_BINHOST"'
        )
        self.assertEqual(
            lines[3], f"source {self.internal_postsubmit_binhost_file_path}"
        )
        self.assertEqual(
            lines[4], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $POSTSUBMIT_BINHOST"'
        )
        # Note: Internal and external CQ binhosts are swapped.
        self.assertEqual(
            lines[5], f"source {self.internal_cq_binhost_file_path}"
        )
        self.assertEqual(
            lines[6], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $CQ_BINHOST"'
        )
        self.assertEqual(
            lines[7], f"source {self.external_cq_binhost_file_path}"
        )
        self.assertEqual(
            lines[8], 'PORTAGE_BINHOST="$PORTAGE_BINHOST $CQ_BINHOST"'
        )

    def test_binhost_overrides(self):
        """Test the binhost overrides."""
        overrides = [
            "gs://override/binhost1",
            "gs://override/binhost2",
        ]
        expected_binhosts = " ".join(overrides)
        expected = [
            f'LOOKUP_SERVICE_BINHOST="{expected_binhosts}"',
            'PORTAGE_BINHOST="$LOOKUP_SERVICE_BINHOST"',
        ]

        config = self.sysroot.GenerateBinhostConf(binhost_overrides=overrides)

        lines = self._removeCommentAndEmptyLines(config.splitlines())
        self.assertEqual(lines, expected)


class SysrootLibToolchainUpdateTest(cros_test_lib.RunCommandTempDirTestCase):
    """Sysroot.ToolchanUpdate tests."""

    def setUp(self) -> None:
        """Setup the test environment."""
        # Fake being root to avoid running commands with sudo_run.
        self.PatchObject(os_util, "is_root_user", return_value=True)

        # Avoid any logging functions that inpsect or change filesystem state.
        self.PatchObject(osutils, "rotate_log_file")

        self.sysroot = sysroot_lib.Sysroot(self.tempdir)
        self.emerge = constants.CHROMITE_BIN_DIR / "parallel_emerge"

    def testDefaultUpdateToolchain(self) -> None:
        """Test the default path."""
        self.PatchObject(toolchain, "InstallToolchain")

        self.sysroot.UpdateToolchain("board")
        self.assertCommandContains(
            [self.emerge, "--board=board", "--getbinpkg", "--usepkg"]
        )

    def testNoLocalInitUpdateToolchain(self) -> None:
        """Test the nousepkg and not local case."""
        self.PatchObject(toolchain, "InstallToolchain")

        self.sysroot.UpdateToolchain("board", local_init=False)
        self.assertCommandContains(["--getbinpkg", "--usepkg"], expected=False)
        self.assertCommandContains([self.emerge, "--board=board"])

    def testReUpdateToolchain(self) -> None:
        """Test behavior when not running for the first time."""
        self.PatchObject(toolchain, "InstallToolchain")

        self.PatchObject(
            self.sysroot, "IsToolchainInstalled", return_value=True
        )
        self.sysroot.UpdateToolchain("board")
        self.assertCommandContains([self.emerge], expected=False)

    def testInstallToolchainError(self) -> None:
        """Test error handling from the libc install."""
        failed = ["cat/pkg", "cat/pkg2"]
        failed_pkgs = [package_info.parse(pkg) for pkg in failed]
        result = cros_build_lib.CompletedProcess(returncode=1)
        error = toolchain.ToolchainInstallError(
            "Error", result=result, tc_info=failed_pkgs
        )
        self.PatchObject(toolchain, "InstallToolchain", side_effect=error)

        try:
            self.sysroot.UpdateToolchain("board")
        except sysroot_lib.ToolchainInstallError as e:
            self.assertTrue(e.failed_toolchain_info)
            self.assertEqual(failed_pkgs, e.failed_toolchain_info)
        except Exception as e:
            self.fail("Unexpected exception raised: %s" % type(e))
        else:
            self.fail("Expected an exception.")

    def testEmergeError(self) -> None:
        """Test the emerge error handling."""
        self.PatchObject(toolchain, "InstallToolchain")
        # pylint: disable=protected-access
        command = self.sysroot._UpdateToolchainCommand("board", True)

        err = cros_build_lib.RunCommandError(
            "Error", cros_build_lib.CompletedProcess(returncode=1)
        )
        self.rc.AddCmdResult(command, side_effect=err)

        with self.assertRaises(sysroot_lib.ToolchainInstallError):
            self.sysroot.UpdateToolchain("board", local_init=True)


def test_get_sdk_provided_packages(simple_sysroot) -> None:
    pkg_provided = simple_sysroot.path / "etc/portage/profile/package.provided"
    content = """
foo/bar-2-r3

# Comment line.
cat/pkg-1.0.0 # Comment after package.
"""
    osutils.WriteFile(pkg_provided, content, makedirs=True)
    pkgs = list(sysroot_lib.get_sdk_provided_packages(simple_sysroot.path))
    expected = [
        package_info.parse(p) for p in ("foo/bar-2-r3", "cat/pkg-1.0.0")
    ]
    assert pkgs == expected
