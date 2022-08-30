# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for toolchain_util."""

import base64
import builtins
import collections
import datetime
import fnmatch
import glob
import io
import json
import os
from pathlib import Path
import shutil
import time
from unittest import mock

from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import gob_util
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import toolchain_util
from chromite.lib.parser import package_info


# pylint: disable=protected-access

_input_artifact = collections.namedtuple('_input_artifact',
                                         ['name', 'gs_locations'])


class ProfilesNameHelperTest(cros_test_lib.MockTempDirTestCase):
  """Test the helper functions related to naming."""

  # pylint: disable=protected-access
  def testParseBenchmarkProfileName(self):
    """Test top-level function _ParseBenchmarkProfileName."""
    # Test parse failure
    profile_name_to_fail = 'this_is_an_invalid_name'
    with self.assertRaises(toolchain_util.ProfilesNameHelperError) as context:
      toolchain_util._ParseBenchmarkProfileName(profile_name_to_fail)
    self.assertIn('Unparseable benchmark profile name:', str(context.exception))

    # Test parse success
    profile_name = 'chromeos-chrome-amd64-77.0.3849.0_rc-r1.afdo'
    result = toolchain_util._ParseBenchmarkProfileName(profile_name)
    self.assertEqual(
        result,
        toolchain_util.BenchmarkProfileVersion(
            major=77, minor=0, build=3849, patch=0, revision=1,
            is_merged=False))

    # Test Arm parsing.
    profile_name = 'chromeos-chrome-arm-77.0.3849.0_rc-r1.afdo'
    result = toolchain_util._ParseBenchmarkProfileName(profile_name)
    self.assertEqual(
        result,
        toolchain_util.BenchmarkProfileVersion(
            major=77, minor=0, build=3849, patch=0, revision=1,
            is_merged=False))


  def testParseCWPProfileName(self):
    """Test top-level function _ParseCWPProfileName."""
    # Test parse failure
    profile_name_to_fail = 'this_is_an_invalid_name'
    with self.assertRaises(toolchain_util.ProfilesNameHelperError) as context:
      toolchain_util._ParseCWPProfileName(profile_name_to_fail)
    self.assertIn('Unparseable CWP profile name:', str(context.exception))

    # Test parse success
    profile_name = 'R77-3809.38-1562580965.afdo.xz'
    result = toolchain_util._ParseCWPProfileName(profile_name)
    self.assertEqual(
        result,
        toolchain_util.CWPProfileVersion(
            major=77, build=3809, patch=38, clock=1562580965))

  def testParseMergedProfileName(self):
    """Test top-level function _ParseMergedProfileName."""
    # Test parse failure
    profile_name_to_fail = 'this_is_an_invalid_name'
    with self.assertRaises(toolchain_util.ProfilesNameHelperError) as context:
      toolchain_util._ParseMergedProfileName(profile_name_to_fail)
    self.assertIn('Unparseable merged AFDO name:', str(context.exception))

    # Test parse orderfile success
    orderfile_name = ('chromeos-chrome-orderfile-field-77-3809.38-1562580965'
                      '-benchmark-77.0.3849.0-r1.orderfile.xz')
    result = toolchain_util._ParseMergedProfileName(orderfile_name)
    self.assertEqual(
        result, (toolchain_util.BenchmarkProfileVersion(
            major=77, minor=0, build=3849, patch=0, revision=1,
            is_merged=False),
                 toolchain_util.CWPProfileVersion(
                     major=77, build=3809, patch=38, clock=1562580965)))

    # Test parse release AFDO success
    afdo_name = ('chromeos-chrome-amd64-atom-77-3809.38-1562580965'
                 '-benchmark-77.0.3849.0-r1-redacted.afdo.xz')
    result = toolchain_util._ParseMergedProfileName(afdo_name)
    self.assertEqual(
        result, (toolchain_util.BenchmarkProfileVersion(
            major=77, minor=0, build=3849, patch=0, revision=1,
            is_merged=False),
                 toolchain_util.CWPProfileVersion(
                     major=77, build=3809, patch=38, clock=1562580965)))
    # Test parse release Arm AFDO success
    afdo_name = ('chromeos-chrome-arm-none-77-3809.38-1562580965'
                 '-benchmark-77.0.3849.0-r1-redacted.afdo.xz')
    result = toolchain_util._ParseMergedProfileName(afdo_name)
    self.assertEqual(
        result, (toolchain_util.BenchmarkProfileVersion(
            major=77, minor=0, build=3849, patch=0, revision=1,
            is_merged=False),
                 toolchain_util.CWPProfileVersion(
                     major=77, build=3809, patch=38, clock=1562580965)))


  def testGetOrderfileName(self):
    """Test method _GetOrderfileName and related methods."""
    profile_name = ('chromeos-chrome-amd64-atom-77-3809.38-1562580965-'
                    'benchmark-77.0.3849.0-r1-redacted.afdo.xz')
    self.PatchObject(
        toolchain_util,
        '_GetArtifactVersionInChromium',
        return_value=profile_name)
    result = toolchain_util._GetOrderfileName('/path/to/chrome_root')
    cwp_name = 'field-77-3809.38-1562580965'
    benchmark_name = 'benchmark-77.0.3849.0-r1'
    self.assertEqual(
        result, 'chromeos-chrome-orderfile-%s-%s' % (cwp_name, benchmark_name))

  def testCompressAFDOFiles(self):
    """Test _CompressAFDOFiles()."""
    input_dir = '/path/to/inputs'
    output_dir = '/another/path/to/outputs'
    targets = ['input1', '/path/to/inputs/input2']
    suffix = '.xz'
    self.PatchObject(cros_build_lib, 'CompressFile')
    # Should raise exception because the input doesn't exist
    with self.assertRaises(RuntimeError) as context:
      toolchain_util._CompressAFDOFiles(targets, input_dir, output_dir, suffix)
    self.assertEqual(
        str(context.exception), 'file %s to compress does not exist' %
        os.path.join(input_dir, targets[0]))
    # Should pass
    self.PatchObject(os.path, 'exists', return_value=True)
    # Return ~1MB profile size.
    self.PatchObject(os.path, 'getsize', return_value=100000)
    toolchain_util._CompressAFDOFiles(targets, input_dir, output_dir, suffix)
    compressed_names = [os.path.basename(x) for x in targets]
    inputs = [os.path.join(input_dir, n) for n in compressed_names]
    outputs = [os.path.join(output_dir, n + suffix) for n in compressed_names]
    calls = [mock.call(n, o) for n, o in zip(inputs, outputs)]
    cros_build_lib.CompressFile.assert_has_calls(calls)

  def testGetProfileAge(self):
    """Test top-level function _GetProfileAge()."""
    # Test unsupported artifact_type
    current_day_profile = 'R0-0.0-%d' % int(time.time())
    with self.assertRaises(ValueError) as context:
      toolchain_util._GetProfileAge(current_day_profile, 'unsupported_type')
    self.assertEqual('Only kernel afdo is supported to check profile age.',
                     str(context.exception))

    # Test using profile of the current day.
    ret = toolchain_util._GetProfileAge(current_day_profile, 'kernel_afdo')
    self.assertEqual(0, ret)

    # Test using profile from the last day.
    last_day_profile = 'R0-0.0-%d' % int(time.time() - 86400)
    ret = toolchain_util._GetProfileAge(last_day_profile, 'kernel_afdo')
    self.assertEqual(1, ret)


class PrepareBundleTest(cros_test_lib.RunCommandTempDirTestCase):
  """Setup code common to Prepare/Bundle class methods."""

  def setUp(self):
    self.board = 'chell'
    self.chroot = chroot_lib.Chroot(path=self.tempdir, chrome_root=self.tempdir)
    self.sysroot = '/build/%s' % self.board
    self.chrome_package = 'chromeos-chrome'
    self.kernel_package = 'chromeos-kernel-3_18'
    self.chrome_PV = 'chromeos-base/chromeos-chrome-78.0.3893.0_rc-r1'
    self.chrome_ebuild = os.path.realpath(
        os.path.join(
            os.path.dirname(__file__), '..', '..',
            'src', 'third_party', 'chromiumos-overlay',
            os.path.dirname(self.chrome_PV), 'chromeos-chrome',
            '%s.ebuild' % os.path.basename(self.chrome_PV)))
    self.chrome_pkg = package_info.parse(self.chrome_PV)
    self.glob = self.PatchObject(
        glob, 'glob', return_value=[self.chrome_ebuild])
    self.rc.AddCmdResult(partial_mock.In('rm'), returncode=0)
    self.obj = toolchain_util._CommonPrepareBundle(
        'None', chroot=self.chroot, sysroot_path=self.sysroot)
    self.gs_context = self.PatchObject(self.obj, '_gs_context')
    self.gsc_list = self.PatchObject(self.gs_context, 'List', return_value=[])
    self.data = b'data'
    self.arch = 'atom'
    self.fetch = self.PatchObject(
        gob_util, 'FetchUrl', return_value=base64.encodebytes(self.data))


class CommonPrepareBundleTest(PrepareBundleTest):
  """Test common Prepare/Bundle class methods."""

  def testGetEbuildInfo(self):
    """Verify that EbuildInfo is correctly returned."""
    self.glob.return_value = [
        'chromeos-chrome-96.0.4657.0_rc-r2.ebuild'
    ]
    ret = self.obj._GetEbuildInfo('chromeos-chrome')
    self.assertEqual(ret.CPV.vr, '96.0.4657.0_rc-r2')
    self.assertEqual(ret.CPV.version, '96.0.4657.0_rc')
    self.assertEqual(ret.CPV.revision, 2)
    self.assertTrue(ret.CPV.with_version('96.0.4657.0_rc'))
    self.assertEqual(ret.CPV.category, 'chromeos-base')
    self.assertEqual(ret.CPV.package, 'chromeos-chrome')
    self.glob.assert_called_once()

  def testGetEbuildInfoWithoutRevision(self):
    """Verify that EbuildInfo is correctly returned."""
    self.glob.return_value = [
        'chromeos-chrome-96.0.4657.0_rc.ebuild'
    ]
    ret = self.obj._GetEbuildInfo('chromeos-chrome')
    self.assertEqual(ret.CPV.vr, '96.0.4657.0_rc')
    self.assertEqual(ret.CPV.version, '96.0.4657.0_rc')
    self.assertEqual(ret.CPV.revision, 0)

  def testGetEbuildInfoWithMultipleChromes(self):
    self.glob.return_value = [
        'chromeos-chrome-78.0.3893.0.ebuild',
        'chromeos-chrome-78.0.3893.0_rc-r1.ebuild',
        'chromeos-chrome-78.0.3893.100_rc-r1.ebuild',
        'chromeos-chrome-78.0.3893.10_rc-r1.ebuild'
    ]
    ret = self.obj._GetEbuildInfo('chromeos-chrome')
    self.assertEqual(ret.CPV.vr, '78.0.3893.100_rc-r1')
    self.assertEqual(ret.CPV.version, '78.0.3893.100_rc')
    self.assertEqual(ret.CPV.revision, 1)

  def test_GetArtifactVersionInGob(self):
    """Test that we look in the right place in GoB."""
    self.assertRaises(ValueError, self.obj._GetArtifactVersionInGob, 'badarch')

    self.assertEqual(
        self.data.decode('utf-8'), self.obj._GetArtifactVersionInGob(self.arch))
    self.fetch.assert_called_once_with(
        constants.EXTERNAL_GOB_HOST,
        'chromium/src/+/refs/tags/%s/chromeos/profiles/%s.afdo.newest.txt'
        '?format=text' %
        (self.chrome_pkg.version.split('_')[0], self.arch))

    self.fetch.reset_mock()
    self.fetch.return_value = ''
    self.assertRaises(RuntimeError, self.obj._GetArtifactVersionInGob,
                      self.arch)
    self.fetch.assert_called_once()

  def test_GetOrderfileName(self):
    """Test that GetOrderfileName finds the right answer."""
    vers = self.PatchObject(
        self.obj,
        '_GetArtifactVersionInGob',
        return_value=('chromeos-chrome-amd64-atom-78-1111.0-'
                      '157000000-benchmark-78.0.3893.0-r1-redacted.afdo.xz'))
    self.assertEqual(
        'chromeos-chrome-orderfile-field-78-1111.0-'
        '157000000-benchmark-78.0.3893.0-r1.orderfile',
        self.obj._GetOrderfileName())
    vers.assert_called_once()


