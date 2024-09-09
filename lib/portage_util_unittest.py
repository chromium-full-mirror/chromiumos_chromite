# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for portage_util.py."""

import json
import os
from pathlib import Path

import pytest

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import failures_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib.parser import package_info
from chromite.utils.parser import portage_md5_cache


MANIFEST = git.ManifestCheckout.Cached(constants.SOURCE_ROOT)


# pylint: disable=protected-access


class _Package:
    """Package helper class."""

    def __init__(self, package) -> None:
        self.package = package


class EBuildTest(cros_test_lib.MockTempDirTestCase):
    """Ebuild related tests."""

    _MULTILINE_WITH_TEST = """
hello
src_test() {
}"""

    _MULTILINE_NO_TEST = """
hello
src_compile() {
}"""

    _MULTILINE_COMMENTED = """
#src_test() {
# notactive
# }"""

    _MULTILINE_PLATFORM = """
platform_pkg_test() {
}"""

    _AUTOTEST_NORMAL = (
        "\n\t+tests_fake_Test1\n\t+tests_fake_Test2\n",
        (
            "fake_Test1",
            "fake_Test2",
        ),
    )

    _AUTOTEST_EXTRA_PLUS = ("\n\t++++tests_fake_Test1\n", ("fake_Test1",))

    _AUTOTEST_EXTRA_TAB = (
        "\t\t\n\t\n\t+tests_fake_Test1\tfoo\n",
        ("fake_Test1",),
    )

    _SINGLE_LINE_TEST = 'src_test() { echo "foo" }'

    _INHERIT_CROS_GO = "inherit cros-workon cros-go"

    _INHERIT_TAST_BUNDLE = "inherit tast-bundle"

    _INHERIT_CROS_DEBUG = "inherit cros-debug"

    _EBUILD_BASE = """
CROS_WORKON_COMMIT=commit1
CROS_WORKON_TREE=("tree1" "tree2")
inherit cros-workon
"""

    _EBUILD_DIFFERENT_COMMIT = """
CROS_WORKON_COMMIT=commit9
CROS_WORKON_TREE=("tree1" "tree2")
inherit cros-workon
"""

    _EBUILD_DIFFERENT_TREE = """
CROS_WORKON_COMMIT=commit1
CROS_WORKON_TREE=("tree9" "tree2")
inherit cros-workon
"""

    _EBUILD_DIFFERENT_CONTENT = """
CROS_WORKON_COMMIT=commit1
CROS_WORKON_TREE=("tree1" "tree2")
inherit cros-workon superpower
"""

    def _MakeFakeEbuild(self, fake_ebuild_path, fake_ebuild_content=""):
        osutils.WriteFile(fake_ebuild_path, fake_ebuild_content, makedirs=True)
        fake_ebuild = portage_util.EBuild(fake_ebuild_path, False)
        return fake_ebuild

    def testParseEBuildPath(self) -> None:
        """Test with ebuild with revision number."""
        basedir = os.path.join(self.tempdir, "cat", "test_package")
        fake_ebuild_path = os.path.join(basedir, "test_package-0.0.1-r1.ebuild")
        fake_ebuild = self._MakeFakeEbuild(fake_ebuild_path)

        self.assertEqual(fake_ebuild.category, "cat")
        self.assertEqual(fake_ebuild.pkgname, "test_package")
        self.assertEqual(fake_ebuild.version_no_rev, "0.0.1")
        self.assertEqual(fake_ebuild.current_revision, 1)
        self.assertEqual(fake_ebuild.version, "0.0.1-r1")
        self.assertEqual(fake_ebuild.package, "cat/test_package")
        self.assertEqual(
            fake_ebuild._ebuild_path_no_version,
            os.path.join(basedir, "test_package"),
        )
        self.assertEqual(
            fake_ebuild.ebuild_path_no_revision,
            os.path.join(basedir, "test_package-0.0.1"),
        )
        self.assertEqual(
            fake_ebuild._unstable_ebuild_path,
            os.path.join(basedir, "test_package-9999.ebuild"),
        )
        self.assertEqual(fake_ebuild.ebuild_path, fake_ebuild_path)

    def testParseEBuildPathNoRevisionNumber(self) -> None:
        """Test with ebuild without revision number."""
        basedir = os.path.join(self.tempdir, "cat", "test_package")
        fake_ebuild_path = os.path.join(basedir, "test_package-9999.ebuild")
        fake_ebuild = self._MakeFakeEbuild(fake_ebuild_path)

        self.assertEqual(fake_ebuild.category, "cat")
        self.assertEqual(fake_ebuild.pkgname, "test_package")
        self.assertEqual(fake_ebuild.version_no_rev, "9999")
        self.assertEqual(fake_ebuild.current_revision, 0)
        self.assertEqual(fake_ebuild.version, "9999")
        self.assertEqual(fake_ebuild.package, "cat/test_package")
        self.assertEqual(
            fake_ebuild._ebuild_path_no_version,
            os.path.join(basedir, "test_package"),
        )
        self.assertEqual(
            fake_ebuild.ebuild_path_no_revision,
            os.path.join(basedir, "test_package-9999"),
        )
        self.assertEqual(
            fake_ebuild._unstable_ebuild_path,
            os.path.join(basedir, "test_package-9999.ebuild"),
        )
        self.assertEqual(fake_ebuild.ebuild_path, fake_ebuild_path)

    def testGetCommitId(self) -> None:
        fake_hash = "24ab3c9f6d6b5c744382dba2ca8fb444b9808e9f"
        basedir = os.path.join(self.tempdir, "cat", "test_package")
        fake_ebuild_path = os.path.join(basedir, "test_package-9999.ebuild")
        fake_ebuild = self._MakeFakeEbuild(fake_ebuild_path)

        # git rev-parse HEAD
        self.PatchObject(
            git,
            "RunGit",
            return_value=cros_build_lib.CompletedProcess(
                stdout=fake_hash + "\n"
            ),
        )
        test_hash = fake_ebuild.GetCommitId(self.tempdir)
        self.assertEqual(test_hash, fake_hash)

    def testEBuildStable(self) -> None:
        """Test ebuild w/keyword variations"""
        basedir = os.path.join(self.tempdir, "cat", "test_package")
        fake_ebuild_path = os.path.join(basedir, "test_package-9999.ebuild")

        datasets = (
            ("~amd64", False),
            ("amd64", True),
            ("~amd64 ~arm ~x86", False),
            ("~amd64 arm ~x86", True),
            ("-* ~arm", False),
            ("-* x86", True),
        )
        for keywords, stable in datasets:
            fake_ebuild = self._MakeFakeEbuild(
                fake_ebuild_path,
                fake_ebuild_content=['KEYWORDS="%s"\n' % keywords],
            )
            self.assertEqual(fake_ebuild.is_stable, stable)

    def testEBuildManuallyUpreved(self) -> None:
        """Test manually uprevved ebuild"""
        basedir = os.path.join(self.tempdir, "cat", "test_package")
        fake_ebuild_path = os.path.join(basedir, "test_package-9999.ebuild")

        fake_ebuild = self._MakeFakeEbuild(fake_ebuild_path)
        self.assertEqual(fake_ebuild.is_manually_uprevved, False)

        PATTERNS = (
            "CROS_WORKON_BLACKLIST=1",
            'CROS_WORKON_BLACKLIST="1"',
            "CROS_WORKON_BLACKLIST='1'",
            "CROS_WORKON_MANUAL_UPREV=1",
            'CROS_WORKON_MANUAL_UPREV="1"',
            "CROS_WORKON_MANUAL_UPREV='1'",
        )
        for pattern in PATTERNS:
            fake_ebuild = self._MakeFakeEbuild(
                fake_ebuild_path, fake_ebuild_content=[pattern + "\n"]
            )
            self.assertTrue(fake_ebuild.is_manually_uprevved, msg=pattern)

    def testEBuildAutoUprev(self) -> None:
        """Test auto uprev ebuild"""
        basedir = os.path.join(self.tempdir, "cat", "test_package")
        fake_ebuild_path = os.path.join(basedir, "test_package-9999.ebuild")

        fake_ebuild = self._MakeFakeEbuild(fake_ebuild_path)
        self.assertEqual(fake_ebuild.is_manually_uprevved, False)

        PATTERNS = (
            "CROS_WORKON_MANUAL_UPREV=",
            "CROS_WORKON_MANUAL_UPREV=0",
        )
        for pattern in PATTERNS:
            fake_ebuild = self._MakeFakeEbuild(
                fake_ebuild_path, fake_ebuild_content=[pattern + "\n"]
            )
            self.assertFalse(fake_ebuild.is_manually_uprevved, msg=pattern)

    def testHasTest(self) -> None:
        """Tests that we detect test stanzas correctly."""

        def run_case(content, expected) -> None:
            with osutils.TempDir() as temp:
                ebuild = os.path.join(
                    temp, "overlay", "app-misc", "foo-0.0.1-r1.ebuild"
                )
                osutils.WriteFile(ebuild, content, makedirs=True)
                self.assertEqual(
                    expected, portage_util.EBuild(ebuild, False).has_test
                )

        run_case(self._MULTILINE_WITH_TEST, True)
        run_case(self._MULTILINE_NO_TEST, False)
        run_case(self._MULTILINE_COMMENTED, False)
        run_case(self._MULTILINE_PLATFORM, True)
        run_case(self._SINGLE_LINE_TEST, True)
        run_case(self._INHERIT_CROS_GO, True)
        run_case(self._INHERIT_TAST_BUNDLE, True)
        run_case(self._INHERIT_CROS_DEBUG, False)

    def testCheckHasTestWithoutEbuild(self) -> None:
        """Test CheckHasTest on a package without ebuild config file"""
        package_name = "chromeos-base/temp_mypackage"
        package_path = os.path.join(self.tempdir, package_name)
        os.makedirs(package_path)
        with self.assertRaises(failures_lib.PackageBuildFailure):
            portage_util._CheckHasTest(package_name, self.tempdir)

    def testEBuildGetAutotestTests(self) -> None:
        """Test extraction of test names from IUSE_TESTS variable.

        Used for autotest ebuilds.
        """

        def run_case(tests_str, results) -> None:
            settings = {"IUSE_TESTS": tests_str}
            self.assertEqual(
                portage_util.EBuild._GetAutotestTestsFromSettings(settings),
                results,
            )

        run_case(self._AUTOTEST_NORMAL[0], list(self._AUTOTEST_NORMAL[1]))
        run_case(
            self._AUTOTEST_EXTRA_PLUS[0], list(self._AUTOTEST_EXTRA_PLUS[1])
        )
        run_case(self._AUTOTEST_EXTRA_TAB[0], list(self._AUTOTEST_EXTRA_TAB[1]))

    def testAlmostSameEBuilds(self) -> None:
        """Test _AlmostSameEBuilds()."""

        def AlmostSameEBuilds(ebuild1_contents, ebuild2_contents):
            ebuild1_path = os.path.join(self.tempdir, "a.ebuild")
            ebuild2_path = os.path.join(self.tempdir, "b.ebuild")
            osutils.WriteFile(ebuild1_path, ebuild1_contents)
            osutils.WriteFile(ebuild2_path, ebuild2_contents)
            return portage_util.EBuild._AlmostSameEBuilds(
                ebuild1_path, ebuild2_path
            )

        self.assertTrue(AlmostSameEBuilds(self._EBUILD_BASE, self._EBUILD_BASE))
        self.assertTrue(
            AlmostSameEBuilds(self._EBUILD_BASE, self._EBUILD_DIFFERENT_COMMIT)
        )
        self.assertFalse(
            AlmostSameEBuilds(self._EBUILD_BASE, self._EBUILD_DIFFERENT_TREE)
        )
        self.assertFalse(
            AlmostSameEBuilds(self._EBUILD_BASE, self._EBUILD_DIFFERENT_CONTENT)
        )

    def testClassifySimple(self) -> None:
        """Test Classify on a simple ebuild."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        osutils.WriteFile(ebuild_path, "")
        attrs = portage_util.EBuild.Classify(ebuild_path)
        self.assertFalse(attrs.is_workon)
        self.assertFalse(attrs.is_stable)
        self.assertFalse(attrs.is_manually_uprevved)
        self.assertFalse(attrs.has_test)

    def testClassifyUnstable(self) -> None:
        """Test Classify handling of non-stable KEYWORDS."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        TESTS = (
            "KEYWORDS=",
            "KEYWORDS= # Yep.",
            'KEYWORDS="-*"',
            'KEYWORDS="-* ~arm"',
            'KEYWORDS="~*"',
        )
        for keywords in TESTS:
            osutils.WriteFile(ebuild_path, keywords)
            attrs = portage_util.EBuild.Classify(ebuild_path)
            self.assertFalse(attrs.is_stable, msg="Failing: %s" % (keywords,))

    def testClassifyStable(self) -> None:
        """Test Classify handling of stable KEYWORDS."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        TESTS = (
            'KEYWORDS="*"',
            'KEYWORDS="*" # Yep.',
            'KEYWORDS="-* arm"',
        )
        for keywords in TESTS:
            osutils.WriteFile(ebuild_path, keywords)
            attrs = portage_util.EBuild.Classify(ebuild_path)
            self.assertTrue(attrs.is_stable, msg="Failing: %s" % (keywords,))

    def testClassifyTestHost(self) -> None:
        """Test Classify handling of testable packages for the host."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        TESTS = (
            (True, ""),
            (True, "mirror"),
            (True, "!test? ( test )"),
            (False, "test"),
            (False, "cros_host? ( test )"),
        )
        flags = ["cros_host", "test"]
        for exp, val in TESTS:
            osutils.WriteFile(
                ebuild_path,
                "".join(
                    f"{x}\n" for x in ["src_test() { :; }", f'RESTRICT="{val}"']
                ),
            )
            attrs = portage_util.EBuild.Classify(ebuild_path, flags)
            self.assertEqual(attrs.has_test, exp, msg=f"Failing: {val}")

    def testClassifyTestParsing(self) -> None:
        """Test Classify RESTRICT parsing."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        TESTS = (
            "RESTRICT=",
            'RESTRICT="bin? ( foo )" # comment',
        )
        for val in TESTS:
            osutils.WriteFile(ebuild_path, f"{val}\n")
            portage_util.EBuild.Classify(ebuild_path)

    def testClassifyTestParsingCache(self) -> None:
        """Test Classify RESTRICT parsing with a cache file."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        # We want a diff value in the ebuild so the cache overrides.
        osutils.WriteFile(ebuild_path, "src_test() { :; }\nRESTRICT=test\n")
        flags = ["test", "foo"]

        TESTS = (
            (True, ""),
            (False, "RESTRICT=test"),
            (True, "RESTRICT=!test? ( test )"),
            (False, "RESTRICT=foo? ( test )"),
        )
        for exp, val in TESTS:
            cache = portage_md5_cache.Md5Cache(data=val)
            attrs = portage_util.EBuild.Classify(ebuild_path, flags, cache)
            assert attrs.has_test == exp

    def testClassifyWorkonCache(self) -> None:
        """Test Classify cros-workon parsing with a cache file."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        # We want a diff value in the ebuild so the cache overrides.
        osutils.WriteFile(ebuild_path, "inherit cros-workon\n")

        TESTS = (
            (False, ""),
            (True, "_eclasses_=cros-workon\tabcdef"),
        )
        for exp, val in TESTS:
            cache = portage_md5_cache.Md5Cache(data=val)
            attrs = portage_util.EBuild.Classify(
                ebuild_path, ebuild_cache=cache
            )
            assert attrs.is_workon == exp

    def testClassifyHasTestCache(self) -> None:
        """Test Classify has_test parsing with a cache file."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        # We want a diff value in the ebuild so the cache overrides.
        osutils.WriteFile(ebuild_path, "")

        TESTS = (
            (False, ""),
            (True, "_eclasses_=platform\tabcdef"),
        )
        for exp, val in TESTS:
            cache = portage_md5_cache.Md5Cache(data=val)
            attrs = portage_util.EBuild.Classify(
                ebuild_path, ebuild_cache=cache
            )
            assert attrs.has_test == exp

    def testClassifyEncodingASCII(self) -> None:
        """Test Classify with ASCII file encodings."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        # Generate a valid shell script with all possible ASCII values.
        osutils.WriteFile(
            ebuild_path,
            "cat <<\\EOF\n%s\nEOF\n"
            % ("".join(chr(x) for x in range(0, 128)),),
        )
        # Just check that we don't throw an exception.
        portage_util.EBuild.Classify(ebuild_path)

    def testClassifyEncodingUTF8(self) -> None:
        """Test Classify with UTF-8 file encodings."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        osutils.WriteFile(ebuild_path, "# FöÖßbäłł")
        # Just check that we don't throw an exception.
        portage_util.EBuild.Classify(ebuild_path)

    def testClassifyEncodingLatin1(self) -> None:
        """Test Classify with ISO 8859-1 file encodings."""
        ebuild_path = os.path.join(self.tempdir, "foo-1.ebuild")
        osutils.WriteFile(ebuild_path, b"# This is \xa0 bad UTF-8", mode="wb")
        with self.assertRaises(UnicodeDecodeError):
            portage_util.EBuild.Classify(ebuild_path)


