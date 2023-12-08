# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""chroot_lib unit tests."""

import os
from unittest import mock

from chromite.lib import chroot_lib
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import remoteexec_util


class ChrootTest(cros_test_lib.MockTempDirTestCase):
    """Chroot class tests."""

    def setUp(self) -> None:
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)
        self.chroot_path = self.tempdir / "chroot"
        self.out_path = self.tempdir / "out"
        osutils.SafeMakedirs(self.chroot_path)
        osutils.SafeMakedirs(self.out_path)

    def testGetEnterArgsEmpty(self) -> None:
        """Test empty instance behavior."""
        chroot = chroot_lib.Chroot()
        self.assertFalse(chroot.get_enter_args())

    def testGetEnterArgsAll(self) -> None:
        """Test complete instance behavior."""
        path = "/chroot/path"
        out_path = "/chroot/out"
        cache_dir = "/cache/dir"
        chrome_root = "/chrome/root"
        expected = [
            "--chroot",
            path,
            "--out-dir",
            out_path,
            "--cache-dir",
            cache_dir,
            "--chrome-root",
            chrome_root,
        ]

        reclient_dir = self.tempdir / "cipd" / "rbe"
        osutils.SafeMakedirs(reclient_dir)
        reproxy_cfg_file = self.tempdir / "reclient_cfgs" / "reproxy_config.cfg"
        osutils.Touch(reproxy_cfg_file, makedirs=True)
        remoteexec = remoteexec_util.Remoteexec(
            reclient_dir=reclient_dir, reproxy_cfg_file=reproxy_cfg_file
        )
        expected.extend(
            [
                "--reproxy-cfg-file",
                str(reclient_dir),
                "--reclient-dir",
                str(reproxy_cfg_file),
            ]
        )

        chroot = chroot_lib.Chroot(
            path=path,
            out_path=out_path,
            cache_dir=cache_dir,
            chrome_root=chrome_root,
            remoteexec=remoteexec,
        )

        self.assertCountEqual(expected, chroot.get_enter_args())

    def testEnv(self) -> None:
        """Test the env handling."""
        env = {"VAR": "val"}
        chroot = chroot_lib.Chroot(env=env)
        self.assertEqual(env, chroot.env)

    def testEnvRemoteexec(self) -> None:
        reclient_dir = os.path.join(self.tempdir, "cipd/rbe")
        osutils.SafeMakedirs(reclient_dir)
        reproxy_cfg_file = os.path.join(
            self.tempdir, "reclient_cfgs/reproxy_config.cfg"
        )
        osutils.SafeMakedirs(reproxy_cfg_file)
        remoteexec = remoteexec_util.Remoteexec(
            reclient_dir=reclient_dir, reproxy_cfg_file=reproxy_cfg_file
        )

        chroot = chroot_lib.Chroot(remoteexec=remoteexec)
        self.assertEndsWith(chroot.env["RECLIENT_DIR"], "/reclient")
        self.assertEndsWith(chroot.env["REPROXY_CFG"], "/reproxy_chroot.cfg")

    def testTempdir(self) -> None:
        """Test the tempdir functionality."""
        chroot = chroot_lib.Chroot(
            path=self.chroot_path, out_path=self.out_path
        )
        osutils.SafeMakedirs(chroot.tmp)

        self.assertEqual(os.path.join(self.out_path, "tmp"), chroot.tmp)

        with chroot.tempdir() as tempdir:
            self.assertStartsWith(tempdir, chroot.tmp)

        self.assertNotExists(tempdir)

    def testExists(self) -> None:
        """Test chroot exists."""
        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)
        self.assertTrue(chroot.exists())

        chroot = chroot_lib.Chroot(
            self.chroot_path / "DOES_NOT_EXIST", out_path=self.out_path
        )
        self.assertFalse(chroot.exists())

    def testChrootPath(self) -> None:
        """Test chroot_path functionality."""
        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)
        path1 = self.chroot_path / "some/path"
        path2 = "/bad/path"

        # Make sure that it gives an absolute path inside the chroot.
        self.assertEqual("/some/path", chroot.chroot_path(path1))
        # Make sure it raises an error for paths not inside the chroot.
        self.assertRaises(ValueError, chroot.chroot_path, path2)

    def testFullPath(self) -> None:
        """Test full_path functionality."""
        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)

        # Make sure it's building out the path in the chroot.
        self.assertEqual(
            str(self.chroot_path / "some/path"),
            chroot.full_path("/some/path"),
        )

    def testRelativePath(self) -> None:
        """Test relative path functionality."""
        self.PatchObject(os, "getcwd", return_value="/path/to/workspace")
        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)

        # Relative paths are assumed to be rooted in the chroot
        self.assertEqual(
            os.path.join(self.chroot_path, "some/path"),
            chroot.full_path("some/path"),
        )

    def testFullPathWithExtraArgs(self) -> None:
        """Test full_path functionality with extra args passed."""
        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)
        self.assertEqual(
            os.path.join(self.chroot_path, "some/path/abc/def/g/h/i"),
            chroot.full_path("/some/path", "abc", "def", "g/h/i"),
        )

    def testHasPathSuccess(self) -> None:
        """Test has path for a valid path."""
        tempdir_path = self.chroot_path / "some/file.txt"
        osutils.Touch(tempdir_path, makedirs=True)

        chroot = chroot_lib.Chroot(
            path=self.chroot_path, out_path=self.out_path
        )
        self.assertTrue(chroot.has_path("/some/file.txt"))

    def testHasPathInvalidPath(self) -> None:
        """Test has path for a non-existent path."""
        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)
        self.assertFalse(chroot.has_path("/does/not/exist"))

    def testHasPathVariadic(self) -> None:
        """Test multiple args to has path."""
        path = ["some", "file.txt"]
        tempdir_path = os.path.join(self.chroot_path, *path)
        osutils.Touch(tempdir_path, makedirs=True)

        chroot = chroot_lib.Chroot(self.chroot_path, out_path=self.out_path)
        self.assertTrue(chroot.has_path("/some", "file.txt"))

    def testEqual(self) -> None:
        """__eq__ method check."""
        path = "/chroot/path"
        out_path = "/out/path"
        cache_dir = "/cache/dir"
        chrome_root = "/chrome/root"
        env = {"USE": "useflag", "FEATURES": "feature"}
        chroot1 = chroot_lib.Chroot(
            path=path, cache_dir=cache_dir, chrome_root=chrome_root, env=env
        )
        chroot2 = chroot_lib.Chroot(
            path=path, cache_dir=cache_dir, chrome_root=chrome_root, env=env
        )
        chroot3 = chroot_lib.Chroot(path=path)
        chroot4 = chroot_lib.Chroot(path=path)
        chroot5 = chroot_lib.Chroot(out_path=out_path)
        chroot6 = chroot_lib.Chroot(out_path=out_path)

        self.assertEqual(chroot1, chroot2)
        self.assertEqual(chroot3, chroot4)
        self.assertEqual(chroot5, chroot6)
        self.assertNotEqual(chroot1, chroot3)
        self.assertNotEqual(chroot1, chroot5)
        self.assertNotEqual(chroot3, chroot5)