class PrepBundLatestAFDOArtifactTest(PrepareBundleTest):
  """Test related function to compare freshness of AFDO artifacts."""

  def setUp(self):
    self.board = 'board'
    self.gs_url = 'gs://path/to/any_gs_url'
    self.current_branch = '78'
    self.current_arch = 'atom'
    self.MockListResult = collections.namedtuple('MockListResult',
                                                 ('url', 'creation_time'))
    files_in_gs_bucket = [
        # Benchmark profiles
        ('chromeos-chrome-amd64-78.0.3893.0_rc-r1.afdo.bz2', 2.0),
        ('chromeos-chrome-amd64-78.0.3896.0_rc-r1.afdo.bz2', 1.0),  # Latest
        ('chromeos-chrome-amd64-78.0.3897.0_rc-r1-merged.afdo.bz2', 3.0),
        # CWP profiles
        ('R78-3869.38-1562580965.afdo.xz', 2.1),
        ('R78-3866.0-1570000000.afdo.xz', 1.1),  # Latest
        ('R77-3811.0-1580000000.afdo.xz', 3.1),
        # Kernel profiles
        ('R76-3869.38-1562580965.gcov.xz', 1.3),
        ('R76-3866.0-1570000000.gcov.xz', 2.3),  # Latest
        # Orderfiles
        ('chromeos-chrome-orderfile-field-78-3877.0-1567418235-'
         'benchmark-78.0.3893.0-r1.orderfile.xz', 1.2),  # Latest
        ('chromeos-chrome-orderfile-field-78-3877.0-1567418235-'
         'benchmark-78.0.3850.0-r1.orderfile.xz', 2.2),
    ]

    self.gs_list = [
        self.MockListResult(url=os.path.join(self.gs_url, x), creation_time=y)
        for x, y in files_in_gs_bucket
    ]
    self.gsc_list.return_value = self.gs_list

  def testValidBenchmarkProfileVersion(self):
    """Test that it returns None for unparsable profile name."""
    prof = 'unparsable-file.data'
    ver_none = self.obj._ValidBenchmarkProfileVersion(prof)
    self.assertIsNone(ver_none)

  def testFindLatestAFDOArtifactPassWithBenchmarkAFDO(self):
    """Test _FindLatestAFDOArtifact returns latest benchmark AFDO."""
    latest_afdo = self.obj._FindLatestAFDOArtifact(
        [self.gs_url], self.obj._ValidBenchmarkProfileVersion)
    self.assertEqual(
        latest_afdo,
        os.path.join(self.gs_url,
                     'chromeos-chrome-amd64-78.0.3896.0_rc-r1.afdo.bz2'))

  def testFindLatestAFDOArtifactPassWithOrderfile(self):
    """Test _FindLatestAFDOArtifact return latest orderfile."""
    latest_orderfile = self.obj._FindLatestAFDOArtifact(
        [self.gs_url], self.obj._ValidOrderfileVersion)
    self.assertEqual(
        latest_orderfile,
        os.path.join(
            self.gs_url, 'chromeos-chrome-orderfile-field-78-3877.0-1567418235-'
            'benchmark-78.0.3893.0-r1.orderfile.xz'))

  def testFindLatestAfdoArtifactOnPriorBranch(self):
    """Test that we find a file from prior branch when we have none."""
    self.obj._ebuild_info['chromeos-chrome'] = toolchain_util._EbuildInfo(
        path='path',
        CPV=package_info.parse(
            'chromeos-base/chromeos-chrome-79.0.3900.0_rc-r1'))
    latest_orderfile = self.obj._FindLatestAFDOArtifact(
        [self.gs_url], self.obj._ValidOrderfileVersion)
    self.assertEqual(
        latest_orderfile,
        os.path.join(
            self.gs_url, 'chromeos-chrome-orderfile-field-78-3877.0-1567418235-'
            'benchmark-78.0.3893.0-r1.orderfile.xz'))

  def testFindLatestAFDOArtifactFailToFindAnyFiles(self):
    """Test function fails when no files on current branch."""
    self.obj._ebuild_info['chromeos-chrome'] = toolchain_util._EbuildInfo(
        path='path',
        CPV=package_info.parse(
            'chromeos-base/chromeos-chrome-80.0.3950.0_rc-r1'))
    self.gsc_list.side_effect = gs.GSNoSuchKey('No files')
    with self.assertRaises(RuntimeError) as context:
      self.obj._FindLatestAFDOArtifact([self.gs_url],
                                       self.obj._ValidOrderfileVersion)
    self.assertEqual('No files for branch 80 found in %s' % self.gs_url,
                     str(context.exception))

  def testFindLatestAFDOArtifactsFindMaxFromInvalidFiles(self):
    """Test function fails when searching max from list of invalid files."""
    mock_gs_list = [
        self.MockListResult(
            url=os.path.join(self.gs_url, 'Invalid-name-but-end-in-78.afdo'),
            creation_time=1.0)
    ]
    self.gsc_list.return_value = mock_gs_list
    with self.assertRaises(RuntimeError) as context:
      self.obj._FindLatestAFDOArtifact([self.gs_url],
                                       self.obj._ValidBenchmarkProfileVersion)
    self.assertIn('No valid latest artifact was found', str(context.exception))