class ProjectAndPathTest(cros_test_lib.MockTempDirTestCase):
    """Project and Path related tests."""

    def _MockParseWorkonVariables(
        self,
        fake_projects,
        fake_srcpaths,
        fake_localnames,
        fake_ebuild_contents,
    ):
        """Mock the necessary calls, call GetSourceInfo()."""

        def _isdir(path):
            """Mock function for os.path.isdir"""
            if any(fake_srcpaths):
                if path == os.path.join(self.tempdir, "src"):
                    return True

            for srcpath in fake_srcpaths:
                if srcpath:
                    if path == os.path.join(self.tempdir, "src", srcpath):
                        return True
                else:
                    for localname in fake_localnames:
                        if path == os.path.join(self.tempdir, localname):
                            return False
                        elif path == os.path.join(
                            self.tempdir, "platform", localname
                        ):
                            return True

            raise Exception("unhandled path: %s" % path)

        def _FindCheckoutFromPath(
            path, strict=True
        ):  # pylint: disable=unused-argument
            """Mock function for manifest.FindCheckoutFromPath"""
            for project, localname in zip(fake_projects, fake_localnames):
                if path == os.path.join(self.tempdir, "platform", localname):
                    return {"name": project, "local_path": localname}
            return {}

        self.PatchObject(os.path, "isdir", side_effect=_isdir)
        self.PatchObject(
            MANIFEST, "FindCheckoutFromPath", side_effect=_FindCheckoutFromPath
        )

        if not fake_srcpaths:
            fake_srcpaths = [""] * len(fake_projects)
        if not fake_projects:
            fake_projects = [""] * len(fake_srcpaths)

        # We need 'chromeos-base' here because it controls default _SUBDIR
        # values.
        ebuild_path = os.path.join(
            self.tempdir,
            "packages",
            "chromeos-base",
            "package",
            "package-9999.ebuild",
        )
        osutils.WriteFile(ebuild_path, fake_ebuild_contents, makedirs=True)

        ebuild = portage_util.EBuild(ebuild_path, False)
        return ebuild.GetSourceInfo(self.tempdir, MANIFEST)

    def testParseLegacyWorkonVariables(self) -> None:
        """Tests if ebuilds in a single item format are correctly parsed."""
        fake_project = "my_project1"
        fake_localname = "foo"
        fake_ebuild_contents = """
CROS_WORKON_PROJECT=%s
CROS_WORKON_LOCALNAME=%s
    """ % (
            fake_project,
            fake_localname,
        )
        info = self._MockParseWorkonVariables(
            [fake_project], [], [fake_localname], fake_ebuild_contents
        )
        self.assertEqual(info.projects, [fake_project])
        self.assertEqual(
            info.srcdirs,
            [os.path.join(self.tempdir, "platform", fake_localname)],
        )
        self.assertEqual(
            info.subtrees,
            [os.path.join(self.tempdir, "platform", fake_localname)],
        )

    def testParseAlwaysLive(self) -> None:
        """Tests if an ebuild which is always live is correctly handled."""
        fake_project = "my_project1"
        fake_localname = "foo"
        fake_ebuild_contents = """
CROS_WORKON_PROJECT=%s
CROS_WORKON_LOCALNAME=%s
CROS_WORKON_ALWAYS_LIVE=1
    """ % (
            fake_project,
            fake_localname,
        )
        info = self._MockParseWorkonVariables(
            [fake_project], [], [fake_localname], fake_ebuild_contents
        )
        self.assertEqual(info.projects, [])
        self.assertEqual(info.srcdirs, [])
        self.assertEqual(info.srcdirs, [])
        self.assertEqual(info.subtrees, [])

    def testParseArrayWorkonVariables(self) -> None:
        """Tests if ebuilds in an array format are correctly parsed."""
        fake_projects = ["my_project1", "my_project2", "my_project3"]
        fake_localnames = ["foo", "bar", "bas"]
        # The test content is formatted using the same function that
        # formats ebuild output, ensuring that we can parse our own
        # products.
        fake_ebuild_contents = """
CROS_WORKON_PROJECT=%s
CROS_WORKON_LOCALNAME=%s
    """ % (
            portage_util.EBuild.FormatBashArray(fake_projects),
            portage_util.EBuild.FormatBashArray(fake_localnames),
        )
        info = self._MockParseWorkonVariables(
            fake_projects, [], fake_localnames, fake_ebuild_contents
        )
        self.assertEqual(info.projects, fake_projects)
        fake_paths = [
            os.path.realpath(os.path.join(self.tempdir, "platform", x))
            for x in fake_localnames
        ]
        self.assertEqual(info.srcdirs, fake_paths)
        self.assertEqual(info.subtrees, fake_paths)

    def testParseArrayWorkonVariablesWithSubtrees(self) -> None:
        """Tests if ebuilds with CROS_WORKON_SUBTREE are handled correctly."""
        fake_project = "my_project1"
        fake_localname = "foo/bar"
        fake_subtrees = "test baz/quz"
        # The test content is formatted using the same function that
        # formats ebuild output, ensuring that we can parse our own
        # products.
        fake_ebuild_contents = """
CROS_WORKON_PROJECT=%s
CROS_WORKON_LOCALNAME=%s
CROS_WORKON_SUBTREE="%s"
    """ % (
            fake_project,
            fake_localname,
            fake_subtrees,
        )
        info = self._MockParseWorkonVariables(
            [fake_project], [], [fake_localname], fake_ebuild_contents
        )
        self.assertEqual(info.projects, [fake_project])
        self.assertEqual(
            info.srcdirs,
            [os.path.join(self.tempdir, "platform", fake_localname)],
        )
        self.assertEqual(
            info.subtrees,
            [
                os.path.join(self.tempdir, "platform", "foo/bar/test"),
                os.path.join(self.tempdir, "platform", "foo/bar/baz/quz"),
            ],
        )


class StubEBuild(portage_util.EBuild):
    """Test helper to StubEBuild."""

    def __init__(self, path, subdir_support) -> None:
        super().__init__(path, subdir_support)
        self.is_workon = True
        self.is_stable = True

    def _ReadEBuild(self, path, use_flags=None, cache=None) -> None:
        pass

    def GetCommitId(self, srcdir, ref: str = "HEAD"):
        id_map = {"p1_path1": "my_id1", "p1_path2": "my_id2"}
        if srcdir in id_map:
            return id_map[srcdir]
        else:
            return "you_lose"


