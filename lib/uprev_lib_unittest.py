# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""uprev_lib tests."""

import os
import pathlib
from unittest import mock

from chromite.third_party.infra_libs.buildbucket.proto import common_pb2
import pytest

import chromite as cr
from chromite.lib import build_target_lib
from chromite.lib import buildbucket_v2
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import gob_util
from chromite.lib import osutils
from chromite.lib import parallel
from chromite.lib import uprev_lib
from chromite.lib.parser import package_info


class ChromeVersionTest(cros_test_lib.TestCase):
    """Tests for best_version and get_version_from_refs."""

    def setUp(self) -> None:
        # The tag ref template.
        ref_tpl = "refs/tags/%s"

        self.best = "4.3.2.1"
        self.versions = ["1.2.3.4", self.best, "4.2.2.1", "4.3.1.4"]
        self.best_ref = uprev_lib.GitRef("/path", ref_tpl % self.best, "abc123")
        self.refs = [
            uprev_lib.GitRef(
                "/path", ref_tpl % v, "abc123" + v.replace(".", "")
            )
            for v in self.versions
        ]

        self.unstable = "9999"
        self.unstable_versions = self.versions + [self.unstable]

    def test_single_version(self) -> None:
        """Test a single version."""
        self.assertEqual(self.best, uprev_lib.best_version([self.best]))

    def test_multiple_versions(self) -> None:
        """Test a single version."""
        self.assertEqual(self.best, uprev_lib.best_version(self.versions))

    def test_no_versions_fail(self) -> None:
        """Test no versions given."""
        with self.assertRaises(uprev_lib.NoVersionsError):
            uprev_lib.best_version([])

    def test_unstable_only(self) -> None:
        """Test the unstable version."""
        self.assertEqual(self.unstable, uprev_lib.best_version([self.unstable]))

    def test_unstable_multiple(self) -> None:
        """Test unstable alongside multiple other versions."""
        self.assertEqual(
            self.unstable, uprev_lib.best_version(self.unstable_versions)
        )

    def test_single_ref(self) -> None:
        """Test a single ref."""
        self.assertEqual(
            (self.best, "abc123"),
            uprev_lib.get_version_from_refs([self.best_ref]),
        )

    def test_multiple_refs(self) -> None:
        """Test multiple refs."""
        self.assertEqual(
            (self.best, "abc1234321"),
            uprev_lib.get_version_from_refs(self.refs),
        )

    def test_no_refs_fail(self) -> None:
        """Test no versions given."""
        with self.assertRaises(uprev_lib.NoRefsError):
            uprev_lib.get_version_from_refs([])


class ChromeMainVersionTest(cros_test_lib.MockTestCase):
    """Tests for get_version_from_refs for non-release of Chrome uprev."""

    def setUp(self) -> None:
        self._main_commit = "deadbeef"
        self._main_revert_commit = "beefdead"
        self._canary_commit = "deadfeed"
        self._main_revert_version = "136.0.1346.0_pre1122444"
        self._main_version = "136.0.1345.0_pre1122334"
        self._canary_version = "136.0.1345.0"
        self._main_ref = uprev_lib.GitRef(
            path="/path", ref="refs/heads/main", revision=self._main_commit
        )
        self._main_revert_ref = uprev_lib.GitRef(
            path="/path",
            ref="refs/heads/main",
            revision=self._main_revert_commit,
        )
        self._canary_ref = uprev_lib.GitRef(
            path="/path",
            ref=f"refs/tags/{self._canary_version}",
            revision=self._canary_commit,
        )
        self._mock_fetch_url_json = self.PatchObject(gob_util, "FetchUrlJson")
        self._mock_get_file_contents = self.PatchObject(
            gob_util, "GetFileContents"
        )

    def _mock_gitile(
        self, standard_chrome_version: str, commit_message: str
    ) -> None:
        versions = standard_chrome_version.split(".")
        self._mock_get_file_contents.return_value = (
            f"MAJOR={versions[0]}\n"
            f"MINOR={versions[1]}\n"
            f"BUILD={versions[2]}\n"
            f"PATCH={versions[3]}\n"
        )
        commit_json = {"message": commit_message}
        self._mock_fetch_url_json.return_value = commit_json

    def _assert_gitile(self, commit: str) -> None:
        self._mock_get_file_contents.assert_called_with(
            "https://chromium.googlesource.com/chromium/src.git",
            "chrome/VERSION",
            commit,
        )
        self._mock_fetch_url_json.assert_called_with(
            "chromium.googlesource.com",
            f"chromium/src.git/+/{commit}?format=JSON",
        )

    def test_main_ref(self) -> None:
        self._mock_gitile(
            self._main_version.split("_", maxsplit=1)[0],
            (
                "chromeos: fix bug\n\n"
                "Bug: 12312312\n"
                "Change-Id: I123123812312312312312312\n"
                "Cr-Commit-Position: refs/heads/main@{#1122334}\n"
            ),
        )
        self.assertEqual(
            (self._main_version, self._main_commit),
            uprev_lib.get_version_from_refs([self._main_ref]),
        )
        self._assert_gitile(self._main_commit)

    def test_main_revert(self) -> None:
        self._mock_gitile(
            self._main_revert_version.split("_", maxsplit=1)[0],
            (
                'Revert "chromeos: fix bug"\n\n'
                "This reverts commit deadbeef\n\n"
                "Reason for revert: test\n\n"
                "Original change's description:\n"
                "> chromeos: fix bug\n\n"
                "> Bug: 12312312\n"
                "> Change-Id: I123123812312312312312312\n"
                "> Cr-Commit-Position: refs/heads/main@{#1122334}\n\n"
                "Bug: 12312312, 123999\n"
                "Change-Id: I12318832193838333\n"
                "Cr-Commit-Position: refs/heads/main@{#1122444}\n"
            ),
        )
        self.assertEqual(
            (self._main_revert_version, self._main_revert_commit),
            uprev_lib.get_version_from_refs([self._main_revert_ref]),
        )
        self._assert_gitile(self._main_revert_commit)

    def test_canary_no_network(self) -> None:
        self.assertEqual(
            (self._canary_version, self._canary_commit),
            uprev_lib.get_version_from_refs([self._canary_ref]),
        )
        self._mock_get_file_contents.assert_not_called()
        self._mock_fetch_url_json.assert_not_called()