class PrepareForBuildHandlerTest(PrepareBundleTest):
  """Test PrepareForBuildHandler specific methods."""

  def setUp(self):
    self.artifact_type = 'Unspecified'
    self.input_artifacts = {}
    self.kernel_version = '5_4'
    self.profile_info = {
        'kernel_version': self.kernel_version.replace('_', '.'),
    }
    self.gsc_exists = None
    self.gsc_ls = None
    self.patch_ebuild = mock.MagicMock()
    self.orderfile_name = (
        'chromeos-chrome-orderfile-field-78-3877.0-1567418235-'
        'benchmark-78.0.3893.0-r1.orderfile')
    self.verified_afdo_name = (
        'chromeos-chrome-amd64-atom-78-3877.0-1658747184-'
        'benchmark-78.0.3839.0-r1-redacted.afdo')
    self.afdo_name = 'chromeos-chrome-amd64-78.0.3893.0-r1.afdo'
    self.PatchObject(
        toolchain_util._CommonPrepareBundle,
        '_GetOrderfileName',
        return_value=self.orderfile_name)
    self.PatchObject(
        toolchain_util._CommonPrepareBundle,
        '_FindLatestOrderfileArtifact',
        return_value=self.orderfile_name + toolchain_util.XZ_COMPRESSION_SUFFIX)

  def SetUpPrepare(self, artifact_type, input_artifacts, mock_patch=True,
                   profile_info_extra=None):
    """Set up to test _Prepare${artifactType}."""
    self.artifact_type = artifact_type
    self.input_artifacts = input_artifacts
    if profile_info_extra:
      self.profile_info.update(profile_info_extra)
    self.obj = toolchain_util.PrepareForBuildHandler(self.artifact_type,
                                                     self.chroot, self.sysroot,
                                                     self.board,
                                                     self.input_artifacts,
                                                     self.profile_info)
    self.obj._gs_context = self.gs_context
    self.PatchObject(self.obj, '_GetOrderfileName', return_value='orderfile')
    self.gsc_exists = self.PatchObject(
        self.gs_context, 'Exists', return_value=True)
    self.gsc_ls = self.PatchObject(
        self.gs_context, 'LS', return_value=['gs://path'])
    if mock_patch:
      self.patch_ebuild = self.PatchObject(
          toolchain_util._CommonPrepareBundle, '_PatchEbuild')

  def testPrepareUnverifiedChromeLlvmOrderfileExists(self):
    """Test that PrepareUnverfiedChromeLlvmOrderfile works when POINTLESS."""
    self.SetUpPrepare(
        'UnverifiedChromeLlvmOrderfile',
        {'UnverifiedChromeLlvmOrderfile': ['gs://publish/location']})
    self.assertEqual(toolchain_util.PrepareForBuildReturn.POINTLESS,
                     self.obj.Prepare())
    self.gs_context.Exists.assert_called_once_with(
        'gs://publish/location/orderfile.xz')

  def testPrepareUnverifiedChromeLlvmOrderfileMissing(self):
    """Test that PrepareUnverfiedChromeLlvmOrderfile works when NEEDED."""
    self.SetUpPrepare(
        'UnverifiedChromeLlvmOrderfile',
        {'UnverifiedChromeLlvmOrderfile': ['gs://publish/location']})
    self.gsc_exists.return_value = False
    self.assertEqual(toolchain_util.PrepareForBuildReturn.NEEDED,
                     self.obj.Prepare())
    self.gs_context.Exists.assert_called_once_with(
        'gs://publish/location/orderfile.xz')

  def testPrepareVerifiedChromeLlvmOrderfileExists(self):
    """Test that PrepareVerfiedChromeLlvmOrderfile works when POINTLESS."""
    self.SetUpPrepare(
        'VerifiedChromeLlvmOrderfile', {
            'UnverifiedChromeLlvmOrderfile':
                ['gs://path/to/unvetted', 'gs://other/path/to/unvetted']
        })
    self.assertEqual(toolchain_util.PrepareForBuildReturn.POINTLESS,
                     self.obj.Prepare())
    self.gs_context.Exists.assert_called_once_with('gs://path/to/vetted/%s.xz' %
                                                   self.orderfile_name)
    # The ebuild is still updated.
    self.patch_ebuild.assert_called_once()

  def testPrepareVerifiedChromeLlvmOrderfileMissing(self):
    """Test that PrepareVerfiedChromeLlvmOrderfile works when NEEDED."""
    self.SetUpPrepare(
        'VerifiedChromeLlvmOrderfile', {
            'UnverifiedChromeLlvmOrderfile':
                ['gs://path/to/unvetted', 'gs://other/path/to/unvetted']
        })
    self.gsc_exists.return_value = False
    self.assertEqual(toolchain_util.PrepareForBuildReturn.NEEDED,
                     self.obj.Prepare())
    self.gs_context.Exists.assert_called_once_with('gs://path/to/vetted/%s.xz' %
                                                   self.orderfile_name)
    self.patch_ebuild.assert_called_once()

  def setupUnverifiedChromeBenchmarkAfdoFileInputProperties(
      self, profile_info_extra=None):
    self.SetUpPrepare(
        'UnverifiedChromeBenchmarkAfdoFile',
        {
            'UnverifiedChromeBenchmarkPerfFile': ['gs://path/to/perfdata'],
            'UnverifiedChromeBenchmarkAfdoFile': ['gs://path/to/unvetted'],
            'ChromeDebugBinary': ['gs://image-archive/path'],
        },
        profile_info_extra=profile_info_extra)

  def testPrepareUnverifiedChromeBenchmarkAfdoFileExists(self):
    """Normal flow, build is needed, all artifacts are present."""
    self.setupUnverifiedChromeBenchmarkAfdoFileInputProperties()
    # Published artifact is missing, debug binary is present, perf.data is
    # present.
    self.gsc_exists.return_value = False
    self.gsc_ls.side_effect = (['gs://image-archive/path/to/debug'],
                               ['gs://image-archive/path/to/perf'])
    self.assertEqual(toolchain_util.PrepareForBuildReturn.NEEDED,
                     self.obj.Prepare())
    expected_exists = [
        mock.call('gs://path/to/unvetted/'
                  'chromeos-chrome-amd64-78.0.3893.0_rc-r1.afdo.bz2'),
    ]
    expected_ls = [
        mock.call('gs://image-archive/path/'
                  'chromeos-chrome-amd64-*.debug.bz2'),
        mock.call('gs://path/to/perfdata/'
                  'chromeos-chrome-amd64-78.0.3893.0.perf.data.bz2'),
    ]
    self.assertEqual(expected_exists, self.gs_context.Exists.call_args_list)
    self.assertEqual(expected_ls, self.gs_context.LS.call_args_list)
    # There is no need to patch the ebuild.
    self.patch_ebuild.assert_not_called()

  def testPrepareUnverifiedChromeBenchmarkArmAfdoFile(self):
    """Normal flow with Arm, build is needed, all artifacts are present."""
    profile_info_extra = {'chrome_cwp_profile': 'arm'}
    self.setupUnverifiedChromeBenchmarkAfdoFileInputProperties(
        profile_info_extra)
    # Published artifact is missing, debug binary is present, perf.data is
    # present.
    self.gsc_exists.return_value = False
    self.gsc_ls.side_effect = (['gs://image-archive/path/to/debug'],
                               ['gs://image-archive/path/to/perf'])
    self.assertEqual(toolchain_util.PrepareForBuildReturn.NEEDED,
                     self.obj.Prepare())
    # Expect arm profiles.
    expected_exists = [
        mock.call('gs://path/to/unvetted/'
                  'chromeos-chrome-arm-78.0.3893.0_rc-r1.afdo.bz2'),
    ]
    expected_ls = [
        mock.call('gs://image-archive/path/'
                  'chromeos-chrome-arm-*.debug.bz2'),
        mock.call('gs://path/to/perfdata/'
                  'chromeos-chrome-arm-78.0.3893.0.perf.data.bz2'),
    ]
    self.assertEqual(expected_exists, self.gs_context.Exists.call_args_list)
    self.assertEqual(expected_ls, self.gs_context.LS.call_args_list)
    # There is no need to patch the ebuild.
    self.patch_ebuild.assert_not_called()

  def testPrepareUnverifiedChromeBenchmarkAfdoFileMissingDebug(self):
    """Test raised exception when chrome.debug file is missing."""
    self.setupUnverifiedChromeBenchmarkAfdoFileInputProperties()
    # Published artifact is missing, debug binary is missing.
    self.gsc_exists.return_value = False
    self.gsc_ls.return_value = []
    with self.assertRaisesRegex(
        toolchain_util.PrepareForBuildHandlerError,
        r'Could not find an artifact matching the pattern '
        r'"chromeos-chrome-amd64-\*.debug.bz2" in '
        r"\['gs://image-archive/path'\]."):
      self.obj.Prepare()

  def testPrepareUnverifiedChromeBenchmarkAfdoFileMissingPerf(self):
    """Test raised exception when perf.data file is missing."""
    self.setupUnverifiedChromeBenchmarkAfdoFileInputProperties()
    # Published artifact is missing, debug binary is present,
    # perf.data is missing.
    self.gsc_exists.return_value = False
    self.gsc_ls.side_effect = (['gs://image-archive/path/to/debug'],
                               [])
    with self.assertRaisesRegex(
        toolchain_util.PrepareForBuildHandlerError,
        r'Could not find "chromeos-chrome-amd64-78.0.3893.0.perf.data.bz2" '
        r"in \['gs://path/to/perfdata'\]."):
      self.obj.Prepare()

  def testPrepareUnverifiedChromeBenchmarkAfdoFileMultArtifacts(self):
    """Test raised exception when there are multiple artifacts of one type."""
    self.setupUnverifiedChromeBenchmarkAfdoFileInputProperties()
    # Published artifact is missing, multiple debug binary artifacts.
    self.gsc_exists.return_value = False
    self.gsc_ls.return_value = ['gs://image-archive/path/to/debug1',
                                'gs://image-archive/path/to/debug2']
    with self.assertRaisesRegex(
        toolchain_util.PrepareForBuildHandlerError,
        r"Found \['gs://image-archive/path/to/debug1', "
        r"'gs://image-archive/path/to/debug2'\] artifacts at "
        r'gs://image-archive/path. Expected ONE file.'):
      self.obj.Prepare()

  def testCleanupArtifactDirectory(self):
    mock_rmdir = self.PatchObject(osutils, 'RmDir')
    mock_isdir = self.PatchObject(os.path, 'exists')
    for test_dir in [
        '/tmp/fatal_clang_warnings', '/tmp/clang_crash_diagnostics'
    ]:
      mock_rmdir.reset_mock()
      # When the dirs don't exist, we shouldn't try to remove them
      mock_isdir.return_value = False
      self.obj._CleanupArtifactDirectory(test_dir)
      mock_rmdir.assert_not_called()

      # When the dirs exist, we should remove all of them
      mock_isdir.return_value = True
      self.obj._CleanupArtifactDirectory(test_dir)
      mock_rmdir.assert_has_calls([
          mock.call(self.chroot.full_path(test_dir), sudo=True),
          mock.call(
              self.chroot.full_path(os.path.join(self.sysroot, test_dir[1:])),
              sudo=True)
      ])

    # A non-absolute path will trigger assertion
    with self.assertRaises(Exception) as context:
      self.obj._CleanupArtifactDirectory('non/absolute/path')
    self.assertIn('needs to be an absolute path', str(context.exception))

  def callPrepareVerifiedKernelCwpAfdoFile(self, ebuild_list_of_str):
    cwp_loc = 'gs://path/to/cwp/kernel/5.4'
    self.SetUpPrepare(
        'VerifiedKernelCwpAfdoFile', {
            'UnverifiedKernelCwpAfdoFile': [cwp_loc],
            'VerifiedKernelCwpAfdoFile': [cwp_loc],
        }, mock_patch=False)
    cwp_old_ver = 'R99-14469.8-1644229953'
    cwp_new_ver = 'R100-14496.0-1644834841'
    kernel_cwp = os.path.join(cwp_loc, cwp_new_ver)
    ebuild_info = toolchain_util._EbuildInfo(
        path='/path/to/kernel-9999.ebuild', CPV=mock.MagicMock())

    self.PatchObject(os, 'rename')
    self.PatchObject(cros_build_lib, 'run')
    self.PatchObject(toolchain_util, '_GetProfileAge', return_value=0)
    self.PatchObject(self.obj, '_GetEbuildInfo', return_value=ebuild_info)
    self.PatchObject(self.obj, '_FindLatestAFDOArtifact',
                     return_value=kernel_cwp)
    # The artifact is missing, build is needed.
    self.gsc_exists.return_value = False
    ebuild_old_str = ''.join(ebuild_list_of_str).format(
        kernel_cwp_loc='', kernel_cwp_ver=cwp_old_ver)
    # We are going to check how the mock_object was called.
    mock_open = self.PatchObject(
        builtins, 'open', mock.mock_open(read_data=(ebuild_old_str)))

    self.obj.Prepare()

    # Check the expected patched lines.
    for ebuild_line in ebuild_list_of_str:
      resolved_line = ebuild_line.format(kernel_cwp_loc=cwp_loc,
                                         kernel_cwp_ver=cwp_new_ver)
      self.assertIn(mock.call().write(resolved_line), mock_open.mock_calls)

  def testPrepareVerifiedKernelCwpAfdoFileOldEbuild(self):
    """Test PrepareVerifiedKernelCwpAfdoFile and patch old ebuild."""
    ebuild_data = ('# some comment\n',
                   'AFDO_LOCATION="{kernel_cwp_loc}"\n',
                   'AFDO_PROFILE_VERSION="{kernel_cwp_ver}"')
    self.callPrepareVerifiedKernelCwpAfdoFile(ebuild_data)

  def testPrepareVerifiedKernelCwpAfdoFileNewEbuild(self):
    """Test PrepareVerifiedKernelCwpAfdoFile and patch new ebuild."""
    ebuild_data = ('# some comment\n',
                   'export AFDO_LOCATION="{kernel_cwp_loc}"\n',
                   'export AFDO_PROFILE_VERSION="{kernel_cwp_ver}"')
    self.callPrepareVerifiedKernelCwpAfdoFile(ebuild_data)

  def setupPrepareVerifiedReleaseAfdoFileMocks(self):
    self.PatchObject(
        self.obj, '_FindLatestAFDOArtifact',
        side_effect=(
            os.path.join(toolchain_util.BENCHMARK_AFDO_GS_URL,
                         'chromeos-chrome-amd64-78.0.3839.0_rc-r1.afdo.bz2'),
            os.path.join(toolchain_util.CWP_AFDO_GS_URL,
                         'R78-3877.0-1658747184.afdo.xz')))
    self.PatchObject(self.obj.chroot, 'tempdir', return_value=self.tempdir)
    self.PatchObject(self.obj, '_MergeAFDOProfiles')
    self.PatchObject(self.obj, '_ProcessAFDOProfile')
    self.PatchObject(os, 'rename')

  def testPrepareVerifiedReleaseAfdoFileExists(self):
    """Test that _PrepareVerifiedReleaseAfdoFile works when POINTLESS."""
    profile_info_extra = {'chrome_cwp_profile': 'atom'}
    self.SetUpPrepare(
        'VerifiedReleaseAfdoFile',
        {
            'VerifiedReleaseAfdoFile': ['gs://path/to/vetted']
        },
        profile_info_extra=profile_info_extra)
    self.setupPrepareVerifiedReleaseAfdoFileMocks()
    self.assertEqual(toolchain_util.PrepareForBuildReturn.POINTLESS,
                     self.obj.Prepare())
    self.gs_context.Exists.assert_called_once_with(
        f'gs://path/to/vetted/{self.verified_afdo_name}.xz')
    # The ebuild is still updated.
    self.patch_ebuild.assert_called_once()

  def setupPrepareVerifiedReleaseAfdoFileInputProperties(
      self, profile_info_extra=None):
    self.SetUpPrepare(
        'VerifiedReleaseAfdoFile',
        {
            'UnverifiedChromeBenchmarkAfdoFile': [
                toolchain_util.BENCHMARK_AFDO_GS_URL
            ],
            'UnverifiedChromeCwpAfdoFile': [
                toolchain_util.CWP_AFDO_GS_URL
            ],
        },
        profile_info_extra=profile_info_extra)

  def testPrepareVerifiedReleaseAfdoFile(self):
    """Normal flow, build is needed, all artifacts are present."""
    profile_info_extra = {'chrome_cwp_profile': 'atom'}
    self.setupPrepareVerifiedReleaseAfdoFileInputProperties(profile_info_extra)
    self.setupPrepareVerifiedReleaseAfdoFileMocks()
    # Published artifact is missing, debug binary is present, perf.data is
    # present.
    self.gsc_exists.return_value = False
    self.assertEqual(toolchain_util.PrepareForBuildReturn.NEEDED,
                     self.obj.Prepare())
    expected_exists = [
        mock.call(os.path.join(
            toolchain_util.RELEASE_AFDO_GS_URL_VETTED,
            ('chromeos-chrome-amd64-atom-78-3877.0-1658747184-'
             'benchmark-78.0.3839.0-r1-redacted.afdo.xz'))),
    ]
    self.assertEqual(expected_exists, self.gs_context.Exists.call_args_list)
    self.patch_ebuild.assert_called_once_with(
        self.obj._GetEbuildInfo(toolchain_util.constants.CHROME_PN),
        {
            'UNVETTED_AFDO_FILE': os.path.join(
                self.tempdir,
                ('tmp/chromeos-chrome-amd64-atom-78-3877.0-1658747184-'
                 'benchmark-78.0.3839.0-r1-redacted.afdo'))
        }, uprev=True)

  def testPrepareVerifiedReleaseAfdoFileArmProfile(self):
    """Normal flow with Arm, build is needed, all artifacts are present."""
    profile_info_extra = {'chrome_cwp_profile': 'arm'}
    self.setupPrepareVerifiedReleaseAfdoFileInputProperties(profile_info_extra)
    self.setupPrepareVerifiedReleaseAfdoFileMocks()
    # Published artifact is missing, debug binary is present, perf.data is
    # present.
    self.gsc_exists.return_value = False
    self.assertEqual(toolchain_util.PrepareForBuildReturn.NEEDED,
                     self.obj.Prepare())
    # Expect to see -arm-none-.
    expected_exists = [
        mock.call(os.path.join(
            toolchain_util.RELEASE_AFDO_GS_URL_VETTED,
            'chromeos-chrome-arm-none-78-3877.0-1658747184-'
            'benchmark-78.0.3839.0-r1-redacted.afdo.xz')),
    ]
    self.assertEqual(expected_exists, self.gs_context.Exists.call_args_list)
    self.patch_ebuild.assert_called_once_with(
        self.obj._GetEbuildInfo(toolchain_util.constants.CHROME_PN),
        {
            'UNVETTED_AFDO_FILE': os.path.join(
                self.tempdir,
                ('tmp/chromeos-chrome-arm-none-78-3877.0-1658747184-'
                 'benchmark-78.0.3839.0-r1-redacted.afdo'))
        }, uprev=True)

  def testPrepareVerifiedReleaseAfdoFileMissingInput(self):
    """Test that _PrepareVerifiedReleaseAfdoFile works when POINTLESS."""
    self.setupPrepareVerifiedReleaseAfdoFileInputProperties()
    self.setupPrepareVerifiedReleaseAfdoFileMocks()
    with self.assertRaisesRegex(
        toolchain_util.PrepareForBuildHandlerError,
        r'Could not find profile name.'):
      self.obj.Prepare()


