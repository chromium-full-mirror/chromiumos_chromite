# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for cros_mark_as_stable.py."""

import os
from unittest import mock

import pytest

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import parallel_unittest
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import repo_util
from chromite.scripts import cros_mark_as_stable


pytestmark = pytest.mark.inside_only


class EbuildMock:
    """Mock portage_util.Ebuild."""

    def __init__(self, path, new_package=True) -> None:
        self.path = path
        self.package = "%s_package" % path
        self.cros_workon_vars = "cros_workon_vars"
        self._new_package = new_package

    # pylint: disable=unused-argument
    def RevWorkOnEBuild(self, srcroot, manifest, reject_self_repo=True):
        if self._new_package:
            return (
                "%s_new_package" % self.path,
                "%s_new_ebuild" % self.path,
                "%s_old_ebuild" % self.path,
            )


# pylint: disable=protected-access
class MarkAsStableCMDTest(cros_test_lib.MockTempDirTestCase):
    """Test cros_mark_as_stable commands."""

    def setUp(self) -> None:
        self._manifest = "manifest"
        self._parser = cros_mark_as_stable.GetParser()
        self._package_list = ["pkg1"]

        self._overlays = [
            os.path.join(self.tempdir, "overlay_%s" % i) for i in range(0, 3)
        ]

        self._overlay_remote_ref = {
            self._overlays[0]: git.RemoteRef("remote", "ref", "project_1"),
            self._overlays[1]: git.RemoteRef("remote", "ref", "project_1"),
            self._overlays[2]: git.RemoteRef("remote", "ref", "project_2"),
        }

        self._git_project_overlays = {}
        self._overlay_tracking_branch = {}
        for overlay in self._overlays:
            self._git_project_overlays.setdefault(
                self._overlay_remote_ref[overlay], []
            ).append(overlay)
            self._overlay_tracking_branch[overlay] = self._overlay_remote_ref[
                overlay
            ].ref

        self.PatchObject(git, "GetTrackingBranchViaManifest")
        # TODO: Remove explicit --buildroot after --srcroot remove and a normal
        #       default is set.
        self._commit_options = self._parser.parse_args(
            ["commit", "--buildroot", str(constants.SOURCE_ROOT)]
        )

    def testWorkOnCommit(self) -> None:
        """Test _WorkOnCommit."""
        self.PatchObject(parallel, "RunTasksInProcessPool")
        self.PatchObject(cros_mark_as_stable, "_CommitOverlays")
        self.PatchObject(
            cros_mark_as_stable, "_GetOverlayToEbuildsMap", return_value={}
        )

        cros_mark_as_stable._WorkOnCommit(
            self._commit_options,
            self._overlays,
            self._overlay_tracking_branch,
            self._git_project_overlays,
            self._manifest,
            self._package_list,
        )

    def testGetOverlayToEbuildsMap(self) -> None:
        """Test _GetOverlayToEbuildsMap."""
        self.PatchObject(
            portage_util, "GetOverlayEBuilds", return_value=["ebuild"]
        )

        expected_overlay_dicts = {
            overlay: ["ebuild"] for overlay in self._overlays
        }
        overlay_ebuilds = cros_mark_as_stable._GetOverlayToEbuildsMap(
            self._commit_options, self._overlays, self._package_list
        )
        self.assertCountEqual(expected_overlay_dicts, overlay_ebuilds)

    def testCommitOverlays(self) -> None:
        """Test _CommitOverlays."""
        mock_run_process_pool = self.PatchObject(
            parallel, "RunTasksInProcessPool"
        )
        self.PatchObject(os.path, "isdir", return_value=True)
        self.PatchObject(
            git,
            "RunGit",
            return_value=cros_build_lib.CompletedProcess(stdout=""),
        )
        self.PatchObject(
            cros_mark_as_stable, "_WorkOnEbuild", return_value=None
        )
        self.PatchObject(git, "GetGitRepoRevision")
        self.PatchObject(cros_mark_as_stable.GitBranch, "CreateBranch")
        self.PatchObject(
            cros_mark_as_stable.GitBranch, "Exists", return_value=True
        )
        self.PatchObject(portage_util.EBuild, "CommitChange")

        overlay_ebuilds = {
            self._overlays[0]: ["ebuild_1_1", "ebuild_1_2"],
            self._overlays[1]: ["ebuild_2_1"],
            self._overlays[2]: ["ebuild_3_1", "ebuild_3_2"],
        }

        cros_mark_as_stable._CommitOverlays(
            self._commit_options,
            self._manifest,
            self._overlays,
            self._overlay_tracking_branch,
            overlay_ebuilds,
            [],
            [],
        )
        self.assertEqual(3, mock_run_process_pool.call_count)

    def testWorkOnEbuildWithNewPackage(self) -> None:
        """Test _WorkOnEbuild with new packages."""
        overlay = self._overlays[0]
        ebuild = EbuildMock("ebuild")

        with parallel.Manager() as manager:
            revved_packages = manager.list()
            new_package_atoms = manager.list()

            messages = manager.list()
            ebuild_paths_to_add = manager.list()
            ebuild_paths_to_remove = manager.list()

            cros_mark_as_stable._WorkOnEbuild(
                overlay,
                ebuild,
                self._manifest,
                self._commit_options,
                ebuild_paths_to_add,
                ebuild_paths_to_remove,
                messages,
                revved_packages,
                new_package_atoms,
            )
            self.assertCountEqual(ebuild_paths_to_add, ["ebuild_new_ebuild"])
            self.assertCountEqual(ebuild_paths_to_remove, ["ebuild_old_ebuild"])
            self.assertCountEqual(
                messages,
                [cros_mark_as_stable._GIT_COMMIT_MESSAGE % "ebuild_package"],
            )
            self.assertCountEqual(revved_packages, ["ebuild_package"])
            self.assertCountEqual(new_package_atoms, ["=ebuild_new_package"])

    def testWorkOnEbuildWithoutNewPackage(self) -> None:
        """Test _WorkOnEbuild without new packages."""
        ebuild = EbuildMock("ebuild", new_package=False)
        overlay = self._overlays[0]

        with parallel.Manager() as manager:
            revved_packages = manager.list()
            new_package_atoms = manager.list()

            messages = manager.list()
            ebuild_paths_to_add = manager.list()
            ebuild_paths_to_remove = manager.list()

            cros_mark_as_stable._WorkOnEbuild(
                overlay,
                ebuild,
                self._manifest,
                self._commit_options,
                ebuild_paths_to_add,
                ebuild_paths_to_remove,
                messages,
                revved_packages,
                new_package_atoms,
            )
            self.assertEqual(list(ebuild_paths_to_add), [])
            self.assertEqual(list(ebuild_paths_to_remove), [])
            self.assertEqual(list(messages), [])
            self.assertEqual(list(revved_packages), [])
            self.assertEqual(list(new_package_atoms), [])