class ChromeEbuildVersionTest(cros_test_lib.MockTempDirTestCase):
    """Tests for best_chrome_ebuild and get_stable_chrome_version."""

    def setUp(self) -> None:
        # Setup some ebuilds to test against.
        pkg_dir = os.path.join(self.tempdir, constants.CHROME_CP)
        osutils.SafeMakedirs(pkg_dir)
        ebuild = os.path.join(pkg_dir, "chromeos-chrome-%s_rc-r%s.ebuild")
        unstable_ebuild = os.path.join(pkg_dir, "chromeos-chrome-9999.ebuild")

        best_version = "4.3.2.1"
        rest_versions = ["1.2.3.4", "4.3.2.0"]

        best_revs = [2, 12]
        rest_revs = best_revs + [21]

        # Other versions to set up to compare against.
        ebuild_paths = [ebuild % (best_version, rev) for rev in best_revs]
        ebuild_paths += [
            ebuild % (ver, rev) for ver in rest_versions for rev in rest_revs
        ]
        best_ebuild_path = ebuild % (best_version, max(best_revs))

        # Write stable ebuild data.
        stable_data = 'GIT_COMMIT="deadbeef"\nKEYWORDS=*\n'
        osutils.WriteFile(best_ebuild_path, stable_data)
        for path in ebuild_paths:
            osutils.WriteFile(path, stable_data)
        # Write the unstable ebuild.
        unstable_data = 'GIT_COMMIT=""\nKEYWORDS=~*\n'
        osutils.WriteFile(unstable_ebuild, unstable_data)

        # Create the ebuilds.
        self.ebuilds = [uprev_lib.ChromeEBuild(path) for path in ebuild_paths]
        self.best_ebuild = uprev_lib.ChromeEBuild(best_ebuild_path)

    def test_no_ebuilds(self) -> None:
        """Test error on no ebuilds provided."""
        with self.assertRaises(uprev_lib.NoEbuildsError):
            uprev_lib.best_chrome_ebuild([])

    def test_single_ebuild(self) -> None:
        """Test a single ebuild."""
        best = uprev_lib.best_chrome_ebuild([self.best_ebuild])
        self.assertEqual(self.best_ebuild.ebuild_path, best.ebuild_path)

    def test_multiple_ebuilds(self) -> None:
        """Test multiple ebuilds."""
        best = uprev_lib.best_chrome_ebuild(self.ebuilds)
        self.assertEqual(self.best_ebuild.ebuild_path, best.ebuild_path)

    def test_get_stable_version(self) -> None:
        """Test fetching latest stable version from ebuilds."""
        self.PatchObject(uprev_lib, "_CHROME_OVERLAY_PATH", new=self.tempdir)
        version = uprev_lib.get_stable_chrome_version()
        self.assertEqual((self.best_ebuild.chrome_version, "deadbeef"), version)


class FindChromeEbuildsTest(cros_test_lib.TempDirTestCase):
    """find_chrome_ebuilds tests."""

    def setUp(self) -> None:
        ebuild = os.path.join(self.tempdir, "chromeos-chrome-%s.ebuild")
        self.unstable = ebuild % "9999"
        self.alpha_unstable = ebuild % "4.3.2.1_alpha-r12"
        self.best_stable = ebuild % "4.3.2.1_rc-r12"
        self.old_stable = ebuild % "4.3.2.1_rc-r2"

        unstable_data = "KEYWORDS=~*"
        stable_data = "KEYWORDS=*"

        osutils.WriteFile(self.unstable, unstable_data)
        osutils.WriteFile(self.alpha_unstable, unstable_data)
        osutils.WriteFile(self.best_stable, stable_data)
        osutils.WriteFile(self.old_stable, stable_data)

    def test_find_all(self) -> None:
        unstable, stables = uprev_lib.find_chrome_ebuilds(self.tempdir)
        self.assertEqual(self.unstable, unstable.ebuild_path)
        self.assertCountEqual(
            [self.best_stable, self.old_stable],
            [stable.ebuild_path for stable in stables],
        )