class BundleArtifactHandlerTest(PrepareBundleTest):
  """Test BundleArtifactHandler specific methods."""

  def setUp(self):

    def _Bundle(_self):
      osutils.WriteFile(os.path.join(_self.output_dir, 'artifact'), 'data\n')

    self.artifact_type = 'Unspecified'
    self.outdir = None
    self.afdo_tmp_path = None
    self.kernel_version = '4_4'
    self.profile_info = {
        'kernel_version': self.kernel_version.replace('_', '.'),
    }
    self.orderfile_name = (
        'chromeos-chrome-orderfile-field-78-3877.0-1567418235-'
        'benchmark-78.0.3893.0-r1.orderfile')
    self.afdo_name = 'chromeos-chrome-amd64-78.0.3893.0_rc-r1.afdo'
    self.perf_name = 'chromeos-chrome-amd64-78.0.3893.0.perf.data'
    self.debug_binary_name = 'chromeos-chrome-amd64-78.0.3893.0_rc-r1.debug'
    self.merged_afdo_name = (
        'chromeos-chrome-amd64-78.0.3893.0_rc-r1-merged.afdo')
    self.kernel_name = 'R89-13638.0-1607337135'

    self.gen_order = self.PatchObject(
        toolchain_util.GenerateChromeOrderfile, 'Bundle', new=_Bundle)
    self.PatchObject(
        toolchain_util, '_GetOrderfileName', return_value=self.orderfile_name)
    self.PatchObject(
        cros_build_lib, 'IsInsideChroot', return_value=False)
    self.copy2 = self.PatchObject(shutil, 'copy2')

    class mock_datetime(object):
      """Class for mocking datetime.datetime."""

      @staticmethod
      def strftime(_when, _fmt):
        return 'DATE'

      @staticmethod
      def now():
        return -1

    self.PatchObject(datetime, 'datetime', new=mock_datetime)

  def SetUpBundle(self, artifact_type):
    """Set up to test _Bundle${artifactType}."""
    self.artifact_type = artifact_type
    self.outdir = os.path.join(self.tempdir, 'tmp', 'output_dir')
    osutils.SafeMakedirs(self.outdir)
    self.afdo_tmp_path = '/tmp/benchmark-afdo-generate'
    osutils.SafeMakedirs(self.chroot.full_path(self.afdo_tmp_path))
    self.obj = toolchain_util.BundleArtifactHandler(self.artifact_type,
                                                    self.chroot, self.sysroot,
                                                    self.board, self.outdir,
                                                    self.profile_info)
    self.obj._gs_context = self.gs_context

  def testBundleUnverifiedChromeLlvmOrderfile(self):
    """Test that BundleUnverfiedChromeLlvmOrderfile works."""
    self.SetUpBundle('UnverifiedChromeLlvmOrderfile')
    artifact = os.path.join(self.outdir, 'artifact')
    self.assertEqual([artifact], self.obj.Bundle())
    self.copy2.assert_called_once_with(mock.ANY, Path(artifact))

  def testBundleVerifiedChromeLlvmOrderfileExists(self):
    """Test that BundleVerfiedChromeLlvmOrderfile works."""
    self.SetUpBundle('VerifiedChromeLlvmOrderfile')
    self.PatchObject(
        toolchain_util._CommonPrepareBundle,
        '_GetArtifactVersionInEbuild',
        return_value=self.orderfile_name)
    artifact = os.path.join(self.outdir, '%s.xz' % self.orderfile_name)
    self.assertEqual([artifact], self.obj.Bundle())
    self.copy2.assert_called_once_with(
        os.path.join(self.chroot.path, 'build', self.board, 'opt/google/chrome',
                     '%s.xz' % self.orderfile_name), artifact)

  def testBundleVerifiedChromeLlvmOrderfileRaises(self):
    """Test that BundleVerfiedChromeLlvmOrderfile raises exception."""
    self.SetUpBundle('VerifiedChromeLlvmOrderfile')
    # Chrome ebuild file is missing UNVETTED_ORDERFILE.
    self.PatchObject(
        builtins, 'open', mock.mock_open(read_data=''))
    with self.assertRaisesRegex(
        toolchain_util.BundleArtifactsHandlerError,
        f'Could not find UNVETTED_ORDERFILE version in {constants.CHROME_PN}'):
      self.obj.Bundle()

  def testBundleChromeClangWarningsFile(self):
    """Test that BundleChromeClangWarningsFile works."""
    self.SetUpBundle('ChromeClangWarningsFile')
    artifact = os.path.join(self.outdir,
                            '%s.DATE.clang_tidy_warnings.tar.xz' % self.board)
    self.assertEqual([artifact], self.obj.Bundle())
    self.copy2.assert_called_once_with(mock.ANY, artifact)

  def testBundleUnverifiedLlvmPgoFile(self, llvm_path='llvm-project'):
    self.SetUpBundle('UnverifiedLlvmPgoFile')
    llvm_version = '10.0_pre377782_p20200113-r14'
    llvm_clang_sha = 'a21beccea2020f950845cbb68db663d0737e174c'
    llvm_pkg = package_info.parse('sys-devel/llvm-%s' % llvm_version)
    self.PatchObject(
        self.obj,
        '_GetProfileNames',
        return_value=[
            self.chroot.full_path(self.sysroot, 'build', 'coverage_data',
                                  'sys-libs', 'libcxxabi', 'raw_profiles',
                                  'libcxxabi-10.0_pre3_1673101222_0.profraw')
        ])
    self.PatchObject(
        portage_util, 'FindPackageNameMatches', return_value=[llvm_pkg])
    self.rc.AddCmdResult(
        partial_mock.In('clang'),
        returncode=0,
        stdout=(f'Chromium OS {llvm_version} clang version 10.0.0 '
                f'(/path/to/{llvm_path} {llvm_clang_sha})'))
    base = f'{llvm_pkg.pvr}-{llvm_clang_sha}'
    artifacts = [
        os.path.join(self.outdir, x)
        for x in (f'{base}.llvm_metadata.json', 'llvm_metadata.json',
                  f'{base}.llvm.profdata.tar.xz')
    ]
    self.assertEqual(artifacts, self.obj.Bundle())

  def testBundleUnverifiedLlvmPgoFileWorkaround(self):
    self.testBundleUnverifiedLlvmPgoFile('clang')

  def testBundleUnverifiedChromeBenchmarkPerfFile(self):
    self.SetUpBundle('UnverifiedChromeBenchmarkPerfFile')
    self.assertEqual([], self.obj.Bundle())

  def testBundleChromeDebugBinary(self):
    self.SetUpBundle('ChromeDebugBinary')
    bin_path = toolchain_util._CHROME_DEBUG_BIN % {
        'root': self.chroot.path,
        'sysroot': self.sysroot
    }
    osutils.WriteFile(bin_path, '', makedirs=True)
    output = os.path.join(
        self.outdir,
        self.debug_binary_name + toolchain_util.BZ2_COMPRESSION_SUFFIX)
    self.assertEqual([output], self.obj.Bundle())

  @mock.patch.object(builtins, 'open')
  def testBundleUnverifiedChromeBenchmarkAfdoFile(self, mock_open):
    self.SetUpBundle('UnverifiedChromeBenchmarkAfdoFile')
    self.PatchObject(
        self.obj,
        '_GetEbuildInfo',
        return_value=toolchain_util._EbuildInfo(
            path=self.chrome_ebuild, CPV=self.chrome_pkg))
    run_command = self.PatchObject(cros_build_lib, 'run')
    sym_link_command = self.PatchObject(osutils, 'SafeSymlink')
    # Return ~1MB profile size.
    self.PatchObject(os.path, 'getsize', return_value=100000)
    mock_file_obj = io.StringIO()
    mock_open.return_value = mock_file_obj

    ret = self.obj.Bundle()
    afdo_path = os.path.join(
        self.outdir, self.afdo_name + toolchain_util.BZ2_COMPRESSION_SUFFIX)
    self.assertEqual([afdo_path], ret)
    # Make sure the sym link to debug Chrome is created
    sym_link_command.assert_called_with(
        self.debug_binary_name,
        self.chroot.full_path(
            os.path.join(self.afdo_tmp_path, 'chrome.unstripped')))
    afdo_path_inside = os.path.join(self.afdo_tmp_path, self.afdo_name)
    # Make sure commands are executed correctly
    mock_calls = [
        mock.call([
            toolchain_util._AFDO_GENERATE_LLVM_PROF,
            '--binary=' + os.path.join(self.afdo_tmp_path, 'chrome.unstripped'),
            '--profile=' + os.path.join(self.afdo_tmp_path, self.perf_name),
            '--out=' + afdo_path_inside,
            '--sample_threshold_frac=0',
        ],
                  enter_chroot=True,
                  print_cmd=True),
        mock.call(['bzip2', '-c', afdo_path_inside],
                  stdout=mock_file_obj,
                  enter_chroot=True,
                  print_cmd=True)
    ]
    run_command.assert_has_calls(mock_calls)

  @mock.patch.object(builtins, 'open')
  def testBundleUnverifiedChromeBenchmarkAfdoFileRaisesError(self, mock_open):
    self.SetUpBundle('UnverifiedChromeBenchmarkAfdoFile')
    self.PatchObject(
        self.obj,
        '_GetEbuildInfo',
        return_value=toolchain_util._EbuildInfo(
            path=self.chrome_ebuild, CPV=self.chrome_pkg))
    self.PatchObject(cros_build_lib, 'run')
    self.PatchObject(osutils, 'SafeSymlink')
    # Return invalid size of the profile.
    self.PatchObject(os.path, 'getsize', return_value=100)
    mock_file_obj = io.StringIO()
    mock_open.return_value = mock_file_obj

    with self.assertRaises(toolchain_util.BundleArtifactsHandlerError):
      self.obj.Bundle()

  def testBundleChromeAFDOProfileForAndroidLinuxFailWhenNoBenchmark(self):
    self.SetUpBundle('ChromeAFDOProfileForAndroidLinux')
    merge_function = self.PatchObject(self.obj,
                                      '_CreateAndUploadMergedAFDOProfile')
    with self.assertRaises(AssertionError) as context:
      self.obj.Bundle()
    self.assertIn('No new AFDO profile created', str(context.exception))
    merge_function.assert_not_called()

  @mock.patch.object(builtins, 'open')
  def testBundleChromeAFDOProfileForAndroidLinuxPass(self, mock_open):
    self.SetUpBundle('ChromeAFDOProfileForAndroidLinux')
    self.PatchObject(os.path, 'exists', return_value=True)
    run_command = self.PatchObject(cros_build_lib, 'run')
    merge_function = self.PatchObject(
        self.obj,
        '_CreateAndUploadMergedAFDOProfile',
        return_value=self.merged_afdo_name)
    mock_file_obj = io.StringIO()
    mock_open.return_value = mock_file_obj

    ret = self.obj.Bundle()
    merged_path = os.path.join(
        self.outdir,
        self.merged_afdo_name + toolchain_util.BZ2_COMPRESSION_SUFFIX)
    self.assertEqual([merged_path], ret)
    # Make sure merged function is called
    afdo_path_inside = os.path.join(self.afdo_tmp_path, self.afdo_name)
    merged_path_inside = os.path.join(self.afdo_tmp_path, self.merged_afdo_name)
    merge_function.assert_called_with(
        self.chroot.full_path(afdo_path_inside),
        self.chroot.full_path(os.path.join(self.afdo_tmp_path)))
    run_command.assert_called_with(
        ['bzip2', '-c', merged_path_inside],
        stdout=mock_file_obj,
        enter_chroot=True,
        print_cmd=True,
    )

  def callBundleVerifiedKernelCwpAfdoFile(self, ebuild_data_list):
    self.SetUpBundle('VerifiedKernelCwpAfdoFile')
    ebuild_info = toolchain_util._EbuildInfo(
        path='/path/to/kernel-9999.ebuild', CPV=mock.MagicMock())
    self.PatchObject(self.obj, '_GetEbuildInfo', return_value=ebuild_info)
    ebuild_old_str = ''.join(ebuild_data_list)
    # We are going to check how the mock_object was called.
    self.PatchObject(
        builtins, 'open', mock.mock_open(read_data=(ebuild_old_str)))

    ret = self.obj.Bundle()
    profile_name = self.kernel_name + (
        toolchain_util.KERNEL_AFDO_COMPRESSION_SUFFIX)
    verified_profile = os.path.join(self.outdir, profile_name)
    self.assertEqual([verified_profile], ret)
    profile_path = os.path.join(
        self.chroot.path, self.sysroot[1:], 'usr', 'lib', 'debug', 'boot',
        f'chromeos-kernel-{self.kernel_version}-{profile_name}')
    self.copy2.assert_called_once_with(profile_path, verified_profile)

  def testBundleVerifiedKernelCwpAfdoFileOld(self):
    """Test BundleVerifiedKernelCwpAfdoFile with the old ebuild."""
    ebuild_data_list = ('# some comment\n',
                        'AFDO_LOCATION=""\n',
                        f'AFDO_PROFILE_VERSION="{self.kernel_name}"')
    self.callBundleVerifiedKernelCwpAfdoFile(ebuild_data_list)

  def testBundleVerifiedKernelCwpAfdoFileNew(self):
    """Test BundleVerifiedKernelCwpAfdoFile with the new ebuild."""
    ebuild_data_list = ('# some comment\n',
                        'export AFDO_LOCATION=""\n',
                        f'export AFDO_PROFILE_VERSION="{self.kernel_name}"')
    self.callBundleVerifiedKernelCwpAfdoFile(ebuild_data_list)

  def testBundleVerifiedKernelCwpAfdoFileRaises(self):
    """Test that BundleVerifiedKernelCwpAfdoFile raises exception."""
    # AFDO_PROFILE_VERSION is missing in the ebuild.
    ebuild_data_list = ('# some comment\n',
                        'AFDO_LOCATION=""')
    with self.assertRaisesRegex(
        toolchain_util.BundleArtifactsHandlerError,
        'Could not find AFDO_PROFILE_VERSION in '
        f'chromeos-kernel-{self.kernel_version}'):
      self.callBundleVerifiedKernelCwpAfdoFile(ebuild_data_list)

  def runToolchainBundleTest(self, artifact_path, tarball_name, input_files,
                             expected_output_files):
    """Asserts that the given artifact_path is tarred up properly.

    If no output files are expected, we assert that no tarballs are created.

    Args:
      artifact_path: the path to touch |input_files| in.
      tarball_name: the expected name of the tarball we will produce.
      input_files: a list of files to |touch| relative to |artifact_path|.
      expected_output_files: a list of files that should be present in the
        tarball.

    Returns:
      Nothing.
    """
    with mock.patch.object(cros_build_lib,
                           'CreateTarball') as create_tarball_mock:
      in_chroot_dirs = [
          artifact_path,
          '/build/%s%s' % (self.board, artifact_path)
      ]
      for d in (self.chroot.full_path(x) for x in in_chroot_dirs):
        for l in input_files:
          p = os.path.join(d, l)
          osutils.SafeMakedirs(os.path.dirname(p))
          osutils.Touch(p)

      tarball = self.obj.Bundle()

      if len(expected_output_files) > 0:
        tarball_path = os.path.join(self.outdir, tarball_name)
        self.assertEqual(tarball, [tarball_path])

        create_tarball_mock.assert_called_once()
        output, _tempdir = create_tarball_mock.call_args[0]
        self.assertEqual(output, tarball_path)
        inputs = create_tarball_mock.call_args[1]['inputs']
        self.assertCountEqual(expected_output_files, inputs)
      else:
        # Bundlers do not create tarballs when no artifacts are found.
        self.assertEqual(tarball, [])

  def testBundleToolchainWarningLogs(self):
    self.SetUpBundle('ToolchainWarningLogs')
    artifact_path = '/tmp/fatal_clang_warnings'
    tarball_name = '%s.DATE.fatal_clang_warnings.tar.xz' % self.board

    # Test behaviour when no artifacts are found.
    self.runToolchainBundleTest(artifact_path, tarball_name, [], [])

    # Test behaviour when artifacts are found.
    self.runToolchainBundleTest(
        artifact_path,
        tarball_name,
        input_files=('log1.json', 'log2.json', 'log3.notjson', 'log4'),
        expected_output_files=(
            'log1.json',
            'log10.json',
            'log2.json',
            'log20.json',
        ),
    )

  def testBundleClangCrashDiagnoses(self):
    self.SetUpBundle('ClangCrashDiagnoses')
    artifact_path = '/tmp/clang_crash_diagnostics'
    tarball_name = '%s.DATE.clang_crash_diagnoses.tar.xz' % self.board

    # Test behaviour when no artifacts are found.
    self.runToolchainBundleTest(artifact_path, tarball_name, [], [])

    # Test behaviour when artifacts are found.
    self.runToolchainBundleTest(
        artifact_path,
        tarball_name,
        input_files=('1.cpp', '1.sh', '2.cc', '2.sh', 'foo/bar.sh'),
        expected_output_files=(
            '1.cpp',
            '1.sh',
            '10.cpp',
            '10.sh',
            '2.cc',
            '2.sh',
            '20.cc',
            '20.sh',
            'foo/bar.sh',
            'foo/bar0.sh',
        ),
    )

  def testBundleCompilerRusageLogs(self):
    self.SetUpBundle('CompilerRusageLogs')
    artifact_path = '/tmp/compiler_rusage'
    tarball_name = '%s.DATE.compiler_rusage_logs.tar.xz' % self.board

    # Test behaviour when no artifacts are found.
    self.runToolchainBundleTest(artifact_path, tarball_name, [], [])

    # Test behaviour when artifacts are found.
    self.runToolchainBundleTest(
        artifact_path,
        tarball_name,
        input_files=(
            'good1.json',
            'good2.json',
            'good3.json',
            'bad1.notjson',
            'bad2',
            'json',
        ),
        expected_output_files=(
            'good1.json',
            'good2.json',
            'good3.json',
            'good10.json',
            'good20.json',
            'good30.json',
        ),
    )