class MainTests(
    cros_test_lib.RunCommandTestCase, cros_test_lib.MockTempDirTestCase
):
    """Tests for cros_mark_as_stable.main()."""

    def setUp(self) -> None:
        self.PatchObject(
            git.ManifestCheckout, "Cached", return_value="manifest"
        )
        self.mock_work_on_commit = self.PatchObject(
            cros_mark_as_stable, "_WorkOnCommit"
        )

        self._overlays = []
        remote_refs = []
        self._overlay_tracking_branch = {}
        self._git_project_overlays = {}
        for i in range(0, 3):
            overlay = os.path.join(self.tempdir, "overlay_%s" % i)
            osutils.SafeMakedirs(overlay)
            self._overlays.append(overlay)

            remote_ref = git.RemoteRef("remote", "ref", "project_%s" % i)
            remote_refs.append(remote_ref)

            self._overlay_tracking_branch[overlay] = remote_ref.ref
            self._git_project_overlays[remote_ref.project_name] = [overlay]

        self.PatchObject(
            portage_util, "FindOverlays", return_value=self._overlays
        )
        self.PatchObject(
            git, "GetTrackingBranchViaManifest", side_effect=remote_refs
        )

    def testMainWithCommit(self) -> None:
        """Test Main with Commit options."""
        cros_mark_as_stable.main(
            ["commit", "--all", "--overlays", ":".join(self._overlays)]
        )
        self.mock_work_on_commit.assert_called_once_with(
            mock.ANY,
            self._overlays,
            self._overlay_tracking_branch,
            self._git_project_overlays,
            "manifest",
            None,
        )

    def testMainWithOverlayTypeCommit(self) -> None:
        """Test Main with Commit options."""
        cros_mark_as_stable.main(["commit", "--all", "--overlay-type", "both"])
        self.mock_work_on_commit.assert_called_once_with(
            mock.ANY,
            self._overlays,
            self._overlay_tracking_branch,
            self._git_project_overlays,
            "manifest",
            None,
        )
        options = self.mock_work_on_commit.call_args[0][0]
        self.assertEqual(options.buildroot, constants.SOURCE_ROOT)
        self.assertIsNone(options.srcroot)

    def testMainWithBuildroot(self) -> None:
        """Test Main with Commit options."""
        self.PatchObject(
            os.path, "isdir", side_effect=lambda p: p == "/buildroot"
        )

        cros_mark_as_stable.main(
            [
                "commit",
                "--all",
                "--overlay-type",
                "both",
                "--buildroot",
                "/buildroot",
            ]
        )

        options = self.mock_work_on_commit.call_args[0][0]
        self.assertEqual(options.buildroot, "/buildroot")
        self.assertIsNone(options.srcroot)

    def testMainWithSrcroot(self) -> None:
        """Test Main with Commit options."""
        self.PatchObject(
            os.path, "isdir", side_effect=lambda p: p == "/buildroot"
        )

        cros_mark_as_stable.main(
            [
                "commit",
                "--all",
                "--overlay-type",
                "both",
                "--srcroot",
                "/buildroot/src",
            ]
        )

        options = self.mock_work_on_commit.call_args[0][0]
        self.assertEqual(options.buildroot, "/buildroot")
        self.assertIsNone(options.srcroot)