class UprevChromeManagerTest(cros_test_lib.MockTempDirTestCase):
    """UprevChromeManager tests."""

    def setUp(self) -> None:
        ebuild = "chromeos-chrome-%s.ebuild"
        self.stable_chrome_version = "4.3.2.1"
        self.stable_chrome_commit = "abc123"
        self.new_chrome_version = "4.3.2.2"
        self.new_chrome_commit = "def456"
        self.stable_revision = 1
        stable_version = "%s_rc-r%d" % (
            self.stable_chrome_version,
            self.stable_revision,
        )

        self.package_dir = os.path.join(self.tempdir, constants.CHROME_CP)
        osutils.SafeMakedirs(self.package_dir)

        self.stable_path = os.path.join(
            self.package_dir, ebuild % stable_version
        )
        self.unstable_path = os.path.join(self.package_dir, ebuild % "9999")

        osutils.WriteFile(self.stable_path, 'GIT_COMMIT="abc123"\nKEYWORDS=*\n')
        osutils.WriteFile(self.unstable_path, 'GIT_COMMIT=""\nKEYWORDS=~*\n')

        # Avoid chroot interactions for the tests.
        self.PatchObject(uprev_lib, "clean_stale_packages")

    def test_no_change(self) -> None:
        """Test a no-change uprev."""
        # No changes should be made when the stable and unstable ebuilds match.
        manager = uprev_lib.UprevChromeManager(
            self.stable_chrome_version,
            self.stable_chrome_commit,
            overlay_dir=self.tempdir,
        )
        manager.uprev(constants.CHROME_CP)

        self.assertFalse(manager.modified_ebuilds)

    def test_older_version(self) -> None:
        """Test uprevving to an older version."""
        manager = uprev_lib.UprevChromeManager(
            "1.2.3.4", "0000", overlay_dir=self.tempdir
        )
        manager.uprev(constants.CHROME_CP)

        self.assertFalse(manager.modified_ebuilds)

    def test_same_version_tag_to_main(self) -> None:
        """Test uprevving to pre from rc."""
        manager = uprev_lib.UprevChromeManager(
            "4.3.2.1_pre12345", "0000", overlay_dir=self.tempdir
        )
        manager.uprev(constants.CHROME_CP)

        self.assertFalse(manager.modified_ebuilds)

    def test_new_version(self) -> None:
        """Test a new chrome version."""
        # The stable ebuild should be replaced with one of the new version.
        manager = uprev_lib.UprevChromeManager(
            self.new_chrome_version,
            self.new_chrome_commit,
            overlay_dir=self.tempdir,
        )
        manager.uprev(constants.CHROME_CP)

        # The old one should be deleted and the new one should exist.
        new_path = self.stable_path.replace(
            self.stable_chrome_version, self.new_chrome_version
        )
        self.assertCountEqual(
            [self.stable_path, new_path], manager.modified_ebuilds
        )
        self.assertExists(new_path)
        self.assertNotExists(self.stable_path)

        new_ebuild = uprev_lib.ChromeEBuild(new_path)
        expected_version = f"{self.new_chrome_version}_rc-r1"
        self.assertEqual(expected_version, new_ebuild.version)
        self.assertEqual(self.new_chrome_commit, new_ebuild.commit_hash)

    def test_new_version_main(self) -> None:
        """Test a new chrome version's main branch pre."""
        # The stable ebuild should be replaced with one of the new version.
        manager = uprev_lib.UprevChromeManager(
            self.new_chrome_version + "_pre12345",
            self.new_chrome_commit,
            overlay_dir=self.tempdir,
        )
        manager.uprev(constants.CHROME_CP)

        # The old one should be deleted and the new one should exist.
        new_path = self.stable_path.replace(
            self.stable_chrome_version,
            self.new_chrome_version + "_pre12345",
        )
        self.assertCountEqual(
            [self.stable_path, new_path], manager.modified_ebuilds
        )
        self.assertExists(new_path)
        self.assertNotExists(self.stable_path)

        new_ebuild = uprev_lib.ChromeEBuild(new_path)
        expected_version = f"{self.new_chrome_version}_pre12345_rc-r1"
        self.assertEqual(expected_version, new_ebuild.version)
        self.assertEqual(self.new_chrome_commit, new_ebuild.commit_hash)

    def test_uprev(self) -> None:
        """Test a revision bump."""
        # Make the contents different to force the uprev.
        osutils.WriteFile(self.unstable_path, 'IUSE=""', mode="a")
        manager = uprev_lib.UprevChromeManager(
            self.stable_chrome_version,
            self.stable_chrome_commit,
            overlay_dir=self.tempdir,
        )
        manager.uprev(constants.CHROME_CP)

        new_path = self.stable_path.replace(
            "-r%d" % self.stable_revision, "-r%d" % (self.stable_revision + 1)
        )

        self.assertCountEqual(
            [self.stable_path, new_path], manager.modified_ebuilds
        )
        self.assertExists(new_path)
        self.assertNotExists(self.stable_path)

        new_ebuild = uprev_lib.ChromeEBuild(new_path)
        expected_version = (
            f"{self.stable_chrome_version}_rc-r{self.stable_revision+1}"
        )
        self.assertEqual(expected_version, new_ebuild.version)
        self.assertEqual(self.stable_chrome_commit, new_ebuild.commit_hash)