class ReleaseChromeAFDOProfileTest(PrepareBundleTest):
  """Test functions related to create a release CrOS profile.

  Since these functions are similar to _UploadReleaseChromeAFDO() and
  related functions. These tests are also similar to
  UploadReleaseChromeAFDOTest, except the setup are within recipe
  environment.
  """

  def setUp(self):
    self.cwp_name = 'R77-3809.38-1562580965.afdo'
    self.cwp_full = self.cwp_name + toolchain_util.XZ_COMPRESSION_SUFFIX
    self.arch = 'atom'
    self.benchmark_name = 'chromeos-chrome-amd64-77.0.3849.0_rc-r1.afdo'
    self.benchmark_full = (self.benchmark_name +
                           toolchain_util.BZ2_COMPRESSION_SUFFIX)
    cwp_string = '%s-77-3809.38-1562580965' % self.arch
    benchmark_string = 'benchmark-77.0.3849.0-r1'
    self.merged_name = 'chromeos-chrome-amd64-%s-%s' % (cwp_string,
                                                        benchmark_string)
    self.redacted_name = self.merged_name + '-redacted.afdo'
    self.cwp_url = os.path.join(toolchain_util.CWP_AFDO_GS_URL, self.arch,
                                self.cwp_full)
    self.benchmark_url = os.path.join(toolchain_util.BENCHMARK_AFDO_GS_URL,
                                      self.benchmark_full)
    self.merge_inputs = [
        (os.path.join(self.tempdir,
                      self.cwp_name), toolchain_util.RELEASE_CWP_MERGE_WEIGHT),
        (os.path.join(self.tempdir, self.benchmark_name),
         toolchain_util.RELEASE_BENCHMARK_MERGE_WEIGHT),
    ]
    self.merge_output = os.path.join(self.tempdir, self.merged_name)

    self.gs_copy = self.PatchObject(self.gs_context, 'Copy')
    self.decompress = self.PatchObject(cros_build_lib, 'UncompressFile')
    self.run_command = self.PatchObject(cros_build_lib, 'run')

  def testMergeAFDOProfiles(self):
    self.obj._MergeAFDOProfiles(self.merge_inputs, self.merge_output)
    merge_command = [
        'llvm-profdata',
        'merge',
        '-sample',
        '-output=' + self.chroot.chroot_path(self.merge_output),
    ] + [
        '-weighted-input=%d,%s' % (weight, self.chroot.chroot_path(name))
        for name, weight in self.merge_inputs
    ]
    self.run_command.assert_called_once_with(
        merge_command, enter_chroot=True, print_cmd=True)

  def runProcessAFDOProfileOnce(self,
                                expected_commands,
                                input_path=None,
                                output_path=None,
                                *args,
                                **kwargs):
    if not input_path:
      input_path = os.path.join(self.tempdir, 'input.afdo')
    if not output_path:
      output_path = os.path.join(self.tempdir, 'output.afdo')
    # Return ~1MB profile size.
    self.PatchObject(os.path, 'getsize', return_value=100000)
    self.obj._ProcessAFDOProfile(input_path, output_path, *args, **kwargs)

    self.run_command.assert_has_calls(expected_commands)

  def testProcessAFDOProfileForAndroidLinuxProfile(self):
    """Test call on _processAFDOProfile() for Android/Linux profiles."""
    input_path = os.path.join(self.tempdir, 'android.prof.afdo')
    input_path_inchroot = self.chroot.chroot_path(input_path)
    input_to_text = input_path_inchroot + '.text.temp'
    removed_temp = input_path_inchroot + '.removed.temp'
    reduced_temp = input_path_inchroot + '.reduced.tmp'
    reduce_functions = 70000
    output_path = os.path.join(self.tempdir, 'android.prof.output.afdo')
    expected_commands = [
        mock.call(
            [
                'llvm-profdata',
                'merge',
                '-sample',
                '-text',
                input_path_inchroot,
                '-output',
                input_to_text,
            ],
            enter_chroot=True,
            print_cmd=True,
        ),
        mock.call(
            [
                'remove_indirect_calls',
                '--input=' + input_to_text,
                '--output=' + removed_temp,
            ],
            enter_chroot=True,
            print_cmd=True,
        ),
        mock.call(
            [
                'remove_cold_functions',
                '--input=' + removed_temp,
                '--output=' + reduced_temp,
                '--number=' + str(reduce_functions),
            ],
            enter_chroot=True,
            print_cmd=True,
        ),
        mock.call(
            [
                'llvm-profdata',
                'merge',
                '-sample',
                reduced_temp,
                '-output',
                self.chroot.chroot_path(output_path),
            ],
            enter_chroot=True,
            print_cmd=True,
        )
    ]

    self.runProcessAFDOProfileOnce(
        expected_commands,
        input_path=input_path,
        output_path=output_path,
        remove=True,
        reduce_functions=reduce_functions)

  def testProcessAFDOProfileRaisesError(self):
    input_path = os.path.join(self.tempdir, 'input.afdo')
    output_path = os.path.join(self.tempdir, 'output.afdo')
    # Return invalid size of the profile.
    self.PatchObject(os.path, 'getsize', return_value=100)
    with self.assertRaises(toolchain_util.BundleArtifactsHandlerError):
      self.obj._ProcessAFDOProfile(input_path, output_path)

  @mock.patch.object(builtins, 'open')
  def testProcessAFDOProfileForChromeOSReleaseProfile(self, mock_open):
    """Test call on _processAFDOProfile() for CrOS release profiles."""
    input_path = os.path.join(self.tempdir, self.merged_name)
    input_path_inchroot = self.chroot.chroot_path(input_path)
    input_to_text = input_path_inchroot + '.text.temp'
    redacted_temp = input_path_inchroot + '.redacted.temp'
    redacted_temp_full = input_path + '.redacted.temp'
    removed_temp = input_path_inchroot + '.removed.temp'
    reduced_temp = input_path_inchroot + '.reduced.tmp'
    reduce_functions = 20000
    output_path = os.path.join(self.tempdir, self.redacted_name)
    mock_file_obj = io.StringIO()
    mock_open.return_value = mock_file_obj

    expected_commands = [
        mock.call(
            [
                'llvm-profdata',
                'merge',
                '-sample',
                '-text',
                input_path_inchroot,
                '-output',
                input_to_text,
            ],
            enter_chroot=True,
            print_cmd=True,
        ),
        mock.call(
            ['redact_textual_afdo_profile'],
            input=mock_file_obj,
            stdout=redacted_temp_full,
            print_cmd=True,
            enter_chroot=True,
        ),
        mock.call(
            [
                'remove_indirect_calls',
                '--input=' + redacted_temp,
                '--output=' + removed_temp,
            ],
            enter_chroot=True,
            print_cmd=True,
        ),
        mock.call(
            [
                'remove_cold_functions',
                '--input=' + removed_temp,
                '--output=' + reduced_temp,
                '--number=' + str(reduce_functions),
            ],
            enter_chroot=True,
            print_cmd=True,
        ),
        mock.call(
            [
                'llvm-profdata',
                'merge',
                '-sample',
                reduced_temp,
                '-output',
                self.chroot.chroot_path(output_path),
                '-compbinary',
            ],
            enter_chroot=True,
            print_cmd=True,
        )
    ]
    self.runProcessAFDOProfileOnce(
        expected_commands,
        input_path=input_path,
        output_path=output_path,
        redact=True,
        remove=True,
        reduce_functions=reduce_functions,
        compbinary=True)

  def testCreateReleaseChromeAFDO(self):
    merged_call = self.PatchObject(self.obj, '_MergeAFDOProfiles')
    process_call = self.PatchObject(self.obj, '_ProcessAFDOProfile')
    ret = self.obj._CreateReleaseChromeAFDO(self.cwp_url, self.benchmark_url,
                                            self.tempdir, self.merged_name)

    self.assertEqual(ret, os.path.join(self.tempdir, self.redacted_name))
    self.gs_copy.assert_has_calls([
        mock.call(self.cwp_url, os.path.join(self.tempdir, self.cwp_full)),
        mock.call(self.benchmark_url,
                  os.path.join(self.tempdir, self.benchmark_full))
    ])

    # Check decompress files.
    decompress_calls = [
        mock.call(
            os.path.join(self.tempdir, self.cwp_full),
            os.path.join(self.tempdir, self.cwp_name)),
        mock.call(
            os.path.join(self.tempdir, self.benchmark_full),
            os.path.join(self.tempdir, self.benchmark_name))
    ]
    self.decompress.assert_has_calls(decompress_calls)

    # Check call to merge.
    merged_call.assert_called_once_with(
        self.merge_inputs,
        os.path.join(self.tempdir, self.merged_name),
    )

    # Check calls to redact.
    process_call.assert_called_once_with(
        self.merge_output,
        os.path.join(self.tempdir, self.redacted_name),
        redact=True,
        remove=True,
        reduce_functions=20000,
        compbinary=True,
    )