class CleanStalePackagesTest(cros_test_lib.RunCommandTestCase):
    """Tests for cros_mark_as_stable.CleanStalePackages."""

    def setUp(self) -> None:
        self.PatchObject(osutils, "FindMissingBinaries", return_value=[])

    def testNormalClean(self) -> None:
        """Clean up boards/packages with normal success"""
        cros_mark_as_stable.CleanStalePackages(
            ".", ("board1", "board2"), ["cow", "car"]
        )

    def testNothingToUnmerge(self) -> None:
        """Clean up packages that don't exist (portage will exit 1)"""
        self.rc.AddCmdResult(partial_mock.In("emerge"), returncode=1)
        cros_mark_as_stable.CleanStalePackages(".", (), ["no/pkg"])

    def testUnmergeError(self) -> None:
        """Make sure random exit errors are not ignored"""
        self.rc.AddCmdResult(partial_mock.In("emerge"), returncode=123)
        with parallel_unittest.ParallelMock():
            with self.assertRaises(cros_build_lib.RunCommandError):
                cros_mark_as_stable.CleanStalePackages(".", (), ["no/pkg"])


class GitBranchTest(cros_test_lib.MockTestCase):
    """Tests for cros_mark_as_stable.GitBranch."""

    def setUp(self) -> None:
        # Always stub RunCommmand out as we use it in every method.
        self.git_mock = self.PatchObject(git, "RunGit")
        self.start_mock = self.PatchObject(repo_util.Repository, "StartBranch")

        self._branch_name = "test_branch"
        self._target_manifest_branch = "cros/test"
        self._branch = cros_mark_as_stable.GitBranch(
            branch_name=self._branch_name,
            tracking_branch=self._target_manifest_branch,
            cwd=".",
        )

    def testCheckoutCreate(self) -> None:
        """Test init with no previous branch existing."""
        self.PatchObject(self._branch, "Exists", return_value=False)
        cros_mark_as_stable.GitBranch.Checkout(self._branch)
        self.start_mock.assert_called_with(
            self._branch_name, projects=["."], cwd="."
        )

    def testCheckoutNoCreate(self) -> None:
        """Test init with previous branch existing."""
        self.PatchObject(self._branch, "Exists", return_value=True)
        cros_mark_as_stable.GitBranch.Checkout(self._branch)
        self.git_mock.assert_called_with(
            ".", ["checkout", "-f", self._branch_name]
        )

    def testExists(self) -> None:
        """Test if branch exists that is created."""
        result = cros_build_lib.CompletedProcess(
            stdout=self._branch_name + "\n"
        )
        self.PatchObject(git, "RunGit", return_value=result)
        self.assertTrue(self._branch.Exists())