class UprevManagerTest(cros_test_lib.MockTestCase):
    """UprevManager tests."""

    def test_clean_stale_packages_no_chroot(self) -> None:
        """Test no chroot skip."""
        manager = uprev_lib.UprevOverlayManager([], None)
        self.PatchObject(parallel, "RunTasksInProcessPool")

        # pylint: disable=protected-access
        manager._clean_stale_packages()

        # Make sure we aren't doing any work.
        # TODO(crbug/1065172): Invalid assertion that was previously mocked.
        # patch.assert_not_called()

    def test_clean_stale_packages_chroot_not_exists(self) -> None:
        """Cannot run the commands when the chroot does not exist."""
        chroot = chroot_lib.Chroot()
        self.PatchObject(chroot, "exists", return_value=False)
        manager = uprev_lib.UprevOverlayManager([], None, chroot=chroot)
        self.PatchObject(parallel, "RunTasksInProcessPool")

        # pylint: disable=protected-access
        manager._clean_stale_packages()

        # Make sure we aren't doing any work.
        # TODO(crbug/1065172): Invalid assertion that was previously mocked.
        # patch.assert_not_called()

    def test_clean_stale_packages_no_build_targets(self) -> None:
        """Make sure it behaves as expected with no build targets provided."""
        chroot = chroot_lib.Chroot()
        self.PatchObject(chroot, "exists", return_value=True)
        manager = uprev_lib.UprevOverlayManager([], None, chroot=chroot)
        patch = self.PatchObject(parallel, "RunTasksInProcessPool")

        # pylint: disable=protected-access
        manager._clean_stale_packages()

        # Make sure we aren't doing any work.
        patch.assert_called_once_with(mock.ANY, [[None]])

    def test_clean_stale_packages_with_boards(self) -> None:
        """Test it cleans all boards as well as the chroot."""
        targets = ["board1", "board2"]
        build_targets = [build_target_lib.BuildTarget(t) for t in targets]
        chroot = chroot_lib.Chroot()
        self.PatchObject(chroot, "exists", return_value=True)
        manager = uprev_lib.UprevOverlayManager(
            [], None, chroot=chroot, build_targets=build_targets
        )
        patch = self.PatchObject(parallel, "RunTasksInProcessPool")

        # pylint: disable=protected-access
        manager._clean_stale_packages()

        patch.assert_called_once_with(mock.ANY, [[t] for t in targets + [None]])


def test_find_chrome_ebuilds(overlay_stack) -> None:
    """Test that chrome ebuilds can be discovered in the test overlay."""

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="9999", keywords="~*"
    )
    stable_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="78.0.3876.1-r1"
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    unstable, stable = uprev_lib.find_chrome_ebuilds(
        overlay.path / "chromeos-base" / "chromeos-chrome"
    )
    assert unstable
    assert stable


def test_find_chrome_stable_candidate(overlay_stack) -> None:
    """Test that a stable uprev candidate can be chosen in the expected case."""
    NEW_CHROME_VERSION = "80.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="9999", keywords="~*"
    )
    stable_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="78.0.3876.0_rc-r1"
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    _unstable, stable = uprev_lib.find_chrome_ebuilds(
        overlay.path / "chromeos-base" / "chromeos-chrome"
    )
    assert stable
    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION, commit_hash=""
    )
    # pylint: disable=protected-access
    candidate = uprev_manager._find_chrome_uprev_candidate(stable)
    assert candidate


def test_basic_chrome_uprev(overlay_stack) -> None:
    """Test that the default uprev path works as expected."""
    NEW_CHROME_VERSION = "80.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="78.0.3876.0_rc-r1",
        GIT_COMMIT="abc123",
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.VERSION_BUMP

    new_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="80.0.1234.0_rc-r1"
    )

    assert new_chrome.cpv in overlay


def test_chrome_uprev_tag_to_new_main(overlay_stack) -> None:
    """Test that uprev from a version new newer main works."""
    NEW_CHROME_VERSION = "80.0.1234.0_pre12345"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="78.0.3876.0_rc-r1",
        GIT_COMMIT="abc123",
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.VERSION_BUMP

    new_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="80.0.1234.0_pre12345_rc-r1"
    )

    assert new_chrome.cpv in overlay


