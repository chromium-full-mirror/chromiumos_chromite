# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for SDK stages."""

import json
import os
from pathlib import Path

from chromite.cbuildbot import cbuildbot_unittest
from chromite.cbuildbot import commands
from chromite.cbuildbot.stages import generic_stages
from chromite.cbuildbot.stages import generic_stages_unittest
from chromite.cbuildbot.stages import sdk_stages
from chromite.lib import binpkg
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import perf_uploader
from chromite.lib import portage_util
from chromite.lib.buildstore import FakeBuildStore
from chromite.lib.parser import package_info


class SDKBuildToolchainsStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cbuildbot_unittest.SimpleBuilderTestCase,
):
    """Tests SDK toolchain building."""

    RELEASE_TAG = "ToT.0.0"

    def setUp(self):
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.buildstore = FakeBuildStore()
        # This code has its own unit tests, so no need to go testing it here.
        self.run_mock = self.PatchObject(commands, "RunBuildScript")
        self.uploadartifact_mock = self.PatchObject(
            generic_stages.ArchivingStageMixin, "UploadArtifact"
        )

    def ConstructStage(self):
        self._run.GetArchive().SetupArchivePath()
        return sdk_stages.SDKBuildToolchainsStage(self._run, self.buildstore)

    def testNormal(self):
        """Basic run through the main code."""
        self._Prepare("chromiumos-sdk")
        self.PatchObject(
            os,
            "listdir",
            return_value=[
                "i686-pc.tar.xz",
                "x86_64-cros.tar.xz",
            ],
        )
        self.RunStage()
        self.assertEqual(self.run_mock.call_count, 2)
        self.assertEqual(self.uploadartifact_mock.call_count, 2)

        # Sanity check args passed to RunBuildScript.
        for call in self.run_mock.call_args_list:
            buildroot, cmd = call[0]
            self.assertIsInstance(buildroot, str)
            self.assertIsInstance(cmd, (tuple, list))
            for ele in cmd:
                self.assertIsInstance(ele, str)


class SDKPackageStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cbuildbot_unittest.SimpleBuilderTestCase,
):
    """Tests SDK package and Manifest creation."""

    RELEASE_TAG = "ToT.0.0"
    fake_packages = (
        ("cat1/package", "1"),
        ("cat1/package", "2"),
        ("cat2/package", "3"),
        ("cat2/package", "4"),
    )

    def setUp(self):
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        self.buildstore = FakeBuildStore()
        # Replace sudo_run, since we don't care about sudo.
        self.PatchObject(osutils, "IsRootUser", return_value=True)
        # Don't run CleanupMakeConfBoardSetup as it needs sudo_run.
        self.PatchObject(
            sdk_stages.SDKPackageStage, "CleanupMakeConfBoardSetup"
        )
        self.uploadartifact_mock = self.PatchObject(
            generic_stages.ArchivingStageMixin, "UploadArtifact"
        )
        # Prepare a fake chroot.
        fake_sysroot_path = path_util.FromChrootPath(
            "/build/amd64-host",
            source_path=self.build_root,
        )
        self.fake_json_data = {}
        osutils.SafeMakedirs(fake_sysroot_path)
        osutils.Touch(os.path.join(fake_sysroot_path, "file"))
        for package, v in self.fake_packages:
            cpv = package_info.SplitCPV("%s-%s" % (package, v))
            self.fake_json_data.setdefault(cpv.cp, []).append([v, {}])

    def ConstructStage(self):
        self._run.GetArchive().SetupArchivePath()
        return sdk_stages.SDKPackageStage(self._run, self.buildstore)

    def testTarballCreation(self):
        """Tests if we package the tarball and correctly create a Manifest."""
        # We'll test this separately.
        self.PatchObject(sdk_stages.SDKPackageStage, "_SendPerfValues")

        self._Prepare("chromiumos-sdk")
        fake_tarball = os.path.join(self.build_root, constants.SDK_TARBALL_NAME)
        fake_manifest = os.path.join(
            self.build_root, f"{constants.SDK_TARBALL_NAME}.Manifest"
        )

        self.PatchObject(
            portage_util,
            "ListInstalledPackages",
            return_value=self.fake_packages,
        )

        self.RunStage()

        # Check tarball for the correct contents.
        output = cros_build_lib.run(
            ["tar", "-I", "xz", "-tvf", fake_tarball],
            encoding="utf-8",
            capture_output=True,
        ).stdout.splitlines()
        # First line is './', use it as an anchor, count the chars, and strip as
        # much from all other lines.
        stripchars = len(output[0]) - 1
        tar_lines = [x[stripchars:] for x in output]
        self.assertNotIn("/build/amd64-host/", tar_lines)
        self.assertIn("/file", tar_lines)
        # Verify manifest contents.
        real_json_data = json.loads(osutils.ReadFile(fake_manifest))
        self.assertEqual(real_json_data["packages"], self.fake_json_data)
        self.uploadartifact_mock.assert_called_once_with(
            fake_tarball, strict=True, archive=True
        )

    def testPerf(self):
        """Check perf data points are generated/uploaded."""
        m = self.PatchObject(perf_uploader, "UploadPerfValues")

        sdk_data = "asldjfasf"
        sdk_size = len(sdk_data)
        sdk_tarball = os.path.join(self.tempdir, "sdk.tar.xz")
        osutils.WriteFile(sdk_tarball, sdk_data)

        tarball_dir = path_util.FromChrootPath(
            os.path.join(
                os.path.sep,
                constants.SDK_TOOLCHAINS_OUTPUT,
            ),
            source_path=self.tempdir,
        )
        arm_tar = os.path.join(tarball_dir, "arm-cros-linux-gnu.tar.xz")
        x86_tar = os.path.join(tarball_dir, "i686-pc-linux-gnu.tar.xz")
        osutils.Touch(arm_tar, makedirs=True)
        osutils.Touch(x86_tar, makedirs=True)

        self._Prepare("chromiumos-sdk")
        stage = self.ConstructStage()
        # pylint: disable=protected-access
        stage._SendPerfValues(
            self.tempdir, sdk_tarball, "http://some/log", "123.4.5.6", "sdk-bot"
        )
        # pylint: enable=protected-access

        perf_values = m.call_args[0][0]
        exp = perf_uploader.PerformanceValue(
            description="base",
            value=sdk_size,
            units="bytes",
            higher_is_better=False,
            graph="cros-sdk-size",
            stdio_uri="http://some/log",
        )
        self.assertEqual(exp, perf_values[0])

        exp = set(
            (
                perf_uploader.PerformanceValue(
                    description="arm-cros-linux-gnu",
                    value=0,
                    units="bytes",
                    higher_is_better=False,
                    graph="cros-sdk-size",
                    stdio_uri="http://some/log",
                ),
                perf_uploader.PerformanceValue(
                    description="i686-pc-linux-gnu",
                    value=0,
                    units="bytes",
                    higher_is_better=False,
                    graph="cros-sdk-size",
                    stdio_uri="http://some/log",
                ),
                perf_uploader.PerformanceValue(
                    description="base_plus_arm-cros-linux-gnu",
                    value=sdk_size,
                    units="bytes",
                    higher_is_better=False,
                    graph="cros-sdk-size",
                    stdio_uri="http://some/log",
                ),
                perf_uploader.PerformanceValue(
                    description="base_plus_i686-pc-linux-gnu",
                    value=sdk_size,
                    units="bytes",
                    higher_is_better=False,
                    graph="cros-sdk-size",
                    stdio_uri="http://some/log",
                ),
            )
        )
        self.assertEqual(exp, set(perf_values[1:]))

        platform_name = m.call_args[0][1]
        self.assertEqual(platform_name, "sdk-bot")

        test_name = m.call_args[0][2]
        self.assertEqual(test_name, "sdk")

        kwargs = m.call_args[1]
        self.assertEqual(kwargs["revision"], 123456)