def test_tarball_version(tmp_path, outside_sdk) -> None:
    """Test chroot.tarball_version."""
    del outside_sdk
    chroot = chroot_lib.Chroot(path=tmp_path)
    osutils.WriteFile(
        tmp_path / "etc" / "os-release",
        "BUILD_ID=1234_56",
        makedirs=True,
    )
    assert chroot.tarball_version == "1234_56"


def test_tarball_version_missing(tmp_path, outside_sdk) -> None:
    """Test chroot.tarball_version on a chroot missing /etc/os-release."""
    del outside_sdk
    chroot = chroot_lib.Chroot(path=tmp_path)
    assert chroot.tarball_version is None


class ChrootRunTest(cros_test_lib.RunCommandTempDirTestCase):
    """Chroot tests with mock run()."""

    def setUp(self) -> None:
        self.chroot = chroot_lib.Chroot(
            path=self.tempdir / "chroot", out_path=self.tempdir / "out"
        )

    def testRunSimple(self) -> None:
        """With simple params."""
        self.chroot.run(["./foo", "bar"])
        self.assertCommandContains(
            ["./foo", "bar"],
            enter_chroot=True,
            chroot_args=[
                "--chroot",
                str(self.tempdir / "chroot"),
                "--out-dir",
                str(self.tempdir / "out"),
            ],
            extra_env={},
        )

    def testRunExtraEnv(self) -> None:
        """With extra_env dictionary."""
        self.chroot.run(["cat", "dog"], extra_env={"USE": "antigravity"})
        self.assertCommandContains(
            ["cat", "dog"],
            enter_chroot=True,
            chroot_args=[
                "--chroot",
                str(self.tempdir / "chroot"),
                "--out-dir",
                str(self.tempdir / "out"),
            ],
            extra_env={"USE": "antigravity"},
        )

    def testExtraEnvNone(self) -> None:
        """With extra_env=None."""
        self.chroot.run(["cat"], extra_env=None)
        self.assertCommandContains(
            ["cat"], enter_chroot=True, chroot_args=mock.ANY, extra_env={}
        )

    def testChrootArgs(self) -> None:
        """With additional supplied chroot_args."""
        self.chroot.run(["cat"], chroot_args=["--no-read-only"])
        self.assertCommandContains(
            ["cat"],
            enter_chroot=True,
            chroot_args=self.chroot.get_enter_args() + ["--no-read-only"],
            extra_env={},
        )