def test_chrome_uprev_main_to_main_position_update(overlay_stack) -> None:
    """Test that uprev works with newer commit position."""
    NEW_CHROME_VERSION = "80.0.1234.0_pre12345"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_pre12340_rc-r1",
        GIT_COMMIT="abc123",
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.VERSION_BUMP

    new_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="80.0.1234.0_pre12345_rc-r1"
    )

    assert new_chrome.cpv in overlay


def test_chrome_uprev_main_to_new_main(overlay_stack) -> None:
    """Test that uprev works from main to newer version on main."""
    NEW_CHROME_VERSION = "80.0.1234.0_pre12345"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="78.0.3876.0_pre9971_rc-r1",
        GIT_COMMIT="abc123",
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.VERSION_BUMP

    new_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="80.0.1234.0_pre12345_rc-r1"
    )

    assert new_chrome.cpv in overlay


def test_chrome_uprev_main_to_new_tag(overlay_stack) -> None:
    """Test that uprev works from main to newer release tag."""
    NEW_CHROME_VERSION = "80.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="78.0.3876.0_pre9971_rc-r1",
        GIT_COMMIT="abc123",
    )
    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.VERSION_BUMP

    new_chrome = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="80.0.1234.0_rc-r1"
    )

    assert new_chrome.cpv in overlay


def test_chrome_uprev_revision_bump(overlay_stack) -> None:
    """Verify an uprev with the same major version just increments revision."""
    NEW_CHROME_VERSION = "80.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        depend="foo/bar",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="abc123",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.REVISION_BUMP

    expected_uprev = cr.test.Package(
        "chromeos-base", "chromeos-chrome", version="80.0.1234.0_rc-r2"
    )

    assert expected_uprev.cpv in overlay


def test_no_chrome_uprev_same_version(overlay_stack, caplog) -> None:
    """Test that no uprev occurs when version and contents are the same."""
    NEW_CHROME_VERSION = "80.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="abc123",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert not result
    assert result.outcome is uprev_lib.Outcome.SAME_VERSION_EXISTS

    ebuild_redundant_warning = (
        "Previous ebuild with same version found and ebuild is redundant."
    )
    assert ebuild_redundant_warning in caplog.text


def test_no_chrome_uprev_same_position(overlay_stack, caplog) -> None:
    """Test that no uprev if version and commit position are the same."""
    NEW_CHROME_VERSION = "80.0.1234.0_pre12345"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_pre12345_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="abc123",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert not result
    assert result.outcome is uprev_lib.Outcome.SAME_VERSION_EXISTS

    ebuild_redundant_warning = (
        "Previous ebuild with same version found and ebuild is redundant."
    )
    assert ebuild_redundant_warning in caplog.text


def test_no_chrome_uprev_older_version(overlay_stack, caplog) -> None:
    """Test that no uprev occurs when a newer version already exists."""
    # Intentionally older than what already exists.
    NEW_CHROME_VERSION = "55.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert not result
    assert result.outcome is uprev_lib.Outcome.NEWER_VERSION_EXISTS

    newer_version_warning = (
        "A chrome ebuild candidate with a higher version than the "
        "requested uprev version was found."
    )
    assert newer_version_warning in caplog.messages
    assert "Candidate version found: 80.0.1234.0" in caplog.messages


def test_no_chrome_uprev_older_position(overlay_stack, caplog) -> None:
    """Test that no uprev if uprev to older commit of the same version."""
    # Intentionally older than what already exists.
    NEW_CHROME_VERSION = "80.0.1234.0_pre12340"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_pre12345_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert not result
    assert result.outcome is uprev_lib.Outcome.NEWER_VERSION_EXISTS

    newer_version_warning = (
        "A chrome ebuild candidate with a higher version than the "
        "requested uprev version was found."
    )
    assert newer_version_warning in caplog.messages
    assert "Candidate version found: 80.0.1234.0_pre12345" in caplog.messages


def test_no_chrome_uprev_older_release(overlay_stack, caplog) -> None:
    """Test that no uprev if uprev to older releases."""
    # Intentionally older than what already exists.
    NEW_CHROME_VERSION = "80.0.1230.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_pre12345_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert not result
    assert result.outcome is uprev_lib.Outcome.NEWER_VERSION_EXISTS

    newer_version_warning = (
        "A chrome ebuild candidate with a higher version than the "
        "requested uprev version was found."
    )
    assert newer_version_warning in caplog.messages
    assert "Candidate version found: 80.0.1234.0_pre12345" in caplog.messages


