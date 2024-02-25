# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the binpkg.py module."""

import os
from pathlib import Path
from unittest import mock

from chromite.lib import binpkg
from chromite.lib import build_target_lib
from chromite.lib import cros_test_lib
from chromite.lib import gerrit
from chromite.lib import git
from chromite.lib import gs_unittest
from chromite.lib import osutils
from chromite.lib import patch as cros_patch
from chromite.lib import sysroot_lib


PACKAGES_CONTENT = """USE: test

CPV: chromeos-base/shill-0.0.1-r1

CPV: chromeos-base/test-0.0.1-r1
DEBUG_SYMBOLS: yes
"""


class FetchTarballsTest(cros_test_lib.MockTempDirTestCase):
    """Tests for GSContext that go over the network."""

    def testFetchFakePackages(self) -> None:
        """Pretend to fetch binary packages."""
        gs_mock = self.StartPatcher(gs_unittest.GSContextMock())
        gs_mock.SetDefaultCmdResult()
        uri = "gs://foo/bar"
        packages_uri = f"{uri}/Packages"
        packages_file = """URI: gs://foo

CPV: boo/baz
PATH boo/baz.tbz2
"""
        gs_mock.AddCmdResult(["cat", packages_uri], stdout=packages_file)

        binpkg.FetchTarballs([uri], self.tempdir)

    @cros_test_lib.pytestmark_network_test
    def testFetchRealPackages(self) -> None:
        """Actually fetch a real binhost from the network."""
        # pylint: disable=line-too-long
        uri = "gs://chromeos-prebuilt/board/lumpy/paladin-R37-5905.0.0-rc2/packages"
        # pylint: enable=line-too-long
        binpkg.FetchTarballs([uri], self.tempdir)


class DebugSymbolsTest(cros_test_lib.TempDirTestCase):
    """Tests for the debug symbols handling in binpkg."""

    def testDebugSymbolsDetected(self) -> None:
        """When generating the Packages file, DEBUG_SYMBOLS is updated."""
        osutils.WriteFile(
            os.path.join(
                self.tempdir, "chromeos-base/shill-0.0.1-r1.debug.tbz2"
            ),
            "hello",
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(self.tempdir, "Packages"), PACKAGES_CONTENT
        )

        index = binpkg.GrabLocalPackageIndex(self.tempdir)
        self.assertEqual(
            index.packages[0]["CPV"], "chromeos-base/shill-0.0.1-r1"
        )
        self.assertEqual(index.packages[0].get("DEBUG_SYMBOLS"), "yes")
        self.assertFalse("DEBUG_SYMBOLS" in index.packages[1])


class PackageIndexTest(cros_test_lib.TempDirTestCase):
    """Package index tests."""

    def testReadWrite(self) -> None:
        """Sanity check that the read and write method work properly."""
        packages1 = os.path.join(self.tempdir, "Packages1")
        packages2 = os.path.join(self.tempdir, "Packages2")

        # Set some data.
        pkg_index = binpkg.PackageIndex()
        pkg_index.header["A"] = "B"
        pkg_index.packages = [
            {
                "CPV": "foo/bar",
                "KEY": "value",
            },
            {
                "CPV": "cat/pkg",
                "KEY": "also_value",
            },
        ]

        # Write the package index files using each writing method.
        pkg_index.modified = True
        pkg_index.WriteFile(packages1)
        with open(packages2, "w", encoding="utf-8") as f:
            pkg_index.Write(f)
        tmpf = pkg_index.WriteToNamedTemporaryFile()

        # Make sure the files are the same.
        fc1 = osutils.ReadFile(packages1)
        fc2 = osutils.ReadFile(packages2)
        fc3 = tmpf.read()
        self.assertEqual(fc1, fc2)
        self.assertEqual(fc1, fc3)

        # Make sure it parses out the same data we wrote.
        with open(packages1, encoding="utf-8") as f:
            read_index = binpkg.PackageIndex()
            read_index.Read(f)

        self.assertDictEqual(pkg_index.header, read_index.header)
        self.assertCountEqual(pkg_index.packages, read_index.packages)