class CreateAndUploadMergedAFDOProfileTest(PrepBundLatestAFDOArtifactTest):
  """Test CreateAndUploadMergedAFDOProfile and related functions.

  These tests are mostly coming from cbuildbot/afdo_unittest.py, and are
  written to adapt to recipe functions. When legacy builders are removed,
  those tests can be safely preserved by this one.
  """

  @staticmethod
  def _benchmark_afdo_profile_name(major=0,
                                   minor=0,
                                   build=0,
                                   patch=0,
                                   rev=1,
                                   merged_suffix=False,
                                   compression_suffix=True,
                                   arch='amd64'):
    suffix = '-merged' if merged_suffix else ''
    result = (f'chromeos-chrome-{arch}-{major}.{minor}.{build}.{patch}'
              f'_rc-r{rev}{suffix}')
    result += toolchain_util.AFDO_SUFFIX
    if compression_suffix:
      result += toolchain_util.BZ2_COMPRESSION_SUFFIX
    return result

  def setUp(self):
    self.benchmark_url = 'gs://path/to/unvetted'
    self.obj.input_artifacts = {
        'UnverifiedChromeBenchmarkAfdoFile': [self.benchmark_url],
    }
    self.obj.chroot = self.chroot
    self.output_dir = os.path.join(self.chroot.path, 'tmp', 'output_dir')
    osutils.SafeMakedirs(self.output_dir)
    self.output_dir_inchroot = self.chroot.chroot_path(self.output_dir)
    self.now = datetime.datetime.now()

  def runCreateAndUploadMergedAFDOProfileOnce(self, arch=None, **kwargs):
    if 'unmerged_name' not in kwargs:
      # Match everything.
      kwargs['unmerged_name'] = self._benchmark_afdo_profile_name(
          major=9999, compression_suffix=False)

    if 'output_dir' not in kwargs:
      kwargs['output_dir'] = self.output_dir

    Mocks = collections.namedtuple('Mocks', [
        'gs_context',
        'find_artifact',
        'run_command',
        'uncompress_file',
        'compress_file',
        'process_afdo_profile',
    ])

    def MockList(*_args, **_kwargs):
      files = [
          self._benchmark_afdo_profile_name(major=10, build=9),
          self._benchmark_afdo_profile_name(major=10, build=10),
          self._benchmark_afdo_profile_name(
              major=10, build=10, merged_suffix=True),
          self._benchmark_afdo_profile_name(major=10, build=11),
          self._benchmark_afdo_profile_name(major=10, build=12),
          self._benchmark_afdo_profile_name(major=10, build=13),
          # Profiles with 'arm' have to be filtered out unless Bundle uses
          # other than 'amd64' arch.
          self._benchmark_afdo_profile_name(major=10, build=13, arch='arm'),
          self._benchmark_afdo_profile_name(
              major=10, build=13, merged_suffix=True),
          self._benchmark_afdo_profile_name(
              major=10, build=13, patch=1, arch='arm'),
          self._benchmark_afdo_profile_name(major=10, build=13, patch=1),
          self._benchmark_afdo_profile_name(major=10, build=13, patch=2),
          self._benchmark_afdo_profile_name(
              major=10, build=13, patch=2, merged_suffix=True),
          self._benchmark_afdo_profile_name(major=11, build=14),
          self._benchmark_afdo_profile_name(major=11, build=14, arch='arm'),
          self._benchmark_afdo_profile_name(
              major=11, build=14, merged_suffix=True),
          self._benchmark_afdo_profile_name(major=11, build=15),
          self._benchmark_afdo_profile_name(major=11, build=15, arch='arm'),
      ]

      results = []
      for i, name in enumerate(files):
        url = os.path.join(self.benchmark_url, name)
        now = self.now - datetime.timedelta(days=len(files) - i)
        results.append(self.MockListResult(url=url, creation_time=now))
      # Add a random file with the newest timestamp.
      # The file has to be ignored by the pattern matcher.
      results.append(
          self.MockListResult(url='file-to-be-ignored', creation_time=self.now))
      # Make MockList() a little bit smarter.
      # Give the list of files glob matching "path" from gs_context.List(path).
      # fnmatch() is what glob() is eventually calling.
      return [res for res in results if fnmatch.fnmatch(res.url, _args[0])]

    self.gs_context.List = MockList
    run_command = self.PatchObject(cros_build_lib, 'run')
    uncompress_file = self.PatchObject(cros_build_lib, 'UncompressFile')
    compress_file = self.PatchObject(cros_build_lib, 'CompressFile')
    process_afdo_profile = self.PatchObject(self.obj, '_ProcessAFDOProfile')
    unmerged_profile = os.path.join(self.output_dir,
                                    kwargs.pop('unmerged_name'))
    osutils.Touch(unmerged_profile)
    kwargs['unmerged_profile'] = unmerged_profile

    # Change arch based on the test argument.
    if arch:
      self.obj.arch = arch
    merged_name = self.obj._CreateAndUploadMergedAFDOProfile(**kwargs)
    return merged_name, Mocks(
        gs_context=self.gs_context,
        find_artifact=MockList,
        run_command=run_command,
        uncompress_file=uncompress_file,
        compress_file=compress_file,
        process_afdo_profile=process_afdo_profile,
    )

  def testCreateAndUploadMergedAFDOProfileErrorWhenProfileInBucket(self):
    unmerged_name = self._benchmark_afdo_profile_name(major=10, build=13)
    merged_name = None
    with self.assertRaises(AssertionError):
      merged_name, _ = self.runCreateAndUploadMergedAFDOProfileOnce(
          unmerged_name=unmerged_name)
    self.assertIsNone(merged_name)

  def testCreateAndUploadMergedAFDOProfileMergesBranchProfiles(self):
    unmerged_name = self._benchmark_afdo_profile_name(
        major=10, build=13, patch=99, compression_suffix=False)

    merged_name, mocks = self.runCreateAndUploadMergedAFDOProfileOnce(
        unmerged_name=unmerged_name)
    self.assertIsNotNone(merged_name)

    def _afdo_name(major, build, patch=0, merged_suffix=False):
      return self._benchmark_afdo_profile_name(
          major=major,
          build=build,
          patch=patch,
          merged_suffix=merged_suffix,
          compression_suffix=False)

    expected_unordered_args = [
        '-output=' + os.path.join(
            self.output_dir_inchroot, 'raw-' +
            _afdo_name(major=10, build=13, patch=99, merged_suffix=True))
    ] + [
        '-weighted-input=1,' + os.path.join(self.output_dir_inchroot, s)
        for s in [
            _afdo_name(major=10, build=12),
            _afdo_name(major=10, build=13),
            _afdo_name(major=10, build=13, patch=1),
            _afdo_name(major=10, build=13, patch=2),
            _afdo_name(major=10, build=13, patch=99),
        ]
    ]

    # Note that these should all be in-chroot names.
    expected_ordered_args = ['llvm-profdata', 'merge', '-sample']

    args = mocks.run_command.call_args[0][0]
    ordered_args = args[:len(expected_ordered_args)]
    self.assertEqual(ordered_args, expected_ordered_args)

    unordered_args = args[len(expected_ordered_args):]

    self.assertCountEqual(unordered_args, expected_unordered_args)
    self.assertEqual(mocks.gs_context.Copy.call_count, 4)

  def testCreateAndUploadMergedAFDOProfileRemovesIndirectCallTargets(self):
    unmerged_name = self._benchmark_afdo_profile_name(
        major=10, build=13, patch=99, compression_suffix=False)

    merged_name, mocks = self.runCreateAndUploadMergedAFDOProfileOnce(
        recent_to_merge=2,
        unmerged_name=unmerged_name)
    self.assertIsNotNone(merged_name)

    def _afdo_name(major, build, patch=0, merged_suffix=False):
      return self._benchmark_afdo_profile_name(
          major=major,
          build=build,
          patch=patch,
          merged_suffix=merged_suffix,
          compression_suffix=False)

    merge_output_name = 'raw-' + _afdo_name(
        major=10, build=13, patch=99, merged_suffix=True)
    self.assertNotEqual(merged_name, merge_output_name)

    expected_unordered_args = [
        '-output=' + os.path.join(self.output_dir_inchroot, merge_output_name),
        '-weighted-input=1,' + os.path.join(
            self.output_dir_inchroot, _afdo_name(major=10, build=13, patch=2)),
        '-weighted-input=1,' + os.path.join(
            self.output_dir_inchroot, _afdo_name(major=10, build=13, patch=99)),
    ]

    # Note that these should all be in-chroot names.
    expected_ordered_args = ['llvm-profdata', 'merge', '-sample']
    args = mocks.run_command.call_args[0][0]
    ordered_args = args[:len(expected_ordered_args)]
    self.assertEqual(ordered_args, expected_ordered_args)

    unordered_args = args[len(expected_ordered_args):]
    self.assertCountEqual(unordered_args, expected_unordered_args)

    mocks.process_afdo_profile.assert_called_once_with(
        os.path.join(self.output_dir, merge_output_name),
        os.path.join(self.output_dir, merged_name),
        redact=False,
        remove=True,
        reduce_functions=70000,
        compbinary=False,
    )

  def testCreateAndUploadMergedAFDOProfileWorksInTheHappyCase(self):
    merged_name, mocks = self.runCreateAndUploadMergedAFDOProfileOnce()
    self.assertIsNotNone(merged_name)

    # Note that we always return the *basename*
    self.assertEqual(
        merged_name,
        self._benchmark_afdo_profile_name(
            major=9999, merged_suffix=True, compression_suffix=False))

    mocks.run_command.assert_called_once()

    # Note that these should all be in-chroot names.
    expected_ordered_args = ['llvm-profdata', 'merge', '-sample']

    def _afdo_name(major, build=0, patch=0, merged_suffix=False):
      return self._benchmark_afdo_profile_name(
          major=major,
          build=build,
          patch=patch,
          merged_suffix=merged_suffix,
          compression_suffix=False)

    input_afdo_names = [
        _afdo_name(major=10, build=13, patch=1),
        _afdo_name(major=10, build=13, patch=2),
        _afdo_name(major=11, build=14),
        _afdo_name(major=11, build=15),
        _afdo_name(major=9999),
    ]

    output_afdo_name = _afdo_name(major=9999, merged_suffix=True)
    expected_unordered_args = [
        '-output=' +
        os.path.join(self.output_dir_inchroot, 'raw-' + output_afdo_name)
    ] + [
        '-weighted-input=1,' + os.path.join(self.output_dir_inchroot, n)
        for n in input_afdo_names
    ]

    args = mocks.run_command.call_args[0][0]
    ordered_args = args[:len(expected_ordered_args)]
    self.assertEqual(ordered_args, expected_ordered_args)

    unordered_args = args[len(expected_ordered_args):]
    self.assertCountEqual(unordered_args, expected_unordered_args)
    self.assertEqual(mocks.gs_context.Copy.call_count, 4)
    self.assertEqual(mocks.uncompress_file.call_count, 4)

    def call_for(name):
      basis = os.path.join(self.output_dir, name)
      return mock.call(basis + toolchain_util.BZ2_COMPRESSION_SUFFIX, basis)

    # The last profile is not compressed, so no need to uncompress it
    mocks.uncompress_file.assert_has_calls(
        any_order=True, calls=[call_for(n) for n in input_afdo_names[:-1]])

  def testCreateAndUploadMergedAFDOProfileWorksForArm(self):
    prof = self._benchmark_afdo_profile_name(
        major=9999, compression_suffix=False, arch='arm')
    merged_name, mocks = self.runCreateAndUploadMergedAFDOProfileOnce(
        unmerged_name=prof, arch='arm')
    self.assertIsNotNone(merged_name)

    # Note that we always return the *basename*
    self.assertEqual(
        merged_name,
        self._benchmark_afdo_profile_name(major=9999,
                                          merged_suffix=True,
                                          compression_suffix=False,
                                          arch='arm'))

    mocks.run_command.assert_called_once()

    # Note that these should all be in-chroot names.
    expected_ordered_args = ['llvm-profdata', 'merge', '-sample']

    def _afdo_name(major, build=0, patch=0, merged_suffix=False):
      return self._benchmark_afdo_profile_name(
          major=major,
          build=build,
          patch=patch,
          merged_suffix=merged_suffix,
          compression_suffix=False,
          arch='arm')

    input_afdo_names = [
        _afdo_name(major=10, build=13),
        _afdo_name(major=10, build=13, patch=1),
        _afdo_name(major=11, build=14),
        _afdo_name(major=11, build=15),
        _afdo_name(major=9999),
    ]

    output_afdo_name = _afdo_name(major=9999, merged_suffix=True)
    expected_unordered_args = [
        '-output=' +
        os.path.join(self.output_dir_inchroot, 'raw-' + output_afdo_name)
    ] + [
        '-weighted-input=1,' + os.path.join(self.output_dir_inchroot, n)
        for n in input_afdo_names
    ]

    args = mocks.run_command.call_args[0][0]
    ordered_args = args[:len(expected_ordered_args)]
    self.assertEqual(ordered_args, expected_ordered_args)

    unordered_args = args[len(expected_ordered_args):]
    self.assertCountEqual(unordered_args, expected_unordered_args)
    self.assertEqual(mocks.gs_context.Copy.call_count, 4)
    self.assertEqual(mocks.uncompress_file.call_count, 4)

    def call_for(name):
      basis = os.path.join(self.output_dir, name)
      return mock.call(basis + toolchain_util.BZ2_COMPRESSION_SUFFIX, basis)

    # The last profile is not compressed, so no need to uncompress it
    mocks.uncompress_file.assert_has_calls(
        any_order=True, calls=[call_for(n) for n in input_afdo_names[:-1]])

  def testMergeIsOKIfWeFindFewerProfilesThanWeWant(self):
    merged_name, mocks = self.runCreateAndUploadMergedAFDOProfileOnce(
        recent_to_merge=1000, max_age_days=1000)
    self.assertIsNotNone(merged_name)
    self.assertEqual(mocks.gs_context.Copy.call_count, 9)

  def testNoFilesAfterUnmergedNameAreIncluded(self):
    max_name = self._benchmark_afdo_profile_name(
        major=10, build=11, patch=2, compression_suffix=False)
    # Profiles in this test can be older than 14 days.
    merged_name, mocks = self.runCreateAndUploadMergedAFDOProfileOnce(
        unmerged_name=max_name, max_age_days=21)
    self.assertIsNotNone(merged_name)

    self.assertEqual(
        self._benchmark_afdo_profile_name(
            major=10,
            build=11,
            patch=2,
            merged_suffix=True,
            compression_suffix=False), merged_name)

    def _afdo_name(major, build, patch=0, merged_suffix=False):
      return self._benchmark_afdo_profile_name(
          major=major,
          build=build,
          patch=patch,
          merged_suffix=merged_suffix,
          compression_suffix=False)

    # Note that these should all be in-chroot names.
    expected_ordered_args = ['llvm-profdata', 'merge', '-sample']
    expected_unordered_args = [
        '-output=' + os.path.join(
            self.output_dir_inchroot, 'raw-' +
            _afdo_name(major=10, build=11, patch=2, merged_suffix=True)),
    ] + [
        '-weighted-input=1,' + os.path.join(self.output_dir_inchroot, s)
        for s in [
            _afdo_name(major=10, build=9),
            _afdo_name(major=10, build=10),
            _afdo_name(major=10, build=11),
            _afdo_name(major=10, build=11, patch=2),
        ]
    ]

    args = mocks.run_command.call_args[0][0]
    ordered_args = args[:len(expected_ordered_args)]
    self.assertEqual(ordered_args, expected_ordered_args)

    unordered_args = args[len(expected_ordered_args):]
    self.assertCountEqual(unordered_args, expected_unordered_args)

    self.assertEqual(mocks.gs_context.Copy.call_count, 3)
    self.assertEqual(mocks.uncompress_file.call_count, 3)

  def testMergeDoesntHappenIfNoProfilesAreMerged(self):
    runs = [
        self.runCreateAndUploadMergedAFDOProfileOnce(recent_to_merge=1),
        self.runCreateAndUploadMergedAFDOProfileOnce(max_age_days=0),
    ]

    for merged_name, mocks in runs:
      self.assertIsNone(merged_name)
      self.gs_context.Copy.assert_not_called()
      mocks.run_command.assert_not_called()
      mocks.uncompress_file.assert_not_called()
      mocks.compress_file.assert_not_called()