def test_no_chrome_uprev_tag_to_same_version_main(
    overlay_stack, caplog
) -> None:
    """Test that no uprev if uprev to main-branch of the same version."""
    # Intentionally older than what already exists.
    # Main branch position is older than release tag since position should be
    # suggesting next release's version.
    NEW_CHROME_VERSION = "80.0.1234.0_pre12345"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        GIT_COMMIT="",
    )
    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="80.0.1234.0_rc-r1",
        GIT_COMMIT="abc123",
    )

    overlay.add_package(unstable_chrome)
    overlay.add_package(stable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="def456",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert not result
    assert result.outcome is uprev_lib.Outcome.NEWER_VERSION_EXISTS

    newer_version_warning = (
        "A chrome ebuild candidate with a higher version than the "
        "requested uprev version was found."
    )
    assert newer_version_warning in caplog.messages
    assert "Candidate version found: 80.0.1234.0" in caplog.messages


def test_chrome_uprev_no_existing_stable(overlay_stack) -> None:
    """Test that an uprev generates a stable ebuild if one doesn't exist yet."""
    NEW_CHROME_VERSION = "80.0.1234.0"

    (overlay,) = overlay_stack(1)
    unstable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version="9999",
        keywords="~*",
        depend="foo/bar",
        GIT_COMMIT="",
    )

    overlay.add_package(unstable_chrome)

    uprev_manager = uprev_lib.UprevChromeManager(
        version=NEW_CHROME_VERSION,
        commit_hash="abc123",
        overlay_dir=overlay.path,
    )

    result = uprev_manager.uprev(constants.CHROME_CP)
    assert result
    assert result.outcome is uprev_lib.Outcome.NEW_EBUILD_CREATED

    stable_chrome = cr.test.Package(
        "chromeos-base",
        "chromeos-chrome",
        version=f"{NEW_CHROME_VERSION}_rc-r1",
    )

    assert stable_chrome.cpv in overlay


def test_get_stable_ebuild_version(overlay_stack, monkeypatch) -> None:
    """Test getting the stable ebuild version."""
    (overlay,) = overlay_stack(1)
    unstable_package = cr.test.Package(
        "chromeos-base",
        "test-package",
        version="9999",
        keywords="~*",
        inherit="cros-workon",
    )
    stable_package = cr.test.Package(
        "chromeos-base", "test-package", version="30.0"
    )

    overlay.add_package(unstable_package)
    overlay.add_package(stable_package)

    monkeypatch.setattr(uprev_lib, "SRC_ROOT", overlay.path)
    stable_version = uprev_lib.get_stable_ebuild_version(
        pathlib.Path(unstable_package.category) / unstable_package.package,
    )

    assert stable_version == stable_package.package_info.version


def test_get_stable_ebuild_version_2_stable_ebuilds(
    overlay_stack, monkeypatch
) -> None:
    """Test getting the stable ebuild version on multiple stable ebuilds."""
    (overlay,) = overlay_stack(1)
    unstable_package = cr.test.Package(
        "chromeos-base",
        "test-package",
        version="9999",
        keywords="~*",
        inherit="cros-workon",
    )
    stable_package_30 = cr.test.Package(
        "chromeos-base", "test-package", version="30.0"
    )
    stable_package_31 = cr.test.Package(
        "chromeos-base", "test-package", version="31.0"
    )

    overlay.add_package(unstable_package)
    overlay.add_package(stable_package_30)
    overlay.add_package(stable_package_31)

    monkeypatch.setattr(uprev_lib, "SRC_ROOT", overlay.path)
    with pytest.raises(uprev_lib.TooManyStableEbuildsError):
        _ = uprev_lib.get_stable_ebuild_version(
            pathlib.Path(unstable_package.category) / unstable_package.package,
        )


def test_get_stable_ebuild_version_no_unstable(
    overlay_stack, monkeypatch
) -> None:
    """Test getting the stable ebuild version on no unstable ebuild."""
    (overlay,) = overlay_stack(1)
    stable_package = cr.test.Package(
        "chromeos-base", "test-package", version="30.0"
    )

    overlay.add_package(stable_package)

    monkeypatch.setattr(uprev_lib, "SRC_ROOT", overlay.path)
    with pytest.raises(uprev_lib.NoUnstableEbuildError):
        _ = uprev_lib.get_stable_ebuild_version(
            pathlib.Path(stable_package.category) / stable_package.package,
        )


@pytest.mark.inside_only
def test_non_workon_fails_uprev_workon_ebuild_to_version(
    overlay_stack, monkeypatch
) -> None:
    (overlay,) = overlay_stack(1)
    unstable_package = cr.test.Package(
        "chromeos-base",
        "test-package",
        version="9999",
        keywords="~*",
    )

    overlay.add_package(unstable_package)

    monkeypatch.setattr(uprev_lib, "SRC_ROOT", overlay.path)
    with pytest.raises(uprev_lib.EbuildUprevError):
        uprev_lib.uprev_workon_ebuild_to_version(
            pathlib.Path(unstable_package.category) / unstable_package.package,
            target_version="1",
            chroot=chroot_lib.Chroot(),
        )

    stable_package = package_info.PackageInfo(
        "chromeos-base",
        "test-package",
        version="1",
        revision="1",
    )

    assert not stable_package in overlay