class EBuildRevWorkonTest(cros_test_lib.MockTempDirTestCase):
    """Tests for EBuildRevWorkon."""

    # Lines that we will feed as fake ebuild contents to
    # EBuild.MarAsStable().  This is the minimum content needed
    # to test the various branches in the function's main processing
    # loop.
    _mock_ebuild = [
        "EAPI=2\n",
        "CROS_WORKON_COMMIT=old_id\n",
        "CROS_WORKON_PROJECT=test_package\n",
        'KEYWORDS="~x86 ~arm ~amd64"\n',
        "src_unpack(){}\n",
    ]
    _mock_ebuild_multi = [
        "EAPI=2\n",
        'CROS_WORKON_COMMIT=("old_id1","old_id2")\n',
        'KEYWORDS="~x86 ~arm ~amd64"\n',
        "src_unpack(){}\n",
    ]
    _revved_ebuild = (
        "EAPI=2\n"
        'CROS_WORKON_COMMIT="my_id1"\n'
        'CROS_WORKON_TREE=("treehash1a" "treehash1b")\n'
        "CROS_WORKON_PROJECT=test_package\n"
        'KEYWORDS="x86 arm amd64"\n'
        "src_unpack(){}\n"
    )
    _revved_ebuild_multi = (
        "EAPI=2\n"
        'CROS_WORKON_COMMIT=("my_id1" "my_id2")\n'
        'CROS_WORKON_TREE=("treehash1a" "treehash1b" "treehash2")\n'
        'KEYWORDS="x86 arm amd64"\n'
        "src_unpack(){}\n"
    )

    unstable_ebuild_changed = False

    def setUp(self) -> None:
        self.overlay = os.path.join(self.tempdir, "overlay")
        package_name_no_version = os.path.join(
            self.overlay, "category/test_package/test_package"
        )
        package_name_version = package_name_no_version + "-0.0.1"
        package_name_forced_version = package_name_no_version + "-777.0.0"
        ebuild_path = package_name_version + "-r1.ebuild"
        self.m_ebuild = StubEBuild(ebuild_path, False)
        self.revved_ebuild_path = package_name_version + "-r2.ebuild"
        self.revved_ebuild_path_forced_version = (
            package_name_forced_version + "-r1.ebuild"
        )
        self.git_files_changed = []

    def createRevWorkOnMocks(self, ebuild_content, rev, multi=False) -> None:
        """Creates a mock environment to run RevWorkOnEBuild.

        Args:
            ebuild_content: The content of the ebuild that will be revved.
            rev: Tell _RunGit whether this is attempt an attempt to rev an
                ebuild.
            multi: Whether there are multiple projects to uprev.
        """

        def _GetTreeId(path):
            """Mock function for portage_util.EBuild.GetTreeId"""
            return {
                "p1_path1/a": "treehash1a",
                "p1_path1/b": "treehash1b",
                "p1_path2": "treehash2",
            }.get(path)

        def _RunGit(cwd, cmd):
            """Mock function for portage_util.EBuild._RunGit"""
            if cmd[0] == "log":
                # special case for git log in the overlay:
                # report if -9999.ebuild supposedly changed
                if cwd == self.overlay and self.unstable_ebuild_changed:
                    return "someebuild-9999.ebuild"

                file_list = cmd[cmd.index("--") + 1 :]
                # Just get the last path component, so we can specify the
                # file_list without concerning ourselves with tempdir
                file_list = [os.path.split(f)[1] for f in file_list]
                # Return a stub file if we have changes in any of the listed
                # files.
                if set(self.git_files_changed).intersection(file_list):
                    return "somefile"
                return ""
            self.assertEqual(cwd, self.overlay)
            self.assertTrue(rev, msg="git should not be run when not revving")
            if cmd[0] == "add":
                self.assertEqual(cmd, ["add", self.revved_ebuild_path])
            else:
                self.assertTrue(self.m_ebuild.is_stable)
                self.assertEqual(cmd, ["rm", "-f", self.m_ebuild.ebuild_path])

        source_mock = self.PatchObject(portage_util.EBuild, "GetSourceInfo")
        if multi:
            source_mock.return_value = portage_util.SourceInfo(
                projects=["fake_project1", "fake_project2"],
                srcdirs=["p1_path1", "p1_path2"],
                subdirs=["files", None],
                subtrees=["p1_path1/a", "p1_path1/b", "p1_path2"],
            )
        else:
            source_mock.return_value = portage_util.SourceInfo(
                projects=["fake_project1"],
                srcdirs=["p1_path1"],
                subdirs=["files", None],
                subtrees=["p1_path1/a", "p1_path1/b"],
            )

        self.PatchObject(
            portage_util.EBuild, "GetTreeId", side_effect=_GetTreeId
        )
        self.PatchObject(portage_util.EBuild, "_RunGit", side_effect=_RunGit)

        osutils.WriteFile(
            self.m_ebuild._unstable_ebuild_path, ebuild_content, makedirs=True
        )
        osutils.WriteFile(
            self.m_ebuild.ebuild_path, ebuild_content, makedirs=True
        )

    def testRevWorkOnEBuild(self) -> None:
        """Test Uprev of a single project ebuild."""
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        result = self.m_ebuild.RevWorkOnEBuild(self.tempdir, MANIFEST)
        self.assertEqual(result[0], "category/test_package-0.0.1-r2")
        self.assertExists(self.revved_ebuild_path)
        self.assertEqual(
            self._revved_ebuild, osutils.ReadFile(self.revved_ebuild_path)
        )

    def testRevUnchangedEBuildOtherSubdirChange(self) -> None:
        """Uprev an other subdir with no CROS_WORKON_SUBTREE.

        The 'other' directory is changed in git, but there is no
        CROS_WORKON_SUBTREE in the build, so any change causes an uprev.
        """
        self.git_files_changed = ["other"]
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        self.m_ebuild.cros_workon_vars = portage_util.EBuild.GetCrosWorkonVars(
            self.m_ebuild.ebuild_path, "test-package"
        )
        result = self.m_ebuild.RevWorkOnEBuild(self.tempdir, MANIFEST)
        self.assertEqual(result[0], "category/test_package-0.0.1-r2")
        self.assertExists(self.revved_ebuild_path)
        self.assertEqual(
            self._revved_ebuild, osutils.ReadFile(self.revved_ebuild_path)
        )

    def testRevChangedEBuildNoSubdirChange(self) -> None:
        """Uprev a changed ebuild.

        Any change to the 9999 ebuild should cause an uprev.
        """
        self.unstable_ebuild_changed = True
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        self.m_ebuild.cros_workon_vars = portage_util.EBuild.GetCrosWorkonVars(
            self.m_ebuild.ebuild_path, "test-package"
        )
        result = self.m_ebuild.RevWorkOnEBuild(self.tempdir, MANIFEST)
        self.assertEqual(result[0], "category/test_package-0.0.1-r2")
        self.assertExists(self.revved_ebuild_path)
        self.assertEqual(
            self._revved_ebuild,
            osutils.ReadFile(self.revved_ebuild_path),
        )

    def testRevWorkOnMultiEBuild(self) -> None:
        """Test Uprev of a multi-project (array) ebuild."""
        self.createRevWorkOnMocks(self._mock_ebuild_multi, rev=True, multi=True)
        result = self.m_ebuild.RevWorkOnEBuild(self.tempdir, MANIFEST)
        self.assertEqual(result[0], "category/test_package-0.0.1-r2")
        self.assertExists(self.revved_ebuild_path)
        self.assertEqual(
            self._revved_ebuild_multi, osutils.ReadFile(self.revved_ebuild_path)
        )

    def testRevUnchangedEBuild(self) -> None:
        self.createRevWorkOnMocks(self._mock_ebuild, rev=False)

        self.PatchObject(
            portage_util.EBuild, "_AlmostSameEBuilds", return_value=True
        )
        result = self.m_ebuild.RevWorkOnEBuild(self.tempdir, MANIFEST)
        self.assertIsNone(result)
        self.assertNotExists(self.revved_ebuild_path)

    def testRevMissingEBuild(self) -> None:
        self.revved_ebuild_path = self.m_ebuild.ebuild_path
        self.m_ebuild.ebuild_path = self.m_ebuild._unstable_ebuild_path
        self.m_ebuild.current_revision = 0
        self.m_ebuild.is_stable = False

        self.createRevWorkOnMocks(
            self._mock_ebuild[0:1] + self._mock_ebuild[2:], rev=True
        )
        result = self.m_ebuild.RevWorkOnEBuild(self.tempdir, MANIFEST)

        self.assertEqual(result[0], "category/test_package-0.0.1-r1")
        self.assertExists(self.revved_ebuild_path)
        self.assertEqual(
            self._revved_ebuild, osutils.ReadFile(self.revved_ebuild_path)
        )

    def testRevForceStableVersionEBuild(self) -> None:
        """Test force stable version uprev of a ebuild."""
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        result = self.m_ebuild.RevWorkOnEBuild(
            self.tempdir, MANIFEST, new_version="777.0.0"
        )
        self.assertEqual(result[0], "category/test_package-777.0.0-r1")
        self.assertExists(self.revved_ebuild_path_forced_version)
        self.assertEqual(
            self._revved_ebuild,
            osutils.ReadFile(self.revved_ebuild_path_forced_version),
        )

    def testRevForceStableVersionSameVersionEBuild(self) -> None:
        """Test force stable version uprev of a ebuild with same version."""
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        result = self.m_ebuild.RevWorkOnEBuild(
            self.tempdir, MANIFEST, new_version="0.0.1"
        )
        self.assertEqual(result[0], "category/test_package-0.0.1-r2")
        self.assertExists(self.revved_ebuild_path)
        self.assertEqual(
            self._revved_ebuild, osutils.ReadFile(self.revved_ebuild_path)
        )

    def testRevInvalidVersionWithRevisionEBuild(self) -> None:
        """Test force stable version uprev of a ebuild with same version."""
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        with self.assertRaises(ValueError):
            self.m_ebuild.RevWorkOnEBuild(
                self.tempdir, MANIFEST, new_version="0.0.1-r777"
            )

    def testRevInvalidGibberishVersionEBuild(self) -> None:
        """Test force stable version uprev of a ebuild with same version."""
        self.createRevWorkOnMocks(self._mock_ebuild, rev=True)
        with self.assertRaises(ValueError):
            self.m_ebuild.RevWorkOnEBuild(
                self.tempdir, MANIFEST, new_version="gibberish-version-0000"
            )

    def testCommitChange(self) -> None:
        m = self.PatchObject(portage_util.EBuild, "_RunGit", return_value="")
        mock_message = "Commitme"
        self.m_ebuild.CommitChange(mock_message, ".")
        m.assert_called_once_with(".", ["commit", "-a", "-m", "Commitme"])

    def testGitRepoHasChanges(self) -> None:
        """Tests that GitRepoHasChanges works correctly."""
        git.RunGit(
            self.tempdir,
            [
                "clone",
                "--depth=1",
                f"file://{constants.CHROMITE_DIR}",
                self.tempdir,
            ],
        )
        # No changes yet as we just cloned the repo.
        self.assertFalse(portage_util.EBuild.GitRepoHasChanges(self.tempdir))
        # Update metadata but no real changes.
        osutils.Touch(os.path.join(self.tempdir, "LICENSE"))
        self.assertFalse(portage_util.EBuild.GitRepoHasChanges(self.tempdir))
        # A real change.
        osutils.WriteFile(os.path.join(self.tempdir, "LICENSE"), "hi")
        self.assertTrue(portage_util.EBuild.GitRepoHasChanges(self.tempdir))

    def testNoVersionScript(self) -> None:
        """Verify default behavior with no chromeos-version.sh script."""
        self.assertEqual("1234", self.m_ebuild.GetVersion(None, None, "1234"))

    def testValidVersionScript(self) -> None:
        """Verify normal behavior with a chromeos-version.sh script."""
        exists = self.PatchObject(os.path, "exists", return_value=True)
        self.PatchObject(
            portage_util.EBuild,
            "GetSourceInfo",
            return_value=portage_util.SourceInfo(
                projects=None, srcdirs=[], subdirs=[], subtrees=[]
            ),
        )
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc_mock.SetDefaultCmdResult(stdout="1122", stderr="STDERR")
        self.assertEqual("1122", self.m_ebuild.GetVersion(None, None, "1234"))
        # Sanity check.
        self.assertEqual(exists.call_count, 1)

    def testVersionScriptNoOutput(self) -> None:
        """Reject scripts that output nothing."""
        exists = self.PatchObject(os.path, "exists", return_value=True)
        self.PatchObject(
            portage_util.EBuild,
            "GetSourceInfo",
            return_value=portage_util.SourceInfo(
                projects=None, srcdirs=[], subdirs=[], subtrees=[]
            ),
        )
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())

        # Reject no output.
        rc_mock.SetDefaultCmdResult(stdout="", stderr="STDERR")
        self.assertRaises(
            portage_util.Error, self.m_ebuild.GetVersion, None, None, "1234"
        )
        # Sanity check.
        self.assertEqual(exists.call_count, 1)
        exists.reset_mock()

        # Reject simple output.
        rc_mock.SetDefaultCmdResult(stdout="\n", stderr="STDERR")
        self.assertRaises(
            portage_util.Error, self.m_ebuild.GetVersion, None, None, "1234"
        )
        # Sanity check.
        self.assertEqual(exists.call_count, 1)
        exists.reset_mock()

        # Reject error.
        rc_mock.SetDefaultCmdResult(
            returncode=1, stdout="FAIL\n", stderr="STDERR"
        )
        self.assertRaises(
            portage_util.Error, self.m_ebuild.GetVersion, None, None, "1234"
        )
        # Sanity check.
        self.assertEqual(exists.call_count, 1)

    def testVersionScriptTooHighVersion(self) -> None:
        """Reject scripts that output high version numbers."""
        exists = self.PatchObject(os.path, "exists", return_value=True)
        self.PatchObject(
            portage_util.EBuild,
            "GetSourceInfo",
            return_value=portage_util.SourceInfo(
                projects=None, srcdirs=[], subdirs=[], subtrees=[]
            ),
        )
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc_mock.SetDefaultCmdResult(stdout="999999", stderr="STDERR")
        self.assertRaises(
            ValueError, self.m_ebuild.GetVersion, None, None, "1234"
        )
        # Sanity check.
        self.assertEqual(exists.call_count, 1)

    def testVersionScriptInvalidVersion(self) -> None:
        """Reject scripts that output bad version numbers."""
        exists = self.PatchObject(os.path, "exists", return_value=True)
        self.PatchObject(
            portage_util.EBuild,
            "GetSourceInfo",
            return_value=portage_util.SourceInfo(
                projects=None, srcdirs=[], subdirs=[], subtrees=[]
            ),
        )
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc_mock.SetDefaultCmdResult(stdout="abcd", stderr="STDERR")
        self.assertRaises(
            ValueError, self.m_ebuild.GetVersion, None, None, "1234"
        )
        # Sanity check.
        self.assertEqual(exists.call_count, 1)

    def testVersionScriptInvalidVersionPostfix(self) -> None:
        """Reject scripts that output bad version numbers."""
        exists = self.PatchObject(os.path, "exists", return_value=True)
        self.PatchObject(
            portage_util.EBuild,
            "GetSourceInfo",
            return_value=portage_util.SourceInfo(
                projects=None, srcdirs=[], subdirs=[], subtrees=[]
            ),
        )
        rc_mock = self.StartPatcher(cros_test_lib.RunCommandMock())
        rc_mock.SetDefaultCmdResult(stdout="4.4.21_baseline", stderr="STDERR")
        with self.assertRaises(portage_util.EbuildVersionError):
            self.m_ebuild.GetVersion(None, None, "1234")
        # Sanity check.
        self.assertEqual(exists.call_count, 1)

    def testUpdateEBuildRecovery(self) -> None:
        """Verify UpdateEBuild can be called more than once even w/failures."""
        ebuild = os.path.join(self.tempdir, "test.ebuild")
        content = "# Some data\nVAR=val\n"
        osutils.WriteFile(ebuild, content)

        # First run: pass in an invalid redirect file to trigger an exception.
        try:
            portage_util.EBuild.UpdateEBuild(ebuild, [])
            self.fail("this should have thrown an exception")
        except Exception:
            pass
        self.assertEqual(content, osutils.ReadFile(ebuild))

        # Second run: it should pass normally.
        portage_util.EBuild.UpdateEBuild(ebuild, {"VAR": "b"})

    def testUpdateEBuildSpacing(self) -> None:
        """Verify UpdateEBuild does not edit marked variables."""
        ebuild = os.path.join(self.tempdir, "test.ebuild")
        content = (
            "# Some data\n"
            "VAR=a # portage_util: no edit\n"
            "VAR=b\n"
            "\tVAR=c\n"
        )
        expected_content = "# Some data\nVAR=d\nVAR=a # portage_util: no edit\n"
        osutils.WriteFile(ebuild, content)
        # Check that all VARs are removed except the one with no edit.
        portage_util.EBuild.UpdateEBuild(ebuild, {"VAR": "d"})
        self.assertEqual(expected_content, osutils.ReadFile(ebuild))
        # And check idempotency.
        portage_util.EBuild.UpdateEBuild(ebuild, {"VAR": "d"})
        self.assertEqual(expected_content, osutils.ReadFile(ebuild))