class SDKTestStageTest(
    generic_stages_unittest.AbstractStageTestCase,
    cros_test_lib.RunCommandTestCase,
):
    """Tests SDK test phase."""

    def setUp(self):
        self.buildstore = FakeBuildStore()

    def ConstructStage(self):
        return sdk_stages.SDKTestStage(self._run, self.buildstore)

    def testNormal(self):
        """Basic run through the main code."""
        self._Prepare("chromiumos-sdk")
        self.RunStage()


class SDKUprevStageTest(generic_stages_unittest.AbstractStageTestCase):
    """Tests SDK Uprev stage."""

    _VERSION = "2017.09.01.155318"

    def ConstructStage(self):
        return sdk_stages.SDKUprevStage(
            self._run, self.buildstore, version=self._VERSION
        )

    def testUprev(self):
        self.PatchObject(cros_build_lib, "IsInsideChroot", return_value=False)

        recorded_args = []
        self.PatchObject(
            binpkg,
            "UpdateAndSubmitKeyValueFile",
            lambda *args, **kwargs: recorded_args.append(args),
        )

        out_dir = path_util.FromChrootPath(
            Path("/") / "tmp" / "toolchain-pkgs", source_path=self.build_root
        )
        osutils.SafeMakedirs(out_dir)
        osutils.Touch(os.path.join(out_dir, "fake_sdk.tar.xz"))

        self._Prepare("chromiumos-sdk")

        self.RunStage()
        # binpkg.UpdateAndSubmitKeyValueFile should be called exactly once.
        self.assertEqual(1, len(recorded_args))
        sdk_conf, sdk_settings = recorded_args[0]
        self.assertEqual(
            sdk_conf,
            os.path.join(
                self.build_root,
                "src",
                "third_party",
                "chromiumos-overlay",
                "chromeos",
                "binhost",
                "host",
                "sdk_version.conf",
            ),
        )
        self.assertEqual(
            sdk_settings,
            {
                "SDK_LATEST_VERSION": self._VERSION,
                "TC_PATH": "2017/09/%(target)s-2017.09.01.155318.tar.xz",
            },
        )


class SDKUtilTest(cros_test_lib.RunCommandTempDirTestCase):
    """Tests various utility functions."""

    def testCreateTarballBasic(self):
        """Basic sanity checks for CreateTarball."""
        sdk_stages.CreateTarball(self.tempdir, "/chromite.tar")
        self.assertCommandContains(["tar", "/chromite.tar", "."])

    def testCreateTarballExclude(self):
        """Verify CreateTarball exclude_path handling."""
        sdk_stages.CreateTarball(
            self.tempdir,
            "/chromite.tar",
            exclude_paths=["tmp", "usr/lib/debug"],
        )
        self.assertCommandContains(
            [
                "tar",
                "--anchored",
                "--exclude=./tmp/*",
                "--exclude=./usr/lib/debug/*",
                "/chromite.tar",
                ".",
            ]
        )