@pytest.mark.inside_only
def test_simple_uprev_workon_ebuild_to_version(
    overlay_stack, monkeypatch
) -> None:
    (overlay,) = overlay_stack(1)
    unstable_package = cr.test.Package(
        "chromeos-base",
        "test-package",
        version="9999",
        keywords="~*",
        inherit="cros-workon",
        CROS_WORKON_PROJECT="chromiumos/infra/build/empty-project",
        CROS_WORKON_LOCALNAME="empty-project",
    )

    overlay.add_package(unstable_package)

    monkeypatch.setattr(uprev_lib, "SRC_ROOT", overlay.path)
    res = uprev_lib.uprev_workon_ebuild_to_version(
        pathlib.Path(unstable_package.category) / unstable_package.package,
        target_version="1",
        chroot=chroot_lib.Chroot(),
    )

    assert res.outcome is uprev_lib.Outcome.NEW_EBUILD_CREATED

    stable_package = package_info.PackageInfo(
        "chromeos-base",
        "test-package",
        version="1",
        revision="1",
    )

    assert stable_package in overlay


def test_uprev_workon_ebuild_to_version_newer_exists(
    overlay_stack, monkeypatch
) -> None:
    """Test no uprev when downrev not allowed and newer version exists."""
    (overlay,) = overlay_stack(1)
    unstable_ebuild = cr.test.Package(
        "chromeos-base",
        "uprev-test",
        version="9999",
        keywords="~*",
        inherit="cros-workon",
    )
    stable_ebuild = cr.test.Package(
        "chromeos-base", "uprev-test", version="5.0.3-r2", inherit="cros-workon"
    )

    overlay.add_package(unstable_ebuild)
    overlay.add_package(stable_ebuild)

    monkeypatch.setattr(uprev_lib, "SRC_ROOT", overlay.path)
    result = uprev_lib.uprev_workon_ebuild_to_version(
        "chromeos-base/uprev-test",
        "1.2.3",
        allow_downrev=False,
        chroot=chroot_lib.Chroot(),
    )

    assert not result
    assert result.outcome is uprev_lib.Outcome.NEWER_VERSION_EXISTS


def test_get_version_with_snapshot_from_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test get_version_with_snapshot_from_manifest."""
    monkeypatch.setattr(
        uprev_lib.git,
        "Log",
        mock.Mock(return_value="Cr-Snapshot-Identifier: 12345\n"),
    )
    mock_run = mock.Mock()
    mock_run.stdout = (
        '<manifest><project path="src/third_party/chromiumos-overlay" '
        'revision="abcdef" /></manifest>'
    )

    def side_effect(
        _git_repo: str, cmd: list[str], **_kwargs: object
    ) -> mock.Mock:
        """Mock side effect for RunGit."""
        if "snapshot.xml" in cmd[1]:
            return mock_run
        res = mock.Mock()
        res.stdout = (
            "CHROMEOS_BUILD=1\n"
            "CHROMEOS_BRANCH=2\n"
            "CHROMEOS_PATCH=3\n"
            "CHROME_BRANCH=4\n"
        )
        return res

    monkeypatch.setattr(
        uprev_lib.git, "RunGit", mock.Mock(side_effect=side_effect)
    )

    assert (
        uprev_lib.get_version_with_snapshot_from_manifest("HEAD")
        == "1.2.3-12345"
    )


def test_validate_lkgm_builds_succeeded_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify success of validate_lkgm_builds_succeeded."""
    mock_build = mock.Mock(
        id=1234500,
        number=123,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        output=mock.Mock(properties={"chromeos_version": "R120-1.2.3-12345"}),
        tags=[mock.Mock(key="relevance", value="relevant")],
    )
    mock_response = mock.Mock(builds=[mock_build])
    monkeypatch.setattr(
        buildbucket_v2.BuildbucketV2,
        "SearchBuild",
        mock.Mock(return_value=mock_response),
    )

    assert uprev_lib.validate_lkgm_builds_succeeded(
        "1.2.3-12345",
        "12345",
    )


def test_validate_lkgm_builds_succeeded_broken_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify validate_lkgm_builds_succeeded fails when a build failed."""
    mock_build = mock.Mock(
        id=1234500,
        number=123,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.FAILURE,
        output=mock.Mock(properties={"chromeos_version": "R120-1.2.3-12345"}),
    )
    mock_response = mock.Mock(builds=[mock_build])
    monkeypatch.setattr(
        buildbucket_v2.BuildbucketV2,
        "SearchBuild",
        mock.Mock(return_value=mock_response),
    )

    assert not uprev_lib.validate_lkgm_builds_succeeded(
        "1.2.3-12345",
        "12345",
    )


def test_validate_lkgm_builds_succeeded_irrelevant_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify success when build is irrelevant but previous succeeds."""
    monkeypatch.setattr(
        uprev_lib.git,
        "Log",
        mock.Mock(return_value="12345\n12344\n"),
    )

    mock_build_12345_irrelevant = mock.Mock(
        id=1234500,
        number=12345,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        tags=[
            mock.Mock(key="relevance", value="not relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12345"
                ),
            ),
        ],
    )
    mock_build_12345_relevant = mock.Mock(
        id=1234500,
        number=12345,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        tags=[
            mock.Mock(key="relevance", value="relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12345"
                ),
            ),
        ],
    )
    mock_build_12344 = mock.Mock(
        id=1234400,
        number=12344,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        tags=[
            mock.Mock(key="relevance", value="relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12344"
                ),
            ),
        ],
    )

    def side_effect(predicate, **_kwargs):
        builder = predicate.builder.builder
        if predicate.tags:
            buildset = next(
                t.value for t in predicate.tags if t.key == "buildset"
            )
            commit = buildset.split("/")[-1]
            if commit == "12345":
                if builder == "betty-snapshot":
                    return mock.Mock(builds=[mock_build_12345_relevant])
                return mock.Mock(builds=[mock_build_12345_irrelevant])
        elif predicate.build:
            if predicate.build.end_build_id == 1234500:
                return mock.Mock(
                    builds=[mock_build_12345_irrelevant, mock_build_12344]
                )
        return mock.Mock(builds=[])

    monkeypatch.setattr(
        buildbucket_v2.BuildbucketV2,
        "SearchBuild",
        mock.Mock(side_effect=side_effect),
    )

    # This should return True because it falls back to
    # 12344 which is success, and at least one board (betty) is relevant.
    assert uprev_lib.validate_lkgm_builds_succeeded(
        "1.2.3-12345",
        "12345",
    )