class PackageIndexInfoTest(cros_test_lib.TestCase):
    """Package index info tests."""

    def _make_instance(self, sha, number, board, profile_name, location):
        """Return a binpkg.PackageIndexInfo instance."""
        return binpkg.PackageIndexInfo(
            snapshot_sha=sha,
            snapshot_number=number,
            build_target=build_target_lib.BuildTarget(name=board)
            if board
            else None,
            profile=sysroot_lib.Profile(name=profile_name)
            if profile_name
            else None,
            location=location,
        )

    def testEquality(self) -> None:
        """Test that equality checks work."""
        info = self._make_instance("SHA5", 5, "target", "profile", "LOCATION")
        self.assertEqual(
            info,
            self._make_instance("SHA5", 5, "target", "profile", "LOCATION"),
        )
        self.assertNotEqual(
            info,
            self._make_instance("XXXX", 5, "target", "profile", "LOCATION"),
        )
        self.assertNotEqual(
            info,
            self._make_instance("SHA5", 6, "target", "profile", "LOCATION"),
        )
        self.assertNotEqual(
            info,
            self._make_instance("SHA5", 5, "xxxxxx", "profile", "LOCATION"),
        )
        self.assertNotEqual(
            info,
            self._make_instance("SHA5", 5, "target", "xxxxxxx", "LOCATION"),
        )
        self.assertNotEqual(
            info,
            self._make_instance("SHA5", 5, "target", "profile", "XXXXXXXX"),
        )