class GetUpdatedFilesTest(cros_test_lib.MockTempDirTestCase):
  """Test functions in class GetUpdatedFilesForCommit."""

  def setUp(self):
    # Prepare a JSON file containing metadata
    toolchain_util.TOOLCHAIN_UTILS_PATH = self.tempdir
    osutils.SafeMakedirs(os.path.join(self.tempdir, 'afdo_metadata'))
    self.json_file = os.path.join(self.tempdir,
                                  'afdo_metadata/kernel_afdo_4_14.json')
    self.kernel = '4.14'
    self.kernel_name = self.kernel.replace('.', '_')
    self.kernel_key_name = f'chromeos-kernel-{self.kernel_name}'
    self.afdo_sorted_by_freshness = [
        'R78-3865.0-1560000000.afdo', 'R78-3869.38-1562580965.afdo',
        'R78-3866.0-1570000000.afdo'
    ]
    self.afdo_versions = {
        self.kernel_key_name: {
            'name': self.afdo_sorted_by_freshness[1],
        },
    }

    with open(self.json_file, 'w') as f:
      json.dump(self.afdo_versions, f)
    self.artifact_path = os.path.join(
        '/any/path/to/',
        self.afdo_sorted_by_freshness[2] +
        toolchain_util.KERNEL_AFDO_COMPRESSION_SUFFIX
    )
    self.profile_info = {'kernel_version': self.kernel}

  def testUpdateKernelMetadataFailureWithInvalidKernel(self):
    with self.assertRaises(AssertionError) as context:
      toolchain_util.GetUpdatedFilesHandler._UpdateKernelMetadata('3.8', None)
    self.assertIn('does not exist', str(context.exception))

  def testUpdateKernelMetadataFailureWithOlderProfile(self):
    with self.assertRaises(AssertionError) as context:
      toolchain_util.GetUpdatedFilesHandler._UpdateKernelMetadata(
          self.kernel, self.afdo_sorted_by_freshness[0])
    self.assertIn('is not newer than', str(context.exception))

  def testUpdateKernelMetadataPass(self):
    toolchain_util.GetUpdatedFilesHandler._UpdateKernelMetadata(
        self.kernel, self.afdo_sorted_by_freshness[2])
    # Check changes in JSON file
    new_afdo_versions = json.loads(osutils.ReadFile(self.json_file))
    self.assertEqual(len(self.afdo_versions), len(new_afdo_versions))
    self.assertEqual(new_afdo_versions[self.kernel_key_name]['name'],
                     self.afdo_sorted_by_freshness[2])
    for k in self.afdo_versions:
      # Make sure other fields are not changed
      if k != self.kernel_key_name:
        self.assertEqual(self.afdo_versions[k], new_afdo_versions[k])

  def testUpdateKernelProfileMetadata(self):
    ret_files, ret_commit = toolchain_util.GetUpdatedFiles(
        'VerifiedKernelCwpAfdoFile', self.artifact_path, self.profile_info)
    file_to_update = os.path.join(self.tempdir, 'afdo_metadata',
                                  f'kernel_afdo_{self.kernel_name}.json')
    self.assertEqual(ret_files, [file_to_update])
    self.assertIn('Publish new kernel profiles', ret_commit)
    self.assertIn(f'Update 4.14 to {self.afdo_sorted_by_freshness[2]}',
                  ret_commit)

  def testUpdateFailWithOtherTypes(self):
    with self.assertRaises(
        toolchain_util.GetUpdatedFilesForCommitError) as context:
      toolchain_util.GetUpdatedFiles('OtherType', '', '')
    self.assertIn('has no handler in GetUpdatedFiles', str(context.exception))