def test_validate_lkgm_builds_succeeded_all_irrelevant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failure (return False) when all boards are irrelevant."""
    monkeypatch.setattr(
        uprev_lib.git,
        "Log",
        mock.Mock(return_value="12345\n12344\n"),
    )

    mock_build_12345 = mock.Mock(
        id=1234500,
        number=12345,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        tags=[
            mock.Mock(key="relevance", value="not relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12345"
                ),
            ),
        ],
    )
    mock_build_12344 = mock.Mock(
        id=1234400,
        number=12344,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        tags=[
            mock.Mock(key="relevance", value="relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12344"
                ),
            ),
        ],
    )

    def side_effect(predicate, **_kwargs):
        if predicate.tags:
            buildset = next(
                t.value for t in predicate.tags if t.key == "buildset"
            )
            commit = buildset.split("/")[-1]
            if commit == "12345":
                return mock.Mock(builds=[mock_build_12345])
        elif predicate.build:
            if predicate.build.end_build_id == 1234500:
                return mock.Mock(builds=[mock_build_12345, mock_build_12344])
        return mock.Mock(builds=[])

    monkeypatch.setattr(
        buildbucket_v2.BuildbucketV2,
        "SearchBuild",
        mock.Mock(side_effect=side_effect),
    )

    # This should return False because all boards are irrelevant at 12345
    # (even though they fall back to 12344 successfully).
    assert not uprev_lib.validate_lkgm_builds_succeeded(
        "1.2.3-12345",
        "12345",
    )


def test_validate_lkgm_builds_succeeded_previous_broken_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify failure when previous build in chain is broken."""
    monkeypatch.setattr(
        uprev_lib.git,
        "Log",
        mock.Mock(return_value="12345\n12344\n"),
    )

    mock_build_12345 = mock.Mock(
        id=1234500,
        number=12345,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.SUCCESS,
        tags=[
            mock.Mock(key="relevance", value="not relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12345"
                ),
            ),
        ],
    )
    mock_build_12344 = mock.Mock(
        id=1234400,
        number=12344,
        builder=mock.Mock(
            project="chromeos", bucket="postsubmit", builder="betty-snapshot"
        ),
        status=common_pb2.FAILURE,
        tags=[
            mock.Mock(key="relevance", value="relevant"),
            mock.Mock(
                key="buildset",
                value=(
                    "commit/gitiles/chrome-internal.googlesource.com/"
                    "chromeos/manifest-internal/+/12344"
                ),
            ),
        ],
    )

    def side_effect(predicate, **_kwargs):
        if predicate.tags:
            buildset = next(
                t.value for t in predicate.tags if t.key == "buildset"
            )
            commit = buildset.split("/")[-1]
            if commit == "12345":
                return mock.Mock(builds=[mock_build_12345])
        elif predicate.build:
            if predicate.build.end_build_id == 1234500:
                return mock.Mock(builds=[mock_build_12345, mock_build_12344])
        return mock.Mock(builds=[])

    monkeypatch.setattr(
        buildbucket_v2.BuildbucketV2,
        "SearchBuild",
        mock.Mock(side_effect=side_effect),
    )

    assert not uprev_lib.validate_lkgm_builds_succeeded(
        "1.2.3-12345",
        "12345",
    )


def test_validate_lkgm_builds_succeeded_no_build_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify validate_lkgm_builds_succeeded fails when a build is not found."""
    monkeypatch.setattr(
        uprev_lib.git,
        "Log",
        mock.Mock(return_value="12345\n"),
    )

    # Mock SearchBuild to return empty builds (not found)
    mock_response = mock.Mock(builds=[])
    monkeypatch.setattr(
        buildbucket_v2.BuildbucketV2,
        "SearchBuild",
        mock.Mock(return_value=mock_response),
    )

    with pytest.raises(uprev_lib.EbuildUprevError):
        uprev_lib.validate_lkgm_builds_succeeded(
            "1.2.3-12345",
            "12345",
        )