class UpdateAndSubmitKeyValueFileTest(cros_test_lib.MockTestCase):
    """Unit test for UpdateAndSubmitKeyValueFile."""

    def setUp(self):
        self.mock_gerrit_patch = mock.Mock(spec=cros_patch.GerritPatch)
        self.mock_gerrit_patch.PatchLink.return_value = "chromium:1234"
        self.gerrit_helper = mock.create_autospec(gerrit.GerritHelper)
        self.gerrit_helper.CreateGerritPatch.return_value = (
            self.mock_gerrit_patch
        )

        def fake_GetTrackingBranch(
            _path, _branch=None, for_checkout=True, for_push=False
        ):
            assert for_push, "only for_push==True is implemented in this fake"
            if for_checkout:
                return git.RemoteRef("cros", "refs/remotes/cros/main")
            else:
                return git.RemoteRef("cros", "refs/heads/main")

        self.PatchObject(
            binpkg.git,
            "GetTrackingBranch",
            side_effect=fake_GetTrackingBranch,
        )
        self.PatchObject(binpkg.git, "RunGit", autospec=True)
        self.PatchObject(
            binpkg.gerrit, "GetGerritHelper", return_value=self.gerrit_helper
        )
        self.PatchObject(binpkg, "key_value_store", autospec=True)

    def testDryRun(self):
        """Checks that dryrun=True is passed to gerrit_helper."""

        report = {}
        git_file = "somefile"
        abs_file = Path(git_file).absolute()

        binpkg.UpdateAndSubmitKeyValueFile(
            git_file,
            {"SDK_LATEST_VERSION": "2023.06.16.179334"},
            report,
            dryrun=True,
        )

        self.gerrit_helper.CreateGerritPatch.assert_called_once()
        self.assertEqual(
            list(sorted(report.setdefault("created_cls", []))),
            ["chromium:1234"],
        )
        binpkg.key_value_store.UpdateKeyInLocalFile.assert_called_once_with(
            abs_file,
            "SDK_LATEST_VERSION",
            "2023.06.16.179334",
        )
        binpkg.git.RunGit.assert_has_calls(
            [
                mock.call(abs_file.parent, ["add", abs_file.name]),
                mock.call(abs_file.parent, ["commit", "-m", mock.ANY]),
            ]
        )
        self.gerrit_helper.SetReview.assert_called_once_with(
            self.mock_gerrit_patch,
            labels={"Bot-Commit": 1},
            dryrun=True,
            notify="NONE",
        )
        self.gerrit_helper.SubmitChange.assert_called_once_with(
            self.mock_gerrit_patch,
            dryrun=True,
            notify="NONE",
        )

    def testWithReport(self):
        """Tests that created CL is listed in the report."""

        report = {}
        git_file = "chromiumos-overlay/chromeos/binhost/host/sdk_version.conf"
        abs_file = Path(git_file).absolute()
        data = {
            "SDK_LATEST_VERSION": "2023.06.15.171224",
            "TC_PATH": "2023/06/%(target)s-2023.06.15.171224.tar.xz",
        }

        binpkg.UpdateAndSubmitKeyValueFile(
            git_file,
            data,
            report,
        )

        self.gerrit_helper.CreateGerritPatch.assert_called_once()
        self.assertEqual(
            list(sorted(report.setdefault("created_cls", []))),
            ["chromium:1234"],
        )
        binpkg.key_value_store.UpdateKeyInLocalFile.assert_has_calls(
            [
                mock.call(
                    abs_file,
                    "SDK_LATEST_VERSION",
                    "2023.06.15.171224",
                ),
                mock.call(
                    abs_file,
                    "TC_PATH",
                    "2023/06/%(target)s-2023.06.15.171224.tar.xz",
                ),
            ],
            any_order=True,
        )
        binpkg.git.RunGit.assert_has_calls(
            [
                mock.call(
                    abs_file.parent, ["checkout", "-B", mock.ANY, "HEAD"]
                ),
                mock.call(
                    abs_file.parent,
                    ["branch", "--set-upstream-to", "cros/main"],
                ),
                mock.call(abs_file.parent, ["add", abs_file.name]),
                mock.call(abs_file.parent, ["commit", "-m", mock.ANY]),
            ]
        )
        self.gerrit_helper.SetReview.assert_called_once_with(
            self.mock_gerrit_patch,
            labels={"Bot-Commit": 1},
            dryrun=False,
            notify="NONE",
        )
        self.gerrit_helper.SubmitChange.assert_called_once_with(
            self.mock_gerrit_patch,
            dryrun=False,
            notify="NONE",
        )

    def testWithExistingReport(self):
        """Tests that created CL is added to an existing report."""

        report = {
            "created_cls": ["chromium:956"],
        }
        git_file = "chromeos/config/make.conf.amd64-host"
        abs_file = Path(git_file).absolute()
        data = {
            "FULL_BINHOST": "gs://test/host/test-2023.06.15.171224/packages/",
        }

        binpkg.UpdateAndSubmitKeyValueFile(
            git_file,
            data,
            report,
        )

        self.gerrit_helper.CreateGerritPatch.assert_called_once()
        self.assertEqual(
            list(sorted(report.setdefault("created_cls", []))),
            ["chromium:1234", "chromium:956"],
        )
        binpkg.key_value_store.UpdateKeyInLocalFile.assert_called_once_with(
            abs_file,
            "FULL_BINHOST",
            "gs://test/host/test-2023.06.15.171224/packages/",
        )
        binpkg.git.RunGit.assert_has_calls(
            [
                mock.call(
                    abs_file.parent, ["checkout", "-B", mock.ANY, "HEAD"]
                ),
                mock.call(
                    abs_file.parent,
                    ["branch", "--set-upstream-to", "cros/main"],
                ),
                mock.call(abs_file.parent, ["add", abs_file.name]),
                mock.call(abs_file.parent, ["commit", "-m", mock.ANY]),
            ]
        )
        self.gerrit_helper.SetReview.assert_called_once_with(
            self.mock_gerrit_patch,
            labels={"Bot-Commit": 1},
            dryrun=False,
            notify="NONE",
        )
        self.gerrit_helper.SubmitChange.assert_called_once_with(
            self.mock_gerrit_patch,
            dryrun=False,
            notify="NONE",
        )