class ListOverlaysTest(cros_test_lib.TempDirTestCase):
    """Tests related to listing overlays."""

    def testMissingOverlays(self) -> None:
        """Tests that exceptions are raised when an overlay is missing."""
        self.assertRaises(
            portage_util.MissingOverlayError,
            portage_util._ListOverlays,
            board="foo",
            buildroot=self.tempdir,
        )


class FindOverlaysTest(cros_test_lib.MockTempDirTestCase):
    """Tests related to finding overlays."""

    FAKE, PUB_PRIV, PUB_PRIV_VARIANT, PUB_ONLY, PUB2_ONLY, PRIV_ONLY = (
        "fake!board",
        "pub-priv-board",
        "pub-priv-board_variant",
        "pub-only-board",
        "pub2-only-board",
        "priv-only-board",
    )
    PRIVATE = constants.PRIVATE_OVERLAYS
    PUBLIC = constants.PUBLIC_OVERLAYS
    BOTH = constants.BOTH_OVERLAYS

    def setUp(self) -> None:
        # Create an overlay tree to run tests against and isolate ourselves from
        # changes in the main tree.
        D = cros_test_lib.Directory
        overlay_files = (D("metadata", ("layout.conf",)),)
        board_overlay_files = overlay_files + (
            "make.conf",
            "toolchain.conf",
        )
        file_layout = (
            D(
                "src",
                (
                    D(
                        "overlays",
                        (
                            D(
                                "overlay-%s" % self.PUB_ONLY,
                                board_overlay_files,
                            ),
                            D(
                                "overlay-%s" % self.PUB2_ONLY,
                                board_overlay_files,
                            ),
                            D(
                                "overlay-%s" % self.PUB_PRIV,
                                board_overlay_files,
                            ),
                            D(
                                "overlay-%s" % self.PUB_PRIV_VARIANT,
                                board_overlay_files,
                            ),
                        ),
                    ),
                    D(
                        "private-overlays",
                        (
                            D(
                                "overlay-%s" % self.PUB_PRIV,
                                board_overlay_files,
                            ),
                            D(
                                "overlay-%s" % self.PUB_PRIV_VARIANT,
                                board_overlay_files,
                            ),
                            D(
                                "overlay-%s" % self.PRIV_ONLY,
                                board_overlay_files,
                            ),
                        ),
                    ),
                    D(
                        "third_party",
                        (
                            D("chromiumos-overlay", overlay_files),
                            D("portage-stable", overlay_files),
                        ),
                    ),
                ),
            ),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

        # Seed the board overlays.
        conf_data = "repo-name = %(repo-name)s\nmasters = %(masters)s"
        conf_path = os.path.join(
            self.tempdir,
            "src",
            "%(private)soverlays",
            "overlay-%(board)s",
            "metadata",
            "layout.conf",
        )

        for board in (
            self.PUB_PRIV,
            self.PUB_PRIV_VARIANT,
            self.PUB_ONLY,
            self.PUB2_ONLY,
        ):
            settings = {
                "board": board,
                "masters": "portage-stable ",
                "private": "",
                "repo-name": board,
            }
            if "_" in board:
                # TODO(b/236161656): Fix.
                # pylint: disable-next=use-maxsplit-arg
                settings["masters"] += board.split("_")[0]
            osutils.WriteFile(conf_path % settings, conf_data % settings)

        for board in (self.PUB_PRIV, self.PUB_PRIV_VARIANT, self.PRIV_ONLY):
            settings = {
                "board": board,
                "masters": "portage-stable ",
                "private": "private-",
                "repo-name": "%s-private" % board,
            }
            if "_" in board:
                # TODO(b/236161656): Fix.
                # pylint: disable-next=use-maxsplit-arg
                settings["masters"] += board.split("_")[0]
            osutils.WriteFile(conf_path % settings, conf_data % settings)

        # Seed the common overlays.
        conf_path = os.path.join(
            self.tempdir,
            "src",
            "third_party",
            "%(overlay)s",
            "metadata",
            "layout.conf",
        )
        osutils.WriteFile(
            conf_path % {"overlay": "chromiumos-overlay"},
            conf_data % {"repo-name": "chromiumos", "masters": ""},
        )
        osutils.WriteFile(
            conf_path % {"overlay": "portage-stable"},
            conf_data % {"repo-name": "portage-stable", "masters": ""},
        )

        # Now build up the list of overlays that we'll use in tests below.
        self.overlays = {}
        for b in (
            None,
            self.FAKE,
            self.PUB_PRIV,
            self.PUB_PRIV_VARIANT,
            self.PUB_ONLY,
            self.PUB2_ONLY,
            self.PRIV_ONLY,
        ):
            self.overlays[b] = d = {}
            for o in (self.PRIVATE, self.PUBLIC, self.BOTH, None):
                try:
                    d[o] = portage_util.FindOverlays(o, b, self.tempdir)
                except portage_util.MissingOverlayError:
                    d[o] = []
        self._no_overlays = not bool(any(d.values()))

    def testDuplicates(self) -> None:
        """Verify that no duplicate overlays are returned."""
        for d in self.overlays.values():
            for overlays in d.values():
                self.assertEqual(len(overlays), len(set(overlays)))

    def testOverlaysExist(self) -> None:
        """Verify that all overlays returned actually exist on disk."""
        for d in self.overlays.values():
            for overlays in d.values():
                self.assertTrue(all(os.path.isdir(x) for x in overlays))

    def testPrivatePublicOverlayTypes(self) -> None:
        """Verify public/private filtering.

        If we ask for results from 'both overlays', we should
        find all public and all private overlays.
        """
        for b, d in self.overlays.items():
            if b == self.FAKE:
                continue
            self.assertGreaterEqual(set(d[self.BOTH]), set(d[self.PUBLIC]))
            self.assertGreater(set(d[self.BOTH]), set(d[self.PRIVATE]))
            self.assertTrue(set(d[self.PUBLIC]).isdisjoint(d[self.PRIVATE]))

    def testNoOverlayType(self) -> None:
        """If we specify overlay_type=None, no results should be returned."""
        self.assertTrue(all(d[None] == [] for d in self.overlays.values()))

    def testNonExistentBoard(self) -> None:
        """Test what happens when a non-existent board is supplied.

        If we specify a non-existent board to FindOverlays, only generic
        overlays should be returned.
        """
        for o in (self.PUBLIC, self.BOTH):
            self.assertLess(
                set(self.overlays[self.FAKE][o]),
                set(self.overlays[self.PUB_PRIV][o]),
            )

    def testAllBoards(self) -> None:
        """If we specify board=None, all overlays should be returned."""
        for o in (self.PUBLIC, self.BOTH):
            for b in (self.FAKE, self.PUB_PRIV):
                self.assertLess(
                    set(self.overlays[b][o]), set(self.overlays[None][o])
                )

    def testReadOverlayFileOrder(self) -> None:
        """Verify that the boards are examined in the right order."""
        m = self.PatchObject(os.path, "isfile", return_value=False)
        portage_util.ReadOverlayFile(
            "test", self.PUBLIC, self.PUB_PRIV, self.tempdir
        )
        read_overlays = [x[0][0][:-5] for x in m.call_args_list]
        overlays = list(reversed(self.overlays[self.PUB_PRIV][self.PUBLIC]))
        self.assertEqual(read_overlays, overlays)

    def testFindOverlayFile(self) -> None:
        """Verify that the first file found is returned."""
        file_to_find = "something_special"
        full_path = os.path.join(
            self.tempdir,
            "src",
            "private-overlays",
            "overlay-%s" % self.PUB_PRIV,
            file_to_find,
        )
        osutils.Touch(full_path)
        self.assertEqual(
            full_path,
            portage_util.FindOverlayFile(
                file_to_find, self.BOTH, self.PUB_PRIV_VARIANT, self.tempdir
            ),
        )

    def testFoundPrivateOverlays(self) -> None:
        """Verify that private boards had their overlays located."""
        for b in (self.PUB_PRIV, self.PUB_PRIV_VARIANT, self.PRIV_ONLY):
            self.assertNotEqual(self.overlays[b][self.PRIVATE], [])
        self.assertNotEqual(
            self.overlays[self.PUB_PRIV][self.BOTH],
            self.overlays[self.PUB_PRIV][self.PRIVATE],
        )
        self.assertNotEqual(
            self.overlays[self.PUB_PRIV_VARIANT][self.BOTH],
            self.overlays[self.PUB_PRIV_VARIANT][self.PRIVATE],
        )

    def testFoundPublicOverlays(self) -> None:
        """Verify that public boards had their overlays located."""
        for b in (
            self.PUB_PRIV,
            self.PUB_PRIV_VARIANT,
            self.PUB_ONLY,
            self.PUB2_ONLY,
        ):
            self.assertNotEqual(self.overlays[b][self.PUBLIC], [])
        self.assertNotEqual(
            self.overlays[self.PUB_PRIV][self.BOTH],
            self.overlays[self.PUB_PRIV][self.PUBLIC],
        )
        self.assertNotEqual(
            self.overlays[self.PUB_PRIV_VARIANT][self.BOTH],
            self.overlays[self.PUB_PRIV_VARIANT][self.PUBLIC],
        )

    def testFoundParentOverlays(self) -> None:
        """Verify that the overlays for a parent board are found."""
        for d in self.PUBLIC, self.PRIVATE:
            self.assertLess(
                set(self.overlays[self.PUB_PRIV][d]),
                set(self.overlays[self.PUB_PRIV_VARIANT][d]),
            )


class UtilFuncsTest(cros_test_lib.TempDirTestCase):
    """Basic tests for utility functions"""

    def _CreateProfilesRepoName(self, name) -> None:
        """Write |name| to profiles/repo_name"""
        profiles = os.path.join(self.tempdir, "profiles")
        osutils.SafeMakedirs(profiles)
        repo_name = os.path.join(profiles, "repo_name")
        osutils.WriteFile(repo_name, name)

    def testGetOverlayNameNone(self) -> None:
        """If the overlay has no name, it should be fine"""
        self.assertEqual(portage_util.GetOverlayName(self.tempdir), None)

    def testGetOverlayNameProfilesRepoName(self) -> None:
        """Verify profiles/repo_name can be read"""
        self._CreateProfilesRepoName("hi!")
        self.assertEqual(portage_util.GetOverlayName(self.tempdir), "hi!")

    def testGetOverlayNameProfilesLayoutConf(self) -> None:
        """Verify metadata/layout.conf is read before profiles/repo_name"""
        self._CreateProfilesRepoName("hi!")
        metadata = os.path.join(self.tempdir, "metadata")
        osutils.SafeMakedirs(metadata)
        layout_conf = os.path.join(metadata, "layout.conf")
        osutils.WriteFile(layout_conf, "repo-name = bye")
        self.assertEqual(portage_util.GetOverlayName(self.tempdir), "bye")

    def testGetOverlayNameProfilesLayoutConfNoRepoName(self) -> None:
        """Verify metadata/layout.conf w/out repo-name is ignored"""
        self._CreateProfilesRepoName("hi!")
        metadata = os.path.join(self.tempdir, "metadata")
        osutils.SafeMakedirs(metadata)
        layout_conf = os.path.join(metadata, "layout.conf")
        osutils.WriteFile(layout_conf, "here = we go")
        self.assertEqual(portage_util.GetOverlayName(self.tempdir), "hi!")

    def testGetRepositoryFromEbuildInfo(self) -> None:
        """Verify GetRepositoryFromEbuildInfo handles data from ebuild info."""

        def _runTestGetRepositoryFromEbuildInfo(
            fake_projects, fake_srcdirs
        ) -> None:
            """Generate the output from ebuild info"""

            # ebuild info always puts () around the result, even for single
            # element array. It tends to use single quotes, though double
            # quotes are valid too.
            for quote in ("'", '"'):
                fake_ebuild_contents = f"""
CROS_WORKON_PROJECT=({quote}%s{quote})
CROS_WORKON_SRCDIR=({quote}%s{quote})
      """ % (
                    f"{quote} {quote}".join(fake_projects),
                    f"{quote} {quote}".join(fake_srcdirs),
                )
                result = portage_util.GetRepositoryFromEbuildInfo(
                    fake_ebuild_contents
                )
                result_srcdirs, result_projects = zip(*result)
                self.assertEqual(fake_projects, list(result_projects))
                self.assertEqual(fake_srcdirs, list(result_srcdirs))

        _runTestGetRepositoryFromEbuildInfo(["a", "b"], ["src_a", "src_b"])
        _runTestGetRepositoryFromEbuildInfo(["a"], ["src_a"])


class GetOverlayEBuildsTest(cros_test_lib.MockTempDirTestCase):
    """Tests for GetOverlayEBuilds."""

    def setUp(self) -> None:
        self.overlay = self.tempdir
        self.uprev_candidate_mock = self.PatchObject(
            portage_util,
            "_FindUprevCandidates",
            side_effect=GetOverlayEBuildsTest._FindUprevCandidateMock,
        )

    def _CreatePackage(self, name, manually_uprevved=False) -> None:
        """Helper that creates an ebuild."""
        package_path = os.path.join(
            self.overlay, name, "test_package-0.0.1.ebuild"
        )
        content = "CROS_WORKON_MANUAL_UPREV=1" if manually_uprevved else ""
        osutils.WriteFile(package_path, content, makedirs=True)

    @staticmethod
    def _FindUprevCandidateMock(files, allow_manual_uprev, _subdir_support):
        """Mock for the FindUprevCandidateMock function.

        Simplified implementation of FindUprevCandidate: consider an ebuild
        worthy of uprev if |allow_manual_uprev| is set or the ebuild is not
        manually uprevved.
        """
        for f in files:
            if f.endswith(".ebuild") and (
                "CROS_WORKON_MANUAL_UPREV=1" not in osutils.ReadFile(f)
                or allow_manual_uprev
            ):
                pkgdir = os.path.dirname(f)
                return _Package(
                    os.path.join(
                        os.path.basename(os.path.dirname(pkgdir)),
                        os.path.basename(pkgdir),
                    )
                )
        return None

    def _assertFoundPackages(self, ebuilds, packages) -> None:
        """Succeeds iff the packages discovered were packages."""
        self.assertEqual([e.package for e in ebuilds], packages)

    def testWantedPackage(self) -> None:
        """Test that we can find a specific package."""
        package_name = "chromeos-base/mypackage"
        self._CreatePackage(package_name)
        ebuilds = portage_util.GetOverlayEBuilds(
            self.overlay, False, [package_name]
        )
        self._assertFoundPackages(ebuilds, [package_name])

    def testUnwantedPackage(self) -> None:
        """Test that we find only the packages we want."""
        ebuilds = portage_util.GetOverlayEBuilds(self.overlay, False, [])
        self._assertFoundPackages(ebuilds, [])

    def testAnyPackage(self) -> None:
        """Test that we return all packages available if use_all is set."""
        package_name = "chromeos-base/package_name"
        self._CreatePackage(package_name)
        ebuilds = portage_util.GetOverlayEBuilds(self.overlay, True, [])
        self._assertFoundPackages(ebuilds, [package_name])

    def testUnknownPackage(self) -> None:
        """Test that _FindUprevCandidates is only called if the CP matches."""
        self._CreatePackage("chromeos-base/package_name")
        ebuilds = portage_util.GetOverlayEBuilds(
            self.overlay, False, ["chromeos-base/other_package"]
        )
        self.assertFalse(self.uprev_candidate_mock.called)
        self._assertFoundPackages(ebuilds, [])

    def testManuallyUprevedPackagesIgnoredByDefault(self) -> None:
        """Test that manually uprevved packages are ignored by default."""
        package_name = "chromeos-base/manuallyuprevved_package"
        self._CreatePackage(package_name, manually_uprevved=True)
        ebuilds = portage_util.GetOverlayEBuilds(
            self.overlay, False, [package_name]
        )
        self._assertFoundPackages(ebuilds, [])

    def testManuallyUprevedPackagesAllowed(self) -> None:
        """Test that we can find manually uprevved packages.

        When we specify the |allow_manual_uprev| parameter.
        """
        package_name = "chromeos-base/manuallyuprevved_package"
        self._CreatePackage(package_name, manually_uprevved=True)
        ebuilds = portage_util.GetOverlayEBuilds(
            self.overlay, False, [package_name], allow_manual_uprev=True
        )
        self._assertFoundPackages(ebuilds, [package_name])


class ProjectMappingTest(cros_test_lib.TestCase):
    """Tests related to Proejct Mapping."""

    def testSplitEbuildPath(self) -> None:
        """Test if we can split an ebuild path into its components."""
        ebuild_path = "chromeos-base/platform2/platform2-9999.ebuild"
        components = ["chromeos-base", "platform2", "platform2-9999"]
        for path in (ebuild_path, "./" + ebuild_path, "foo.bar/" + ebuild_path):
            self.assertEqual(components, portage_util.SplitEbuildPath(path))

    def testFindWorkonProjects(self) -> None:
        """Test if we can find the list of workon projects."""
        frecon = "sys-apps/frecon"
        frecon_project = "chromiumos/platform/frecon"
        dev_install = "chromeos-base/dev-install"
        dev_install_project = "chromiumos/platform2"
        matches = [
            ([frecon], {frecon_project}),
            ([dev_install], {dev_install_project}),
            ([frecon, dev_install], {frecon_project, dev_install_project}),
        ]
        if portage_util.FindOverlays(constants.BOTH_OVERLAYS):
            for packages, projects in matches:
                self.assertEqual(
                    projects, portage_util.FindWorkonProjects(packages)
                )


class PortageDBTest(cros_test_lib.TempDirTestCase):
    """Portage package Database related tests."""

    fake_pkgdb = {
        "category1": ["package-1", "package-2"],
        "category2": ["package-3", "package-4"],
        "category3": ["invalid", "semi-invalid"],
        "with": ["files-1"],
        "dash-category": ["package-5"],
        "-invalid": ["package-6"],
        "invalid": [],
    }
    fake_packages = []
    build_root = None
    fake_chroot = None

    fake_files = [
        ("dir", "/lib64"),
        (
            "obj",
            "/lib64/libext2fs.so.2.4",
            "a6723f44cf82f1979e9731043f820d8c",
            "1390848093",
        ),
        ("dir", "/dir with spaces"),
        (
            "obj",
            "/dir with spaces/file with spaces",
            "cd4865bbf122da11fca97a04dfcac258",
            "1390848093",
        ),
        ("sym", "/lib64/libe2p.so.2", "->", "libe2p.so.2.3", "1390850489"),
        "foo",
    ]

    def setUp(self) -> None:
        self.build_root = self.tempdir
        self.fake_packages = []
        # Prepare a fake chroot.
        self.fake_chroot = os.path.join(
            self.build_root, "chroot/build/amd64-host"
        )
        fake_pkgdb_path = os.path.join(self.fake_chroot, portage_util.VDB_PATH)
        os.makedirs(fake_pkgdb_path)
        for cat, pkgs in self.fake_pkgdb.items():
            catpath = os.path.join(fake_pkgdb_path, cat)
            if cat == "invalid":
                # Invalid category is a file. Should not be delved into.
                osutils.Touch(catpath)
                continue
            os.makedirs(catpath)
            for pkg in pkgs:
                pkgpath = os.path.join(catpath, pkg)
                if pkg == "invalid":
                    # Invalid package is a file instead of a directory/
                    osutils.Touch(pkgpath)
                    continue
                os.makedirs(pkgpath)
                if pkg.endswith("-invalid"):
                    # Invalid package does not meet existence of "%s/%s.ebuild"
                    # file.
                    osutils.Touch(os.path.join(pkgpath, "whatever"))
                    continue
                # Create the package.
                osutils.Touch(os.path.join(pkgpath, pkg + ".ebuild"))
                if cat.startswith("-"):
                    # Invalid category.
                    continue
                # Correct pkg.
                pv = package_info.parse(pkg)
                key = "%s/%s" % (cat, pv.package)
                self.fake_packages.append((key, pv.vr))
        # Add contents to with/files-1.
        osutils.WriteFile(
            os.path.join(fake_pkgdb_path, "with", "files-1", "CONTENTS"),
            "".join(" ".join(entry) + "\n" for entry in self.fake_files),
        )

    def testListInstalledPackages(self) -> None:
        """Test if listing packages installed into a root works."""
        packages = portage_util.ListInstalledPackages(self.fake_chroot)
        # Sort the lists, because the filesystem might reorder the entries for
        # us.
        packages.sort()
        self.fake_packages.sort()
        self.assertEqual(self.fake_packages, packages)

    def testCalculatePackageSizes_ApparentSize(self) -> None:
        """Test if calculating disk usage of installed packages works."""
        fake_data = "FAKE DATA"
        expected_size = 0
        for fake_file in self.fake_files:
            if fake_file[0] == "obj":
                fake_filename = os.path.join(
                    self.fake_chroot, os.path.relpath(fake_file[1], "/")
                )
                osutils.WriteFile(fake_filename, fake_data, makedirs=True)
                expected_size += len(fake_data)

        portage_db = portage_util.PortageDB(self.fake_chroot)
        installed_packages = portage_db.InstalledPackages()

        # Only one package in fake portage db has files associated with it.
        total_size = 0
        for p in installed_packages:
            sizes = portage_util.CalculatePackageSize(
                p.ListContents(), self.fake_chroot
            )
            total_size += sizes.apparent_size
        self.assertEqual(total_size, expected_size)

    def testCalculatePackageSizes_DiskUsage(self) -> None:
        """Test if calculating disk usage of installed packages works."""
        fake_data = "FAKE DATA"
        expected_size = 0
        for fake_file in self.fake_files:
            if fake_file[0] == "obj":
                fake_filename = os.path.join(
                    self.fake_chroot, os.path.relpath(fake_file[1], "/")
                )
                osutils.WriteFile(fake_filename, fake_data, makedirs=True)
                # Filesystems allocate 4096 bytes on disk for new files.
                expected_size += 8 * 512

        portage_db = portage_util.PortageDB(self.fake_chroot)
        installed_packages = portage_db.InstalledPackages()

        # Only one package in fake portage db has files associated with it.
        total_size = 0
        for p in installed_packages:
            sizes = portage_util.CalculatePackageSize(
                p.ListContents(), self.fake_chroot
            )
            total_size += sizes.disk_utilization_size
        self.assertEqual(total_size, expected_size)

    def testGeneratePackageSizes(self) -> None:
        """Test if calculating installed package sizes works."""
        fake_data = "FAKE DATA"
        expected_size = 0
        for fake_file in self.fake_files:
            if fake_file[0] == "obj":
                fake_filename = os.path.join(
                    self.fake_chroot, os.path.relpath(fake_file[1], "/")
                )
                osutils.WriteFile(fake_filename, fake_data, makedirs=True)
                expected_size += len(fake_data)

        portage_db = portage_util.PortageDB(self.fake_chroot)
        installed_packages = portage_db.InstalledPackages()
        package_size_pairs = portage_util.GeneratePackageSizes(
            portage_db, "fake_chroot", installed_packages
        )
        total_size = sum(x for _, x in package_size_pairs)
        self.assertEqual(total_size, expected_size)

    def testIsPackageInstalled(self) -> None:
        """Test if checking the existence of an installed package works."""
        self.assertTrue(
            portage_util.IsPackageInstalled(
                "category1/package", sysroot=self.fake_chroot
            )
        )
        self.assertFalse(
            portage_util.IsPackageInstalled(
                "category1/foo", sysroot=self.fake_chroot
            )
        )

    def testListContents(self) -> None:
        """Test if the list of installed files is properly parsed."""
        pdb = portage_util.PortageDB(self.fake_chroot)
        pkg = pdb.GetInstalledPackage("with", "files-1")
        self.assertTrue(pkg)
        lst = pkg.ListContents()

        # Check ListContents filters out the garbage we added to the list of
        # files.
        fake_files = [
            f for f in self.fake_files if f[0] in ("sym", "obj", "dir")
        ]
        self.assertEqual(len(fake_files), len(lst))

        # Check the paths are all relative.
        self.assertTrue(all(not f[1].startswith("/") for f in lst))

        # Check all the files are present. We only consider file type and path,
        # and convert the path to a relative path.
        fake_files = [(f[0], f[1].lstrip("/")) for f in fake_files]
        self.assertEqual(fake_files, lst)

    def testPackageInfo(self) -> None:
        """Verify construction and self consistency of the PackageInfo."""
        portage_db = portage_util.PortageDB(self.fake_chroot)
        for pkg in portage_db.InstalledPackages():
            self.assertEqual(pkg.category, pkg.package_info.category)
            self.assertEqual(pkg.pf, pkg.package_info.pvr)


class InstalledPackageTest(cros_test_lib.TempDirTestCase):
    """InstalledPackage class tests outside a PortageDB."""

    def setUp(self) -> None:
        content = (
            ("package-1.ebuild", "EAPI=1"),
            ("CATEGORY", "category-1\n"),
            ("DEPEND", "dev-libs/foo !dev-libs/bar >=sys-apps/pkg-12:0/0\n"),
            ("HOMEPAGE", "http://example.com\n"),
            ("LICENSE", "GPL-2\n"),
            ("NEEDED", "/usr/sbin/bootlockboxd libmetrics.so,libhwsec.so\n"),
            ("PF", "package-1\n"),
            ("PROVIDES", "x86_64: libsystem_api.so\n"),
            ("repository", "portage-stable\n"),
            ("RDEPEND", ">=sys-apps/pkg-12:0/0\n"),
            ("REQUIRES", "x86_64: libc++.so.1 libc++abi.so.1 libc.so.6\n"),
            ("SIZE", "123\n"),
        )
        for path, data in content:
            osutils.WriteFile(os.path.join(self.tempdir, path), data)

    def testOutOfDBPackage(self) -> None:
        """Verify InstalledPackage instance can be created w/o a PortageDB."""
        pkg = portage_util.InstalledPackage(None, self.tempdir)
        self.assertEqual([], pkg.bdepend.reduce())
        self.assertEqual("category-1", pkg.category)
        self.assertEqual(
            ["dev-libs/foo", "!dev-libs/bar", ">=sys-apps/pkg-12:0/0"],
            pkg.depend.reduce(),
        )
        self.assertEqual("http://example.com", pkg.homepage)
        self.assertEqual("GPL-2", pkg.license)
        self.assertEqual(
            {"/usr/sbin/bootlockboxd": ["libmetrics.so", "libhwsec.so"]},
            pkg.needed,
        )
        self.assertEqual("package-1", pkg.pf)
        self.assertEqual([">=sys-apps/pkg-12:0/0"], pkg.rdepend.reduce())
        self.assertEqual("portage-stable", pkg.repository)
        self.assertEqual(
            {"x86_64": ["libc++.so.1", "libc++abi.so.1", "libc.so.6"]},
            pkg.requires,
        )
        self.assertEqual("123", pkg.size)

    def testIncompletePackage(self) -> None:
        """Tests an incomplete or invalid package raises an exception."""
        # No package name is provided.
        os.unlink(os.path.join(self.tempdir, "PF"))
        self.assertRaises(
            portage_util.PortageDBError,
            portage_util.InstalledPackage,
            None,
            self.tempdir,
        )

        # Check that doesn't fail when the package name is provided.
        pkg = portage_util.InstalledPackage(None, self.tempdir, pf="package-1")
        self.assertEqual("package-1", pkg.pf)


class HasPrebuiltTest(cros_test_lib.RunCommandTestCase):
    """HasPrebuilt tests."""

    def setUp(self) -> None:
        self.atom = constants.CHROME_CP

    def testHasPrebuilt(self) -> None:
        """Test a package with a matching prebuilt."""
        self.rc.SetDefaultCmdResult(returncode=0)
        self.PatchObject(
            osutils, "ReadFile", return_value=json.dumps({self.atom: True})
        )

        self.assertTrue(portage_util.HasPrebuilt(self.atom))

    def testNoPrebuilt(self) -> None:
        """Test a package without a matching prebuilt."""
        self.rc.SetDefaultCmdResult(returncode=0)
        self.PatchObject(
            osutils, "ReadFile", return_value=json.dumps({self.atom: False})
        )
        self.assertFalse(portage_util.HasPrebuilt(self.atom))

    def testScriptFailure(self) -> None:
        """Test the script failure fail safe returns false."""
        self.rc.SetDefaultCmdResult(returncode=1)
        self.assertFalse(portage_util.HasPrebuilt(self.atom))


class PortageqBestVisibleTest(cros_test_lib.MockTestCase):
    """PortageqBestVisible tests."""

    def testValidPackage(self) -> None:
        """Test valid outputs."""
        expected = package_info.PackageInfo("cat", "pkg", "1.0")
        result = cros_build_lib.CompletedProcess(
            stdout=expected.cpvr, returncode=0
        )
        self.PatchObject(portage_util, "_Portageq", return_value=result)

        result = portage_util.PortageqBestVisible("cat/pkg")
        self.assertEqual(expected, result)


class PortageqEnvvarTest(cros_test_lib.MockTestCase):
    """PortageqEnvvar[s] tests."""

    def testValidEnvvar(self) -> None:
        """Test valid variables."""
        result = cros_build_lib.CompletedProcess(
            stdout="TEST=value\n", returncode=0
        )
        self.PatchObject(portage_util, "_Portageq", return_value=result)

        envvar1 = portage_util.PortageqEnvvar("TEST")
        envvars1 = portage_util.PortageqEnvvars(["TEST"])

        self.assertEqual("value", envvar1)
        self.assertEqual(envvar1, envvars1["TEST"])

    def testUndefinedEnvvars(self) -> None:
        """Test undefined variable handling."""
        # The variable exists in the command output even when not actually
        # defined.
        result = cros_build_lib.CompletedProcess(
            stdout="DOES_NOT_EXIST=\n", returncode=1
        )
        success_error = cros_build_lib.RunCommandError("", result)
        self.PatchObject(portage_util, "_Portageq", side_effect=success_error)

        # Test ignoring error when just from undefined variable.
        envv = portage_util.PortageqEnvvar(
            "DOES_NOT_EXIST", allow_undefined=True
        )
        envvs = portage_util.PortageqEnvvars(
            ["DOES_NOT_EXIST"], allow_undefined=True
        )
        self.assertEqual("", envv)
        self.assertEqual(envv, envvs["DOES_NOT_EXIST"])

        # Test raising the error when just from undefined variable.
        with self.assertRaises(portage_util.PortageqError):
            portage_util.PortageqEnvvar("DOES_NOT_EXIST")
        with self.assertRaises(portage_util.PortageqError):
            portage_util.PortageqEnvvars(["DOES_NOT_EXIST"])

        run_error = cros_build_lib.CompletedProcess(stdout="\n", returncode=2)
        failure_error = cros_build_lib.RunCommandError("", run_error)
        self.PatchObject(portage_util, "_Portageq", side_effect=failure_error)

        # Test re-raising the error when the command did not run successfully.
        with self.assertRaises(cros_build_lib.RunCommandError):
            portage_util.PortageqEnvvar("DOES_NOT_EXIST")
        with self.assertRaises(cros_build_lib.RunCommandError):
            portage_util.PortageqEnvvars(["DOES_NOT_EXIST"])

    def testInvalidEnvvars(self) -> None:
        """Test invalid variables handling."""
        # Envvar tests.
        with self.assertRaises(TypeError):
            portage_util.PortageqEnvvar([])
        with self.assertRaises(ValueError):
            portage_util.PortageqEnvvar("")

        # Envvars tests.
        self.assertEqual({}, portage_util.PortageqEnvvars([]))
        with self.assertRaises(TypeError):
            portage_util.PortageqEnvvars("")

        # Raised when extending the command list. This is currently expected,
        # and ints should not be accepted, but more formal handling can be
        # added.
        with self.assertRaises(TypeError):
            portage_util.PortageqEnvvars(1)


class PortageqHasVersionTest(cros_test_lib.MockTestCase):
    """PortageqHasVersion tests."""

    def testPortageqHasVersion(self) -> None:
        """Test HasVersion."""
        result_true = cros_build_lib.CompletedProcess(returncode=0)
        result_false = cros_build_lib.CompletedProcess(returncode=1)
        result_error = cros_build_lib.CompletedProcess(returncode=2)

        # Test has version.
        self.PatchObject(portage_util, "_Portageq", return_value=result_true)
        self.assertTrue(portage_util.PortageqHasVersion("cat/pkg"))

        # Test not has version.
        self.PatchObject(portage_util, "_Portageq", return_value=result_false)
        self.assertFalse(portage_util.PortageqHasVersion("cat/pkg"))

        # Test run error.
        self.PatchObject(portage_util, "_Portageq", return_value=result_error)
        self.assertFalse(portage_util.PortageqHasVersion("cat/pkg"))


class PortageqMatchTest(cros_test_lib.MockTestCase):
    """PortageqMatch tests."""

    def testMultiError(self) -> None:
        """Test unspecific query results in error.

        The method currently isn't setup to support multiple values in the
        output. It is instead interpreted as a cpv format error by SplitCPV.
        This isn't a hard requirement, just the current expected behavior.
        """
        output_str = "cat-1/pkg-one-1.0\ncat-2/pkg-two-2.1.3-r45\n"
        result = cros_build_lib.CompletedProcess(
            returncode=0, stdout=output_str
        )
        self.PatchObject(portage_util, "_Portageq", return_value=result)

        with self.assertRaises(ValueError):
            portage_util.PortageqMatch("*/*")

    def testValidPackage(self) -> None:
        """Test valid package produces the corresponding PackageInfo."""
        cpvr = "cat/pkg-1.0-r1"
        result = cros_build_lib.CompletedProcess(returncode=0, stdout=cpvr)
        self.PatchObject(portage_util, "_Portageq", return_value=result)

        pkg = portage_util.PortageqMatch("cat/pkg")
        self.assertIsInstance(pkg, package_info.PackageInfo)
        assert pkg == cpvr


class FindEbuildTest(cros_test_lib.RunCommandTestCase):
    """Tests for FindEbuildsForPackages and FindEbuildsForPackages."""

    def testFindEbuildsForPackagesReturnResultsSimple(self) -> None:
        equery_output = (
            "/chromeos-overlay/misc/foo/foo.ebuild\n"
            "/chromeos-overlay/misc/bar/bar.ebuild\n"
        )
        self.rc.AddCmdResult(
            [
                "equery",
                "--no-color",
                "--no-pipe",
                "which",
                "misc/foo",
                "misc/bar",
            ],
            stdout=equery_output,
        )
        self.assertEqual(
            portage_util.FindEbuildsForPackages(
                ["misc/foo", "misc/bar"], sysroot="/build/nami"
            ),
            {
                "misc/bar": "/chromeos-overlay/misc/bar/bar.ebuild",
                "misc/foo": "/chromeos-overlay/misc/foo/foo.ebuild",
            },
        )

    def testFindEbuildsForPackagesWithoutCategoryReturnResults(self) -> None:
        equery_output = (
            "/chromeos-overlay/misc/foo/foo.ebuild\n"
            "/chromeos-overlay/misc/bar/bar.ebuild\n"
        )
        self.rc.AddCmdResult(
            ["equery", "--no-color", "--no-pipe", "which", "misc/foo", "bar"],
            stdout=equery_output,
        )
        self.assertEqual(
            portage_util.FindEbuildsForPackages(
                ["misc/foo", "bar"], sysroot="/build/nami"
            ),
            {
                "bar": "/chromeos-overlay/misc/bar/bar.ebuild",
                "misc/foo": "/chromeos-overlay/misc/foo/foo.ebuild",
            },
        )

    def testFindEbuildsForPackagesReturnResultsComplexPackages(self) -> None:
        ebuild_path = (
            "/portage-stable/sys-libs/timezone-data/timezone-data-2018i.ebuild"
        )
        equery_output = "\n".join([ebuild_path] * 4)
        packages = [
            # CATEGORY/PN
            "sys-libs/timezone-data",
            # CATEGORY/P
            "sys-libs/timezone-data-2018i",
            # CATEGORY/PN:SLOT
            "sys-libs/timezone-data:0",
            # CATEGORY/P:SLOT
            "sys-libs/timezone-data-2018i:0",
        ]
        self.rc.AddCmdResult(
            ["equery", "--no-color", "--no-pipe", "which"] + packages,
            stdout=equery_output,
        )
        self.assertEqual(
            portage_util.FindEbuildsForPackages(
                packages, sysroot="/build/nami"
            ),
            {
                "sys-libs/timezone-data": ebuild_path,
                "sys-libs/timezone-data-2018i:0": ebuild_path,
                "sys-libs/timezone-data:0": ebuild_path,
                "sys-libs/timezone-data-2018i": ebuild_path,
            },
        )

    def testFindEbuildsForPackagesReturnNone(self) -> None:
        # Result for package 'bar' is missing.
        equery_output = "/chromeos-overlay/bar/bar.ebuild\n"
        self.rc.AddCmdResult(
            ["equery", "--no-color", "--no-pipe", "which", "foo", "bar"],
            stdout=equery_output,
            returncode=1,
        )
        self.assertEqual(
            portage_util.FindEbuildsForPackages(
                ["foo", "bar"], sysroot="/build/nami"
            ),
            {},
        )

    def testFindEbuildsForPackagesInvalidEbuildsOrder(self) -> None:
        equery_output = (
            "/chromeos-overlay/bar/bar.ebuild\n"
            "/chromeos-overlay/foo/foo.ebuild\n"
        )
        self.rc.AddCmdResult(
            ["equery", "--no-color", "--no-pipe", "which", "foo", "bar"],
            stdout=equery_output,
        )
        with self.assertRaises(AssertionError):
            portage_util.FindEbuildsForPackages(
                ["foo", "bar"], sysroot="/build/nami"
            )

    def testFindEbuildForPackageReturnResults(self) -> None:
        equery_output = "/chromeos-overlay/misc/foo/foo-9999.ebuild\n"
        self.rc.AddCmdResult(
            ["equery", "--no-color", "--no-pipe", "which", "misc/foo"],
            stdout=equery_output,
        )
        self.assertEqual(
            portage_util.FindEbuildForPackage(
                "misc/foo", sysroot="/build/nami"
            ),
            "/chromeos-overlay/misc/foo/foo-9999.ebuild",
        )

    def testFindEbuildForPackageReturnNone(self) -> None:
        equery_output = "Cannot find ebuild for package 'foo'\n"
        self.rc.AddCmdResult(
            ["equery", "--no-color", "--no-pipe", "which", "foo"],
            stdout=equery_output,
            returncode=1,
        )
        self.assertEqual(
            portage_util.FindEbuildForPackage("foo", sysroot="/build/nami"),
            None,
        )


class FindPackageNamesForFilesTest(cros_test_lib.RunCommandTestCase):
    """Tests for FindPackageNamesForFiles."""

    belongs_cmd = ["equery", "--no-color", "--no-pipe", "--quiet", "belongs"]

    def testFindPackageNamesForFilesSimple(self) -> None:
        self.rc.AddCmdResult(
            self.belongs_cmd + ["/some/file"],
            stdout="some-category/some-package-0.2-r2\n",
        )
        packages = portage_util.FindPackageNamesForFiles("/some/file")
        expected = package_info.PackageInfo(
            "some-category", "some-package", "0.2", 2
        )
        self.assertEqual(packages, [expected])

    def testFindPackageNamesForFilesNoResults(self) -> None:
        self.rc.AddCmdResult(self.belongs_cmd + ["/some/file"], stdout="")
        packages = portage_util.FindPackageNamesForFiles("/some/file")
        self.assertEqual(packages, [])


class FindOverlaysForPackagesTest(cros_test_lib.RunCommandTestCase):
    """Tests for FindOverlaysForPackages."""

    list_cmd = [
        "equery",
        "--no-color",
        "--no-pipe",
        "--quiet",
        "list",
        "--format=$repo",
    ]

    def testFindOverlaysForPackagesSimple(self) -> None:
        self.rc.AddCmdResult(
            self.list_cmd + ["qemu", "rust"],
            stdout="portage-stable\nchromiumos\n",
        )
        overlays = portage_util.FindOverlaysForPackages("qemu", "rust")
        self.assertEqual(overlays, ["portage-stable", "chromiumos"])

    def testFindOverlaysForPackagesNoResult(self) -> None:
        # Equery list bails from processing further arguments if it hits an
        # invalid / not-installed package. Error should propagate as there's no
        # use case for this yet, and we'd need multiple executions to provide a
        # meaningful result.
        self.rc.AddCmdResult(self.list_cmd + ["fnord"], returncode=3, stdout="")
        with self.assertRaises(cros_build_lib.RunCommandError):
            portage_util.FindOverlaysForPackages("fnord")

    def testFindOverlaysForPackagesNoArgs(self) -> None:
        # The output of `equery list` is its help if no arg given. Ensure it is
        # not processed.
        self.rc.SetDefaultCmdResult(2, "equery\nhelp\ntext\n")
        overlays = portage_util.FindOverlaysForPackages()
        self.assertEqual(overlays, [])

    def testFindOverlaysForPackagesInvalidResult(self) -> None:
        # With a valid returncode, `equery list` should always report a line for
        # each arg. This is validated principally to ensure any run mocks are
        # set up correctly.
        self.rc.AddCmdResult(self.list_cmd + ["fnord"], stdout="")
        with self.assertRaises(ValueError):
            portage_util.FindOverlaysForPackages("fnord")


_EQUERY_OUTPUT_CORPUS = """

virtual/editor-0:
 [  0]  virtual/editor-0   
 [  1]  app-editors/nano-4.2   
 [  1]  app-editors/emacs-26.1-r3   
 [  1]  app-editors/qemacs-0.4.1_pre20170225   
 [  1]  app-editors/vim-8.1.1486   
 [  1]  app-misc/mc-4.8.10   
 [  1]  sys-apps/busybox-1.29.3   
 [  1]  sys-apps/ed-1.14.2   
"""


class DepTreeTest(cros_test_lib.TestCase):
    """Tests for GetDepTreeForPackage & parsing"""

    def testParseDepTreeOutput(self) -> None:
        expected = [
            "virtual/editor-0",
            "app-editors/nano-4.2",
            "app-editors/emacs-26.1-r3",
            "app-editors/qemacs-0.4.1_pre20170225",
            "app-editors/vim-8.1.1486",
            "app-misc/mc-4.8.10",
            "sys-apps/busybox-1.29.3",
            "sys-apps/ed-1.14.2",
        ]
        self.assertEqual(
            expected, portage_util._ParseDepTreeOutput(_EQUERY_OUTPUT_CORPUS)
        )


_EMERGE_PRETEND_SDK_OUTPUT_CORPUS = """\
 N f   sys-devel/binutils 2.27.0-r23 to /var/empty/
  R    dev-python/sphinxcontrib-jsmath 1.0.1-r1
  R    virtual/perl-JSON-PP 2.273.0-r4
  R    sys-libs/readline 6.3_p8-r2
 N     sys-libs/readline 6.3_p8-r2 to /var/empty/
 N     app-shells/bash 4.3_p48-r3 to /var/empty/
 N     sys-libs/glibc 2.27-r18 to /var/empty/
"""


class PackageDependenciesTest(cros_test_lib.RunCommandTestCase):
    """Tests for GetPackageDependencies & parsing"""

    def testParseDepTreeOutput(self) -> None:
        expected = [
            "sys-devel/binutils-2.27.0-r23",
            "dev-python/sphinxcontrib-jsmath-1.0.1-r1",
            "virtual/perl-JSON-PP-2.273.0-r4",
            "sys-libs/readline-6.3_p8-r2",
            "sys-libs/readline-6.3_p8-r2",
            "app-shells/bash-4.3_p48-r3",
            "sys-libs/glibc-2.27-r18",
        ]
        self.rc.AddCmdResult(
            partial_mock.Ignore(), stdout=_EMERGE_PRETEND_SDK_OUTPUT_CORPUS
        )
        self.assertEqual(
            expected,
            portage_util.GetPackageDependencies("target-chromium-os-sdk"),
        )


class FindEbuildsForOverlaysTest(cros_test_lib.MockTempDirTestCase):
    """Tests for FindEbuildsForOverlays."""

    def setUp(self) -> None:
        file_layout = (
            cros_test_lib.Directory("package1/bar1", ["bar1-1.0.ebuild"]),
            cros_test_lib.Directory("package2/bar2", ["bar2-2.0.ebuild"]),
        )
        cros_test_lib.CreateOnDiskHierarchy(self.tempdir, file_layout)

    def testFindEbuildsForOverlaysOutput(self) -> None:
        mock_overlay_paths = [
            self.tempdir / "package1" / "bar1",
            self.tempdir / "package2" / "bar2",
        ]
        expected_ebuilds = [
            self.tempdir / "package1" / "bar1" / "bar1-1.0.ebuild",
            self.tempdir / "package2" / "bar2" / "bar2-2.0.ebuild",
        ]

        ebuilds = yield from portage_util.FindEbuildsForOverlays(
            mock_overlay_paths
        )

        self.assertEqual(expected_ebuilds, ebuilds)


_EQUERY_DEPENDS_OUTPUT_CORPUS = """\
app-admin/perl-cleaner-2.20
app-shells/bash-completion-2.8-r1
chromeos-base/chromeos-base-1-r11
sys-apps/portage-3.0.21-r73
sys-devel/crossdev-20211027-r1
virtual/target-chromium-os-sdk-1-r219
"""


class GetReverseDependenciesTest(cros_test_lib.RunCommandTestCase):
    """Tests for GetReverseDependencies."""

    def testGetReverseDependencies(self) -> None:
        expected = [
            package_info.parse("app-admin/perl-cleaner-2.20"),
            package_info.parse("app-shells/bash-completion-2.8-r1"),
            package_info.parse("chromeos-base/chromeos-base-1-r11"),
            package_info.parse("sys-apps/portage-3.0.21-r73"),
            package_info.parse("sys-devel/crossdev-20211027-r1"),
            package_info.parse("virtual/target-chromium-os-sdk-1-r219"),
        ]
        self.rc.AddCmdResult(
            partial_mock.Ignore(), stdout=_EQUERY_DEPENDS_OUTPUT_CORPUS
        )

        result = portage_util.GetReverseDependencies(["app-shells/bash"])

        self.assertEqual(expected, result)

    def testGetReverseDependenciesNone(self) -> None:
        self.rc.AddCmdResult(partial_mock.Ignore(), stdout="\n")

        result = portage_util.GetReverseDependencies(["fake/package"])

        self.assertEqual([], result)

    def testGetReverseDependenciesValueError(self) -> None:
        with self.assertRaises(ValueError) as e:
            portage_util.GetReverseDependencies([])

            self.assertEqual("Must provide at least one package.", e)


class RegenDependencyCacheTest(
    cros_test_lib.RunCommandTestCase, cros_test_lib.LoggingTestCase
):
    """Tests for RegenDependencyCache."""

    def testRegenDependencyCache(self) -> None:
        with cros_test_lib.LoggingCapturer() as logs:
            portage_util.RegenDependencyCache()

            self.AssertLogsContain(logs, "Rebuilding Portage dependency cache.")

        self.assertCommandContains(["parallel_emerge", "--regen", "--quiet"])

    def testRegenDependencyCacheBoard(self) -> None:
        portage_util.RegenDependencyCache(board="eve")

        self.assertCommandContains(["--board=eve"])

    def testRegenDependencyCacheSysroot(self) -> None:
        portage_util.RegenDependencyCache(sysroot="/build/eve")

        self.assertCommandContains(["--sysroot=/build/eve"])

    def testRegenDependencyCacheJobs(self) -> None:
        portage_util.RegenDependencyCache(jobs=10)

        self.assertCommandContains(["--jobs=10"])


# Manifest file format:
# https://wiki.gentoo.org/wiki/Repository_format/package/Manifest
_EBUILD_MANIFEST_CONTENT = """\
DIST foo 7 BLAKE2B 123abc SHA512 456def
DIST bar 8 SHA256 abc123 WHIRLPOOL xyz789 SHA512 def456
AUX foobar 99 MD5 abc123def
"""


class EbuildManifestFileHashTest(cros_test_lib.TempDirTestCase):
    """Test for EbuildManifestFileHash."""

    def testEbuildManifestFileHash(self) -> None:
        manifest_path = os.path.join(self.tempdir, "Manifest")
        osutils.WriteFile(manifest_path, _EBUILD_MANIFEST_CONTENT)
        h = portage_util.EbuildManifestFileHash(self.tempdir, "foo", "SHA512")
        self.assertEqual(h, "456def")
        h = portage_util.EbuildManifestFileHash(self.tempdir, "bar", "SHA256")
        self.assertEqual(h, "abc123")
        h = portage_util.EbuildManifestFileHash(
            self.tempdir, "foobar", "MD5", entry_type="AUX"
        )
        self.assertEqual(h, "abc123def")


@pytest.mark.parametrize(
    "data,expected",
    (
        ('{"test": 1}', {"test": 1}),
        ('{"int": 1, "list": [1, 2, 3]}', {"int": 1, "list": [1, 2, 3]}),
        ('{"test": 1}\n{"test": 2}', {"test": 3}),
        (
            '{"test": 1, "list": ["a", "b"]}\n{"test": 2, "list": ["c", "d"]}',
            {"test": 3, "list": ["a", "b", "c", "d"]},
        ),
    ),
)
def test_read_depgraph_counters_and_combine(data, expected) -> None:
    assert portage_util.read_depgraph_counters(data) == expected


@pytest.mark.parametrize(
    "data,expected",
    (
        ('{"test": 1}', [{"test": 1}]),
        ('{"int": 1, "list": [1, 2, 3]}', [{"int": 1, "list": [1, 2, 3]}]),
        ('{"test": 1}\n{"test": 2}', [{"test": 1}, {"test": 2}]),
        (
            '{"test": 1, "list": ["a", "b"]}\n{"test": 2, "list": ["c", "d"]}',
            [{"test": 1, "list": ["a", "b"]}, {"test": 2, "list": ["c", "d"]}],
        ),
    ),
)
def test_read_depgraph_counters_no_combine(data, expected) -> None:
    assert portage_util.read_depgraph_counters(data, combine=False) == expected


def test_parse_die_hook_status_file(monkeypatch, tmp_path) -> None:
    status_file = tmp_path / constants.DIE_HOOK_STATUS_FILE_NAME
    monkeypatch.setattr(
        portage_util, "get_die_hook_status_file", lambda: status_file
    )
    content = """
foo/bar-1.2.3 src_install
   \n
cat/pkg-2-r2\tpkg_post_inst
another/pkg-3 unknown
\t

"""
    expected = [
        package_info.parse("foo/bar-1.2.3"),
        package_info.parse("cat/pkg-2-r2"),
        package_info.parse("another/pkg-3"),
    ]
    status_file.write_text(content)
    result = portage_util.ParseDieHookStatusFile()

    assert sorted(expected) == sorted(result)


def test_get_cache_file(tmp_path) -> None:
    """Verify parsing ebuild filenames to cache filenames."""
    with pytest.raises(portage_util.MissingCacheEntry):
        portage_util.get_cache_file(Path("/overlay/foo/bar/bar-1.ebuild"))

    ebuild = tmp_path / "overlay-o" / "cat" / "foo" / "foo-1.ebuild"
    cache = tmp_path / "overlay-o" / "metadata" / "md5-cache" / "cat" / "foo-1"
    cache.parent.mkdir(parents=True)
    cache.touch()
    assert portage_util.get_cache_file(ebuild) == cache


class AnalyzeEmergeFailureTest(cros_test_lib.TestCase):
    """Test emerge failure analysis."""

    def testSlotConflictErrors(self):
        """Test detect multi version slot conflicts."""
        result = portage_util.analyze_emerge_failure(
            AnalyzeEmergeFailureReasons.MULTIVERSION_ERROR
        )
        result.sort(key=lambda e: e.pkg)

        self.assertEqual(result[0].pkg, "chromeos-base/patchpanel:0")
        self.assertEqual(
            result[0].kind, portage_util.ErrorKind.MULTI_VERSION_CONFLICT
        )
        self.assertEqual(result[1].pkg, "chromeos-base/system_api:0")
        self.assertEqual(
            result[1].kind, portage_util.ErrorKind.MULTI_VERSION_CONFLICT
        )

    def testEbuildMaskedError(self):
        """Detect EBUILD_MASKED error from output log."""
        result = portage_util.analyze_emerge_failure(
            AnalyzeEmergeFailureReasons.MASKED_PACKAGE_ERROR
        )

        self.assertListEqual(
            result,
            [
                portage_util.PortageError(
                    kind=portage_util.ErrorKind.EBUILD_MASKED,
                    pkg="media-sound/adhd-0.0.7-r3267",
                    reason="masked by: package.mask",
                ),
            ],
        )

    def testUseFlagUnsatisfiableError(self):
        """Detect USE_FLAG_UNSATISFIABLE in output log."""
        result = portage_util.analyze_emerge_failure(
            AnalyzeEmergeFailureReasons.USE_FLAG_UNSATISFIABLE
        )

        # pylint: disable=line-too-long
        reason = """The following REQUIRED_USE flag constraints are unsatisfied:
    at-most-one-of ( kernel-4_19 kernel-5_4 kernel-5_10 kernel-5_15 kernel-upstream )

  The above constraints are a subset of the following complete expression:
    at-most-one-of ( kernel-4_19 kernel-5_4 kernel-5_10 kernel-5_15 kernel-upstream ) cfi? ( thinlto ) cfi_diag? ( cfi ) cfi_recover? ( cfi_diag )"""

        self.assertListEqual(
            result,
            [
                portage_util.PortageError(
                    kind=portage_util.ErrorKind.USE_FLAG_UNSATISFIABLE,
                    pkg="sys-kernel/linux-firmware-0.0.1-r701::chromiumos",
                    reason=reason,
                ),
            ],
        )

    def testDependencyUnsatisfiableError(self):
        """Detect DEPENDENCY_UNSATISFIABLE in output log."""
        result = portage_util.analyze_emerge_failure(
            AnalyzeEmergeFailureReasons.NO_EBUILD_ERROR
        )

        self.assertListEqual(
            result,
            [
                portage_util.PortageError(
                    kind=portage_util.ErrorKind.DEPENDENCY_UNSATISFIABLE,
                    pkg="dev-python/test-package",
                    reason="",
                ),
            ],
        )

    def testEbuildMissingForUseError(self):
        """Test detect EBUILD_MISSING_FOR_USE_FLAG from output log."""
        result = portage_util.analyze_emerge_failure(
            AnalyzeEmergeFailureReasons.EBUILD_MISSING_FOR_USE
        )

        self.assertListEqual(
            result,
            [
                portage_util.PortageError(
                    kind=portage_util.ErrorKind.EBUILD_MISSING_FOR_USE_FLAG,
                    pkg="chromeos-base/trunks",
                    reason="",
                ),
            ],
        )


class AnalyzeEmergeFailureReasons:
    """Class to hold all the failure data for AnalyzeEmergeFailureTest.

    This is just to make the test class and the file more readable and IDE
    friendly (the class is collapsible).
    """

    # pylint: disable=line-too-long
    NO_EBUILD_ERROR = """
emerge: there are no ebuilds to satisfy \"dev-python/test-package\" for /build/volteer/.
"""

    MULTIVERSION_ERROR = """
!!! Multiple package instances within a single package slot have been pulled
!!! into the dependency graph, resulting in a slot conflict:

chromeos-base/system_api:0 for /build/octopus/

  (chromeos-base/system_api-0.0.1-r5420:0/0.0.1-r5420::chromiumos, installed in '/build/octopus/') pulled in by
    chromeos-base/system_api:0/0.0.1-r5420= required by (chromeos-base/libiioservice_ipc-0.0.1-r490:0/0.0.1-r490::chromiumos, binary scheduled for merge to '/build/octopus/')
                            ^^^^^^^^^^^^^^^
    (and 38 more with the same problem)

  (chromeos-base/system_api-0.0.1-r5419:0/0.0.1-r5419::chromiumos, binary scheduled for merge to '/build/octopus/') pulled in by
    chromeos-base/system_api:0/0.0.1-r5419= required by (chromeos-base/patchpanel-client-0.0.1-r707:0/0.0.1-r707::chromiumos, binary scheduled for merge to '/build/octopus/')
                            ^^^^^^^^^^^^^^^
    (and 3 more with the same problem)

chromeos-base/patchpanel:0 for /build/octopus/

  (chromeos-base/patchpanel-0.0.2-r1054:0/0.0.2-r1054::chromiumos, ebuild scheduled for merge to '/build/octopus/') pulled in by
    (no parents that aren't satisfied by other packages in this slot)

  (chromeos-base/patchpanel-0.0.2-r1052:0/0.0.2-r1052::chromiumos, binary scheduled for merge to '/build/octopus/') pulled in by
    chromeos-base/patchpanel:0/0.0.2-r1052= required by (chromeos-base/dns-proxy-0.0.1-r699:0/0::chromiumos, binary scheduled for merge to '/build/octopus/')
                            ^^^^^^^^^^^^^^^
    (and 1 more with the same problem)

NOTE: Use the '--verbose-conflicts' option to display parents omitted above
"""

    MASKED_PACKAGE_ERROR = """
It may be possible to solve this problem by using package.mask to
prevent one of those packages from being selected. However, it is also
possible that conflicting dependencies exist such that they are
impossible to satisfy simultaneously.  If such a conflict exists in
the dependencies of two different packages, then those packages can
not be installed simultaneously. You may want to try a larger value of
the --backtrack option, such as --backtrack=30, in order to see if
that will solve this conflict automatically.

For more information, see MASKED PACKAGES section in the emerge man
page or refer to the Gentoo Handbook.


!!! The following binary packages have been ignored due to non matching USE:

    =chromeos-base/chromeos-firmware-null-0.0.3-r197 -cros_ec -has_chromeos_config_bsp_private # for /build/octopus/

NOTE: The --binpkg-respect-use=n option will prevent emerge
      from ignoring these binary packages if possible.
      Using --binpkg-respect-use=y will silence this warning.

!!! All ebuilds that could satisfy "media-sound/adhd:0/0.0.7-r3267=" for /build/octopus/ have been masked.
!!! One of the following masked packages is required to complete your request:
- media-sound/adhd-0.0.7-r3267::chromiumos (masked by: package.mask)

(dependency required by "chromeos-base/power_manager-0.0.2-r4956::chromiumos" [binary])
(dependency required by "chromeos-base/update_engine-0.0.3-r4786::chromiumos" [binary])
(dependency required by "virtual/target-chromium-os-1-r265::chromiumos" [installed])
(dependency required by "virtual/target-chrome-os-1.3-r45::chromeos" [installed])
(dependency required by "virtual/target-os-1.3-r3::chromeos" [ebuild])
(dependency required by "virtual/target-os" [argument])
For more information, see the MASKED PACKAGES section in the emerge
man page or refer to the Gentoo Handbook.
"""

    SIGTERM_ERROR = """
died with <Signals.SIGTERM: 15>; command: sudo --preserve-env 'USE=-cros-debug -lto' diagnostics
Merging board packages failed
"""

    USE_FLAG_UNSATISFIABLE = """
!!! The following binary packages have been ignored due to non matching USE:

    =chromeos-base/cros-camera-0.0.1-r1805 -arcvm -cheets # for /build/kukui64/

NOTE: The --binpkg-respect-use=n option will prevent emerge
      from ignoring these binary packages if possible.
      Using --binpkg-respect-use=y will silence this warning.

!!! The ebuild selected to satisfy "sys-kernel/linux-firmware" for /build/kukui64/ has unmet requirements.
- sys-kernel/linux-firmware-0.0.1-r701::chromiumos USE="kernel-4_19 kernel-5_10 -asan -cfi -cfi_diag -cfi_recover -coverage -cros_host -fuzzer -kernel-5_15 -kernel-5_4 -kernel-upstream -msan -thinlto -tsan -ubsan" LINUX_FIRMWARE="ath10k_qca6174a-3 cros-pd keyspan_usb qca6174a-3-bt rt2870 rtl8153 -adreno-630 -adreno-660 -adsp_apl -adsp_cnl -adsp_glk -adsp_kbl -adsp_skl -amd_ucode -amdgpu_carrizo -amdgpu_dimgrey_cavefish -amdgpu_gc_10_3_7 -amdgpu_gc_11_0_1 -amdgpu_gc_11_0_4 -amdgpu_green_sardine -amdgpu_navy_flounder -amdgpu_picasso -amdgpu_raven2 -amdgpu_renoir -amdgpu_sienna_cichlid -amdgpu_stoney -amdgpu_vega12 -amdgpu_yellow_carp -ath10k_qca6174a-5 -ath10k_wcn3990 -ath11k_wcn6750 -ath11k_wcn6855 -ath3k-all -ath3k-ar3011 -ath3k-ar3012 -ath9k_htc -bcm4354-bt -brcmfmac-all -brcmfmac4354-sdio -brcmfmac4356-pcie -brcmfmac4371-pcie -fw_sst -fw_sst2 -i915_adl -i915_bxt -i915_cnl -i915_glk -i915_jsl -i915_kbl -i915_skl -i915_tgl -ibt-hw -ibt_9260 -ibt_9560 -ibt_ax200 -ibt_ax201 -ibt_ax203 -ibt_ax211 -ice -ipu3_fw -iwlwifi-100 -iwlwifi-1000 -iwlwifi-105 -iwlwifi-135 -iwlwifi-2000 -iwlwifi-2030 -iwlwifi-3160 -iwlwifi-3945 -iwlwifi-4965 -iwlwifi-5000 -iwlwifi-5150 -iwlwifi-6000 -iwlwifi-6005 -iwlwifi-6030 -iwlwifi-6050 -iwlwifi-7260 -iwlwifi-7265 -iwlwifi-7265D -iwlwifi-9000 -iwlwifi-9260 -iwlwifi-QuZ -iwlwifi-all -iwlwifi-cc -iwlwifi-so -iwlwifi-so-a0-hr -marvell-mwlwifi -marvell-pcie8897 -marvell-pcie8997 -mt7921e -mt7921e-bt -mt7922 -mt7922-bt -mt8173-vpu -nvidia-xusb -qca-wcn3990-bt -qca-wcn3991-bt -qca-wcn6750-bt -qca-wcn685x-bt -qca6174a-5-bt -rockchip-dptx -rtl8107e-1 -rtl8107e-2 -rtl8125a-3 -rtl8125b-1 -rtl8125b-2 -rtl8168fp-3 -rtl8168g-1 -rtl8168g-2 -rtl8168h-1 -rtl8168h-2 -rtl_bt-8822ce-uart -rtl_bt-8822ce-usb -rtl_bt-8852ae-usb -rtl_bt-8852ce-usb -rtw8822c -rtw8852a -rtw8852c -venus-52 -venus-54 -venus-vpu-2" VIDEO_CARDS="-amdgpu (-radeon)"

  The following REQUIRED_USE flag constraints are unsatisfied:
    at-most-one-of ( kernel-4_19 kernel-5_4 kernel-5_10 kernel-5_15 kernel-upstream )

  The above constraints are a subset of the following complete expression:
    at-most-one-of ( kernel-4_19 kernel-5_4 kernel-5_10 kernel-5_15 kernel-upstream ) cfi? ( thinlto ) cfi_diag? ( cfi ) cfi_recover? ( cfi_diag )

(dependency required by "virtual/target-chromium-os-1-r265::chromiumos" [ebuild])
(dependency required by "virtual/target-chrome-os-1.3-r45::chromeos" [ebuild])
(dependency required by "virtual/target-os-1.3-r3::chromeos" [ebuild])
(dependency required by "virtual/target-os" [argument])
"""

    EBUILD_MISSING_FOR_USE = """
!!! The following binary packages have been ignored due to non matching USE:

    =chromeos-base/trunks-0.0.1-r3602 -cr50_onboard cros-debug tpm2_simulator # for /build/brya-cbx/
    =chromeos-base/trunks-0.0.1-r3602 -cr50_onboard cros-debug tpm2_simulator # for /build/brya-cbx/

NOTE: The --binpkg-respect-use=n option will prevent emerge
      from ignoring these binary packages if possible.
      Using --binpkg-respect-use=y will silence this warning.
violated_atom.use not set:
chromeos-base/trunks:=
violated_atom.use not set:
chromeos-base/trunks:=
violated_atom.use not set:
chromeos-base/trunks:=
violated_atom.use not set:
chromeos-base/trunks:=
violated_atom.use not set:
chromeos-base/trunks:=
violated_atom.use not set:
chromeos-base/trunks:=
violated_atom.use not set:
chromeos-base/trunks:=

emerge: there are no ebuilds built with USE flags to satisfy "chromeos-base/trunks:=[test?]" for /build/brya-cbx/.
!!! One of the following packages is required to complete your request:
- chromeos-base/trunks-0.0.1-r3602::chromiumos (Change USE: +test)
(dependency required by "chromeos-base/libhwsec-0.0.1-r869::chromiumos[-test]" [ebuild])
(dependency required by "libhwsec" [argument])
"""