class GenerateChromeOrderfileTest(cros_test_lib.MockTempDirTestCase):
  """Test GenerateChromeOrderfile class."""

  # pylint: disable=protected-access
  def setUp(self):
    self.board = 'board'
    self.out_dir = os.path.join(self.tempdir, 'outdir')
    osutils.SafeMakedirs(self.out_dir)
    self.chroot_dir = os.path.join(self.tempdir, 'chroot')
    self.working_dir = os.path.join(self.chroot_dir, 'tmp')
    osutils.SafeMakedirs(self.working_dir)
    self.working_dir_inchroot = '/tmp'
    self.chroot_args = []
    self.orderfile_name = 'chromeos-chrome-orderfile-1.0'
    self.PatchObject(
        toolchain_util, '_GetOrderfileName', return_value=self.orderfile_name)
    self.test_obj = toolchain_util.GenerateChromeOrderfile(
        self.board, self.out_dir, '/path/to/chrome_root', self.chroot_dir,
        self.chroot_args)

  def testCheckArgumentsFail(self):
    """Test arguments checking fails without files existing."""
    with self.assertRaises(
        toolchain_util.GenerateChromeOrderfileError) as context:
      self.test_obj._CheckArguments()

    self.assertIn('Chrome binary does not exist at', str(context.exception))

  def testGenerateChromeNM(self):
    """Test generating chrome NM is handled correctly."""
    chrome_binary = self.test_obj.CHROME_BINARY_PATH.replace(
        '${BOARD}', self.board)
    cmd = ['llvm-nm', '-n', chrome_binary]
    output = os.path.join(self.working_dir, self.orderfile_name + '.nm')
    self.test_obj.tempdir = self.tempdir
    self.PatchObject(cros_build_lib, 'run')
    self.test_obj._GenerateChromeNM()
    cros_build_lib.run.assert_called_with(
        cmd, stdout=output, enter_chroot=True, chroot_args=self.chroot_args)

  def testPostProcessOrderfile(self):
    """Test post-processing orderfile is handled correctly."""
    chrome_nm = os.path.join(self.working_dir_inchroot,
                             self.orderfile_name + '.nm')
    input_orderfile = self.test_obj.INPUT_ORDERFILE_PATH.replace(
        '${BOARD}', self.board)
    output = os.path.join(self.working_dir_inchroot,
                          self.orderfile_name + '.orderfile')
    self.PatchObject(cros_build_lib, 'run')
    self.test_obj._PostProcessOrderfile(chrome_nm)
    cmd = [
        self.test_obj.PROCESS_SCRIPT, '--chrome', chrome_nm, '--input',
        input_orderfile, '--output', output
    ]
    cros_build_lib.run.assert_called_with(
        cmd,
        enter_chroot=True,
        chroot_args=self.chroot_args,
        check=True,
        capture_output=True)

  def testSuccessRun(self):
    """Test the main function is running successfully."""
    # Patch the two functions that generate artifacts from inputs that are
    # non-existent without actually building Chrome
    chrome_nm = os.path.join(self.working_dir, self.orderfile_name + '.nm')
    with open(chrome_nm, 'w') as f:
      print('Write something in the nm file', file=f)
    self.PatchObject(
        toolchain_util.GenerateChromeOrderfile,
        '_GenerateChromeNM',
        return_value=chrome_nm)
    chrome_orderfile = os.path.join(self.working_dir,
                                    self.orderfile_name + '.orderfile')
    with open(chrome_orderfile, 'w') as f:
      print('Write something in the orderfile', file=f)
    self.PatchObject(
        toolchain_util.GenerateChromeOrderfile,
        '_PostProcessOrderfile',
        return_value=chrome_orderfile)

    self.PatchObject(toolchain_util.GenerateChromeOrderfile, '_CheckArguments')

    self.test_obj.Bundle()

    # Make sure the tarballs are inside the output directory
    output_files = os.listdir(self.out_dir)
    self.assertIn(
        self.orderfile_name + '.nm' + toolchain_util.XZ_COMPRESSION_SUFFIX,
        output_files)
    self.assertIn(
        self.orderfile_name + '.orderfile' +
        toolchain_util.XZ_COMPRESSION_SUFFIX, output_files)
