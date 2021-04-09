# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Artifacts service tests."""

from __future__ import print_function

from operator import attrgetter

import json
import os
import shutil

import mock

from chromite.lib import autotest_util
from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.lib import portage_util
from chromite.lib import sysroot_lib
from chromite.lib import toolchain_util
from chromite.lib.paygen import partition_lib
from chromite.lib.paygen import paygen_payload_lib
from chromite.lib.paygen import paygen_stateful_payload_lib
from chromite.service import artifacts


class BundleAutotestFilesTest(cros_test_lib.MockTempDirTestCase):
  """Test the Bundle Autotest Files function."""

  def setUp(self):
    self.output_dir = os.path.join(self.tempdir, 'output_dir')
    self.archive_dir = os.path.join(self.tempdir, 'archive_base_dir')

    sysroot_path = os.path.join(self.tempdir, 'sysroot')
    self.chroot = chroot_lib.Chroot(self.tempdir)
    self.sysroot = sysroot_lib.Sysroot('sysroot')
    self.sysroot_dne = sysroot_lib.Sysroot('sysroot_DNE')

    # Make sure we have the valid paths.
    osutils.SafeMakedirs(self.output_dir)
    osutils.SafeMakedirs(sysroot_path)

  def testInvalidOutputDirectory(self):
    """Test invalid output directory."""
    with self.assertRaises(AssertionError):
      artifacts.BundleAutotestFiles(self.chroot, self.sysroot, None)

  def testInvalidSysroot(self):
    """Test sysroot that does not exist."""
    with self.assertRaises(AssertionError):
      artifacts.BundleAutotestFiles(self.chroot, self.sysroot_dne,
                                    self.output_dir)

  def testArchiveDirectoryDoesNotExist(self):
    """Test archive directory that does not exist causes error."""
    self.assertEqual(
        artifacts.BundleAutotestFiles(self.chroot, self.sysroot,
                                      self.output_dir), {})

  def testSuccess(self):
    """Test a successful call handling."""
    ab_path = os.path.join(self.tempdir, self.sysroot.path,
                           constants.AUTOTEST_BUILD_PATH)
    osutils.SafeMakedirs(ab_path)

    # Makes all of the individual calls to build out each of the tarballs work
    # nicely with a single patch.
    self.PatchObject(autotest_util.AutotestTarballBuilder, '_BuildTarball',
                     side_effect=lambda _, path, **kwargs: osutils.Touch(path))

    result = artifacts.BundleAutotestFiles(self.chroot, self.sysroot,
                                           self.output_dir)

    for archive in result.values():
      self.assertStartsWith(archive, self.output_dir)
      self.assertExists(archive)


class ArchiveChromeEbuildEnvTest(cros_test_lib.MockTempDirTestCase):
  """ArchiveChromeEbuildEnv tests."""

  def setUp(self):
    # Create the chroot and sysroot instances.
    self.chroot_path = os.path.join(self.tempdir, 'chroot_dir')
    self.chroot = chroot_lib.Chroot(path=self.chroot_path)
    self.sysroot_path = os.path.join(self.chroot_path, 'sysroot_dir')
    self.sysroot = sysroot_lib.Sysroot(self.sysroot_path)

    # Create the output directory.
    self.output_dir = os.path.join(self.tempdir, 'output_dir')
    osutils.SafeMakedirs(self.output_dir)

    # The sysroot's /var/db/pkg prefix for the chrome package directories.
    var_db_pkg = os.path.join(self.sysroot_path, portage_util.VDB_PATH)
    # Create the var/db/pkg dir so we have that much for no-chrome tests.
    osutils.SafeMakedirs(var_db_pkg)

    # Two versions of chrome to test the multiple version checks/handling.
    chrome_v1 = '%s-1.0.0-r1' % constants.CHROME_PN
    chrome_v2 = '%s-2.0.0-r1' % constants.CHROME_PN

    # Build the two chrome version paths.
    chrome_cat_dir = os.path.join(var_db_pkg, constants.CHROME_CN)
    self.chrome_v1_dir = os.path.join(chrome_cat_dir, chrome_v1)
    self.chrome_v2_dir = os.path.join(chrome_cat_dir, chrome_v2)

    # Directory tuple for verifying the result archive contents.
    self.expected_archive_contents = cros_test_lib.Directory('./',
                                                             'environment')

    # Create a environment.bz2 file to put into folders.
    env_file = os.path.join(self.tempdir, 'environment')
    osutils.Touch(env_file)
    cros_build_lib.run(['bzip2', env_file])
    self.env_bz2 = '%s.bz2' % env_file

  def _CreateChromeDir(self, path, populate=True):
    """Setup a chrome package directory.

    Args:
      path (str): The full chrome package path.
      populate (bool): Whether to include the environment bz2.
    """
    osutils.SafeMakedirs(path)
    if populate:
      shutil.copy(self.env_bz2, path)

  def testSingleChromeVersion(self):
    """Test a successful single-version run."""
    self._CreateChromeDir(self.chrome_v1_dir)

    created = artifacts.ArchiveChromeEbuildEnv(self.sysroot, self.output_dir)

    self.assertStartsWith(created, self.output_dir)
    cros_test_lib.VerifyTarball(created, self.expected_archive_contents)

  def testMultipleChromeVersions(self):
    """Test a successful multiple version run."""
    # Create both directories, but don't populate the v1 dir so it'll hit an
    # error if the wrong one is used.
    self._CreateChromeDir(self.chrome_v1_dir, populate=False)
    self._CreateChromeDir(self.chrome_v2_dir)

    created = artifacts.ArchiveChromeEbuildEnv(self.sysroot, self.output_dir)

    self.assertStartsWith(created, self.output_dir)
    cros_test_lib.VerifyTarball(created, self.expected_archive_contents)

  def testNoChrome(self):
    """Test no version of chrome present."""
    with self.assertRaises(artifacts.NoFilesError):
      artifacts.ArchiveChromeEbuildEnv(self.sysroot, self.output_dir)


class ArchiveImagesTest(cros_test_lib.TempDirTestCase):
  """ArchiveImages tests."""

  def setUp(self):
    self.image_dir = os.path.join(self.tempdir, 'images')
    osutils.SafeMakedirs(self.image_dir)
    self.output_dir = os.path.join(self.tempdir, 'output')
    osutils.SafeMakedirs(self.output_dir)

    self.images = []
    for img in artifacts.IMAGE_TARS.keys():
      full_path = os.path.join(self.image_dir, img)
      self.images.append(full_path)
      osutils.Touch(full_path)

    osutils.Touch(os.path.join(self.image_dir, 'irrelevant_image.bin'))
    osutils.Touch(os.path.join(self.image_dir, 'foo.txt'))
    osutils.Touch(os.path.join(self.image_dir, 'bar'))

  def testNoImages(self):
    """Test an empty directory handling."""
    artifacts.ArchiveImages(self.tempdir, self.output_dir)
    self.assertFalse(os.listdir(self.output_dir))

  def testAllImages(self):
    """Test each image gets picked up."""
    created = artifacts.ArchiveImages(self.image_dir, self.output_dir)
    self.assertCountEqual(list(artifacts.IMAGE_TARS.values()), created)


class CreateChromeRootTest(cros_test_lib.RunCommandTempDirTestCase):
  """CreateChromeRoot tests."""

  def setUp(self):
    # Create the build target.
    self.build_target = build_target_lib.BuildTarget('board')

    # Create the chroot.
    self.chroot_dir = os.path.join(self.tempdir, 'chroot')
    self.chroot_tmp = os.path.join(self.chroot_dir, 'tmp')
    osutils.SafeMakedirs(self.chroot_tmp)
    self.chroot = chroot_lib.Chroot(path=self.chroot_dir)

    # Create the output directory.
    self.output_dir = os.path.join(self.tempdir, 'output_dir')
    osutils.SafeMakedirs(self.output_dir)

  def testRunCommandError(self):
    """Test handling when the run command call is not successful."""
    self.rc.SetDefaultCmdResult(
        side_effect=cros_build_lib.RunCommandError('Error'))

    with self.assertRaises(artifacts.CrosGenerateSysrootError):
      artifacts.CreateChromeRoot(self.chroot, self.build_target,
                                 self.output_dir)

  def testSuccess(self):
    """Test success case."""
    # Separate tempdir for the method itself.
    call_tempdir = os.path.join(self.chroot_tmp, 'cgs_call_tempdir')
    osutils.SafeMakedirs(call_tempdir)
    self.PatchObject(osutils.TempDir, '__enter__', return_value=call_tempdir)

    # Set up files in the tempdir since the command isn't being called to
    # generate anything for it to handle.
    files = ['file1', 'file2', 'file3']
    expected_files = [os.path.join(self.output_dir, f) for f in files]
    for f in files:
      osutils.Touch(os.path.join(call_tempdir, f))

    created = artifacts.CreateChromeRoot(self.chroot, self.build_target,
                                         self.output_dir)

    # Just test the command itself and the parameter-based args.
    self.assertCommandContains(['cros_generate_sysroot',
                                '--board', self.build_target.name])
    # Make sure we
    self.assertCountEqual(expected_files, created)
    for f in created:
      self.assertExists(f)


class BundleEBuildLogsTarballTest(cros_test_lib.TempDirTestCase):
  """BundleEBuildLogsTarball tests."""

  def testBundleEBuildLogsTarball(self):
    """Verifies that the correct EBuild tar files are bundled."""
    board = 'samus'
    # Create chroot object and sysroot object
    chroot_path = os.path.join(self.tempdir, 'chroot')
    chroot = chroot_lib.Chroot(path=chroot_path)
    sysroot_path = os.path.join('build', board)
    sysroot = sysroot_lib.Sysroot(sysroot_path)

    # Create parent dir for logs
    log_parent_dir = os.path.join(chroot.path, 'build')

    # Names of log files typically found in a build directory.
    log_files = (
        '',
        'x11-libs:libdrm-2.4.81-r24:20170816-175008.log',
        'x11-libs:libpciaccess-0.12.902-r2:20170816-174849.log',
        'x11-libs:libva-1.7.1-r2:20170816-175019.log',
        'x11-libs:libva-intel-driver-1.7.1-r4:20170816-175029.log',
        'x11-libs:libxkbcommon-0.4.3-r2:20170816-174908.log',
        'x11-libs:pango-1.32.5-r1:20170816-174954.log',
        'x11-libs:pixman-0.32.4:20170816-174832.log',
        'x11-misc:xkeyboard-config-2.15-r3:20170816-174908.log',
        'x11-proto:kbproto-1.0.5:20170816-174849.log',
        'x11-proto:xproto-7.0.31:20170816-174849.log',
    )
    tarred_files = [os.path.join('logs', x) for x in log_files]
    log_files_root = os.path.join(log_parent_dir,
                                  '%s/tmp/portage/logs' % board)
    # Generate a representative set of log files produced by a typical build.
    cros_test_lib.CreateOnDiskHierarchy(log_files_root, log_files)

    archive_dir = self.tempdir
    tarball = artifacts.BundleEBuildLogsTarball(chroot, sysroot, archive_dir)
    self.assertEqual('ebuild_logs.tar.xz', tarball)

    # Verify the tarball contents.
    tarball_fullpath = os.path.join(self.tempdir, tarball)
    cros_test_lib.VerifyTarball(tarball_fullpath, tarred_files)


class BundleChromeOSConfigTest(cros_test_lib.TempDirTestCase):
  """BundleChromeOSConfig tests."""

  def setUp(self):
    self.board = 'samus'

    # Create chroot object and sysroot object
    chroot_path = os.path.join(self.tempdir, 'chroot')
    self.chroot = chroot_lib.Chroot(path=chroot_path)
    sysroot_path = os.path.join('build', self.board)
    self.sysroot = sysroot_lib.Sysroot(sysroot_path)

    self.archive_dir = self.tempdir

  def testBundleChromeOSConfig(self):
    """Verifies that the correct ChromeOS config file is bundled."""
    # Create parent dir for ChromeOS Config output.
    config_parent_dir = os.path.join(self.chroot.path, 'build')

    # Names of ChromeOS Config files typically found in a build directory.
    config_files = ('config.json',
                    cros_test_lib.Directory('yaml', [
                        'config.c', 'config.yaml', 'ec_config.c', 'ec_config.h',
                        'model.yaml', 'private-model.yaml'
                    ]))
    config_files_root = os.path.join(
        config_parent_dir, '%s/usr/share/chromeos-config' % self.board)
    # Generate a representative set of config files produced by a typical build.
    cros_test_lib.CreateOnDiskHierarchy(config_files_root, config_files)

    # Write a payload to the config.yaml file.
    test_config_payload = {
        'chromeos': {
            'configs': [{
                'identity': {
                    'platform-name': 'Samus'
                }
            }]
        }
    }
    with open(os.path.join(config_files_root, 'yaml', 'config.yaml'), 'w') as f:
      json.dump(test_config_payload, f)

    config_filename = artifacts.BundleChromeOSConfig(self.chroot, self.sysroot,
                                                     self.archive_dir)
    self.assertEqual('config.yaml', config_filename)

    with open(os.path.join(self.archive_dir, config_filename), 'r') as f:
      self.assertEqual(test_config_payload, json.load(f))

  def testNoChromeOSConfigFound(self):
    """Verifies that None is returned when no ChromeOS config file is found."""
    self.assertIsNone(
        artifacts.BundleChromeOSConfig(self.chroot, self.sysroot,
                                       self.archive_dir))


class BundleVmFilesTest(cros_test_lib.TempDirTestCase):
  """BundleVmFiles tests."""

  def testBundleVmFiles(self):
    """Verifies that the correct files are bundled"""
    # Create the chroot instance.
    chroot_path = os.path.join(self.tempdir, 'chroot')
    chroot = chroot_lib.Chroot(path=chroot_path)

    # Create the test_results_dir
    test_results_dir = 'test/results'

    # Create a set of files where some should get bundled up as VM files.
    # Add a suffix (123) to one of the files matching the VM pattern prefix.
    vm_files = ('file1.txt',
                'file2.txt',
                'chromiumos_qemu_disk.bin' + '123',
                'chromiumos_qemu_mem.bin'
               )

    target_test_dir = os.path.join(chroot_path, test_results_dir)
    cros_test_lib.CreateOnDiskHierarchy(target_test_dir, vm_files)

    # Create the output directory.
    output_dir = os.path.join(self.tempdir, 'output_dir')
    osutils.SafeMakedirs(output_dir)

    archives = artifacts.BundleVmFiles(
        chroot, test_results_dir, output_dir)
    expected_archive_files = [
        output_dir + '/chromiumos_qemu_disk.bin' + '123.tar',
        output_dir + '/chromiumos_qemu_mem.bin.tar']
    self.assertCountEqual(archives, expected_archive_files)


class BuildFirmwareArchiveTest(cros_test_lib.TempDirTestCase):
  """BuildFirmwareArchive tests."""

  def testBuildFirmwareArchive(self):
    """Verifies that firmware archiver includes proper files"""
    # Assorted set of file names, some of which are supposed to be included in
    # the archive.
    fw_files = (
        'dts/emeraldlake2.dts',
        'image-link.rw.bin',
        'nv_image-link.bin',
        'pci8086,0166.rom',
        'seabios.cbfs',
        'u-boot.elf',
        'u-boot_netboot.bin',
        'updater-link.rw.sh',
        'x86-memtest',
    )

    board = 'link'
    # fw_test_root = os.path.join(self.tempdir, os.path.basename(__file__))
    fw_test_root = self.tempdir
    fw_files_root = os.path.join(fw_test_root,
                                 'chroot/build/%s/firmware' % board)
    # Generate a representative set of files produced by a typical build.
    cros_test_lib.CreateOnDiskHierarchy(fw_files_root, fw_files)

    # Create the chroot and sysroot instances.
    chroot_path = os.path.join(self.tempdir, 'chroot')
    chroot = chroot_lib.Chroot(path=chroot_path)
    sysroot = sysroot_lib.Sysroot('/build/link')

    # Create an archive from the simulated firmware directory
    tarball = os.path.join(
        fw_test_root,
        artifacts.BuildFirmwareArchive(chroot, sysroot, fw_test_root))

    # Verify the tarball contents.
    cros_test_lib.VerifyTarball(tarball, fw_files)

class BundleFpmcuUnittestsTest(cros_test_lib.TempDirTestCase):
  """BundleFpmcuUnittests tests."""

  def testBundleFpmcuUnittests(self):
    """Verifies that the resulting tarball includes proper files"""
    unittest_files = (
        'bloonchipper/test_rsa.bin',
        'dartmonkey/test_utils.bin',
    )

    board = 'hatch'
    unittest_files_root = os.path.join(
        self.tempdir,
        'chroot/build/%s/firmware/chromeos-fpmcu-unittests' % board)
    cros_test_lib.CreateOnDiskHierarchy(unittest_files_root, unittest_files)

    chroot_path = os.path.join(self.tempdir, 'chroot')
    chroot = chroot_lib.Chroot(path=chroot_path)
    sysroot = sysroot_lib.Sysroot('/build/%s' % board)

    tarball = os.path.join(
        self.tempdir,
        artifacts.BundleFpmcuUnittests(chroot, sysroot, self.tempdir))
    cros_test_lib.VerifyTarball(
        tarball,
        unittest_files + ('bloonchipper/', 'dartmonkey/'))

class BundleAFDOGenerationArtifacts(cros_test_lib.MockTempDirTestCase):
  """BundleAFDOGenerationArtifacts tests."""

  def setUp(self):
    # Create the build target.
    self.build_target = build_target_lib.BuildTarget('board')

    # Create the chroot.
    self.chroot_dir = os.path.join(self.tempdir, 'chroot')
    self.chroot_tmp = os.path.join(self.chroot_dir, 'tmp')
    osutils.SafeMakedirs(self.chroot_tmp)
    self.chroot = chroot_lib.Chroot(path=self.chroot_dir)

    # Create the output directory.
    self.output_dir = os.path.join(self.tempdir, 'output_dir')
    osutils.SafeMakedirs(self.output_dir)

    self.chrome_root = os.path.join(self.tempdir, 'chrome_root')

  def testRunSuccess(self):
    """Generic function for testing success cases for different types."""

    # Separate tempdir for the method itself.
    call_tempdir = os.path.join(self.chroot_tmp, 'call_tempdir')
    osutils.SafeMakedirs(call_tempdir)
    self.PatchObject(osutils.TempDir, '__enter__', return_value=call_tempdir)

    mock_orderfile_generate = self.PatchObject(
        toolchain_util, 'GenerateChromeOrderfile',
        autospec=True)

    mock_afdo_generate = self.PatchObject(
        toolchain_util, 'GenerateBenchmarkAFDOProfile',
        autospec=True)

    # Test both orderfile and AFDO.
    for is_orderfile in [False, True]:
      # Set up files in the tempdir since the command isn't being called to
      # generate anything for it to handle.
      files = ['artifact1', 'artifact2']
      expected_files = [os.path.join(self.output_dir, f) for f in files]
      for f in files:
        osutils.Touch(os.path.join(call_tempdir, f))

      created = artifacts.BundleAFDOGenerationArtifacts(
          is_orderfile, self.chroot, self.chrome_root,
          self.build_target, self.output_dir)

      # Test right class is called with right arguments
      if is_orderfile:
        mock_orderfile_generate.assert_called_once_with(
            board=self.build_target.name,
            chrome_root=self.chrome_root,
            output_dir=call_tempdir,
            chroot_path=self.chroot.path,
            chroot_args=self.chroot.get_enter_args()
        )
      else:
        mock_afdo_generate.assert_called_once_with(
            board=self.build_target.name,
            output_dir=call_tempdir,
            chroot_path=self.chroot.path,
            chroot_args=self.chroot.get_enter_args(),
        )

      # Make sure we get all the expected files
      self.assertCountEqual(expected_files, created)
      for f in created:
        self.assertExists(f)
        os.remove(f)


class GeneratePayloadsTest(cros_test_lib.MockTempDirTestCase):
  """Test cases for the payload generation functions."""

  def setUp(self):
    self.target_image = os.path.join(
        self.tempdir,
        'link/R37-5952.0.2014_06_12_2302-a1/chromiumos_test_image.bin')
    osutils.Touch(self.target_image, makedirs=True)
    self.sample_dlc_image = os.path.join(
        self.tempdir,
        'link/R37-5952.0.2014_06_12_2302-a1/dlc/sample-dlc/package/dlc.img')
    osutils.Touch(self.sample_dlc_image, makedirs=True)

  def testGenerateFullTestPayloads(self):
    """Verifies correctly generating full payloads."""
    paygen_mock = self.PatchObject(paygen_payload_lib, 'GenerateUpdatePayload')
    artifacts.GenerateTestPayloads(self.target_image, self.tempdir, full=True)
    payload_path = os.path.join(
        self.tempdir,
        'chromeos_R37-5952.0.2014_06_12_2302-a1_link_full_dev.bin')
    paygen_mock.assert_called_once_with(self.target_image, payload_path)

  def testGenerateDeltaTestPayloads(self):
    """Verifies correctly generating delta payloads."""
    paygen_mock = self.PatchObject(paygen_payload_lib, 'GenerateUpdatePayload')
    artifacts.GenerateTestPayloads(self.target_image, self.tempdir, delta=True)
    payload_path = os.path.join(
        self.tempdir,
        'chromeos_R37-5952.0.2014_06_12_2302-a1_R37-'
        '5952.0.2014_06_12_2302-a1_link_delta_dev.bin')
    paygen_mock.assert_called_once_with(self.target_image, payload_path,
                                        src_image=self.target_image)

  def testGenerateFullDummyDlcTestPayloads(self):
    """Verifies correctly generating full payloads for sample-dlc."""
    paygen_mock = self.PatchObject(paygen_payload_lib, 'GenerateUpdatePayload')
    self.PatchObject(portage_util, 'GetBoardUseFlags',
                     return_value=['dlc_test'])
    artifacts.GenerateTestPayloads(self.target_image, self.tempdir, full=True,
                                   dlc=True)

    rootfs_payload = 'chromeos_R37-5952.0.2014_06_12_2302-a1_link_full_dev.bin'
    dlc_payload = ('dlc_sample-dlc_package_R37-5952.0.2014_06_12_2302-a1_link_'
                   'full_dev.bin')
    paygen_mock.assert_has_calls([
        mock.call(self.target_image,
                  os.path.join(self.tempdir, rootfs_payload)),
        mock.call(self.sample_dlc_image,
                  os.path.join(self.tempdir, dlc_payload)),
    ])

  def testGenerateDeltaDummyDlcTestPayloads(self):
    """Verifies correctly generating delta payloads for sample-dlc."""
    paygen_mock = self.PatchObject(paygen_payload_lib, 'GenerateUpdatePayload')
    self.PatchObject(portage_util, 'GetBoardUseFlags',
                     return_value=['dlc_test'])
    artifacts.GenerateTestPayloads(self.target_image, self.tempdir, delta=True,
                                   dlc=True)

    rootfs_payload = ('chromeos_R37-5952.0.2014_06_12_2302-a1_R37-'
                      '5952.0.2014_06_12_2302-a1_link_delta_dev.bin')
    dlc_payload = ('dlc_sample-dlc_package_R37-5952.0.2014_06_12_2302-a1_R37-'
                   '5952.0.2014_06_12_2302-a1_link_delta_dev.bin')
    paygen_mock.assert_has_calls([
        mock.call(self.target_image,
                  os.path.join(self.tempdir, rootfs_payload),
                  src_image=self.target_image),
        mock.call(self.sample_dlc_image,
                  os.path.join(self.tempdir, dlc_payload),
                  src_image=self.sample_dlc_image),
    ])

  def testGenerateStatefulTestPayloads(self):
    """Verifies correctly generating stateful payloads."""
    paygen_mock = self.PatchObject(paygen_stateful_payload_lib,
                                   'GenerateStatefulPayload')
    artifacts.GenerateTestPayloads(self.target_image, self.tempdir,
                                   stateful=True)
    paygen_mock.assert_called_once_with(self.target_image, self.tempdir)

  def testGenerateQuickProvisionPayloads(self):
    """Verifies correct files are created for quick_provision script."""
    extract_kernel_mock = self.PatchObject(partition_lib, 'ExtractKernel')
    extract_root_mock = self.PatchObject(partition_lib, 'ExtractRoot')
    compress_file_mock = self.PatchObject(cros_build_lib, 'CompressFile')

    artifacts.GenerateQuickProvisionPayloads(self.target_image, self.tempdir)

    extract_kernel_mock.assert_called_once_with(
        self.target_image, partial_mock.HasString('kernel.bin'))
    extract_root_mock.assert_called_once_with(
        self.target_image, partial_mock.HasString('rootfs.bin'),
        truncate=False)

    calls = [mock.call(partial_mock.HasString('kernel.bin'),
                       partial_mock.HasString(
                           constants.QUICK_PROVISION_PAYLOAD_KERNEL)),
             mock.call(partial_mock.HasString('rootfs.bin'),
                       partial_mock.HasString(
                           constants.QUICK_PROVISION_PAYLOAD_ROOTFS))]
    compress_file_mock.assert_has_calls(calls)


class GenerateCpeExportTest(cros_test_lib.RunCommandTempDirTestCase):
  """GenerateCpeExport tests."""

  def setUp(self):
    self.sysroot = sysroot_lib.Sysroot('/build/board')
    self.chroot = chroot_lib.Chroot(self.tempdir)

    self.chroot_tempdir = osutils.TempDir(base_dir=self.tempdir)
    self.PatchObject(self.chroot, 'tempdir', return_value=self.chroot_tempdir)

    self.output_dir = os.path.join(self.tempdir, 'output_dir')
    osutils.SafeMakedirs(self.output_dir)

    result_file = artifacts.CPE_RESULT_FILE_TEMPLATE % 'board'
    self.result_file = os.path.join(self.output_dir, result_file)

    warnings_file = artifacts.CPE_WARNINGS_FILE_TEMPLATE % 'board'
    self.warnings_file = os.path.join(self.output_dir, warnings_file)

  def testSuccess(self):
    """Test success handling."""
    # Set up warning output and the file the command would be making.
    report = 'Report.'
    warnings = 'Warnings.'
    self.rc.SetDefaultCmdResult(returncode=0, output=report, error=warnings)

    result = artifacts.GenerateCpeReport(self.chroot, self.sysroot,
                                         self.output_dir)

    expected_cmd = ['cros_extract_deps', '--sysroot', '/build/board',
                    '--format', 'cpe', 'virtual/target-os', '--output-path',
                    self.result_file]
    self.assertCommandCalled(expected_cmd, capture_output=True,
                             chroot_args=['--chroot', mock.ANY],
                             enter_chroot=True)

    self.assertEqual(self.result_file, result.report)
    self.assertEqual(self.warnings_file, result.warnings)
    # We cannot assert that self.result_file exists and check contents since we
    # are mocking  cros_extract_deps, but we verified the args to
    # cros_extract_deps.
    self.assertFileContents(self.warnings_file, warnings)


class BundleGceTarballTest(cros_test_lib.MockTempDirTestCase):
  """BundleGceTarball tests."""

  def setUp(self):
    self.output_dir = os.path.join(self.tempdir, 'output_dir')
    self.image_dir = os.path.join(self.tempdir, 'image_dir')
    osutils.SafeMakedirs(self.output_dir)
    osutils.SafeMakedirs(self.image_dir)

    self.image_file = os.path.join(self.image_dir, constants.TEST_IMAGE_BIN)
    osutils.Touch(self.image_file)

  def testSuccess(self):
    # Prepare tempdir for use by the function as tarball root.
    call_tempdir = os.path.join(self.tempdir, 'call_tempdir')
    osutils.SafeMakedirs(call_tempdir)
    self.PatchObject(osutils.TempDir, '__enter__', return_value=call_tempdir)

    tarball = artifacts.BundleGceTarball(self.output_dir, self.image_dir)

    # Verify location and content of the tarball.
    self.assertEqual(tarball, os.path.join(self.output_dir,
                                           constants.TEST_IMAGE_GCE_TAR))
    cros_test_lib.VerifyTarball(tarball, ('disk.raw',))

    # Verify the symlink points the the test image.
    disk_raw = os.path.join(call_tempdir, 'disk.raw')
    self.assertEqual(os.readlink(disk_raw), self.image_file)


class GatherSymbolFilesTest(cros_test_lib.MockTempDirTestCase):
  """Base class for testing GatherSymbolFiles."""

  SLIM_CONTENT = """
some junk
"""

  FAT_CONTENT = """
STACK CFI 1234
some junk
STACK CFI 1234
"""


  def createSymbolFile(self, filename, content=FAT_CONTENT, size=0):
    """Create a symbol file using content with minimum size."""
    osutils.SafeMakedirs(os.path.dirname(filename))

    # If a file size is given, force that to be the minimum file size. Create
    # a sparse file so large files are practical.
    with open(filename, 'w+b') as f:
      f.truncate(size)
      f.seek(0)
      f.write(content.encode('utf-8'))

  def test_ListOutputOfGatherSymbolFiles(self):
    """Mimic how the controller materializes output of GatherSymbolFiles."""
    # Create directory with some symbol files.
    tar_tmp_dir = os.path.join(self.tempdir, 'tar_tmp')
    output_dir = os.path.join(self.tempdir, 'output')
    input_dir = os.path.join(self.tempdir, 'input')
    osutils.SafeMakedirs(output_dir)
    self.createSymbolFile(os.path.join(input_dir, 'a/b/c/file1.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a/b/c/d/file2.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a/file3.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a/b/c/d/e/file1.sym'))

    # Call artifacts.GatherSymbolFiles to find symbol files under self.tempdir
    # and copy them to output_dir.
    symbol_files = list(artifacts.GatherSymbolFiles(
        tar_tmp_dir, output_dir, [input_dir]))
    self.assertEqual(len(symbol_files), 4)

  def test_GatherSymbolFiles(self):
    """Test that files are found and copied."""
    # Create directory with some symbol files.
    tar_tmp_dir = os.path.join(self.tempdir, 'tar_tmp')
    output_dir = os.path.join(self.tempdir, 'output')
    input_dir = os.path.join(self.tempdir, 'input')
    osutils.SafeMakedirs(output_dir)
    self.createSymbolFile(os.path.join(input_dir, 'a/b/c/file1.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a/b/c/d/file2.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a/file3.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a/b/c/d/e/file1.sym'))

    # Call artifacts.GatherSymbolFiles to find symbol files under self.tempdir
    # and copy them to output_dir.
    symbol_files = list(artifacts.GatherSymbolFiles(
        tar_tmp_dir, output_dir, [input_dir]))

    # Construct the expected symbol files. Note that the SymbolFileTuple
    # field source_file_name is the full path to where a symbol file was found,
    # while relative_path is the relative path (from the search) where
    # it is created in the output directory.
    expected_symbol_files = [
        artifacts.SymbolFileTuple(
            source_file_name=os.path.join(input_dir, 'a/b/c/file1.sym'),
            relative_path='a/b/c/file1.sym'),
        artifacts.SymbolFileTuple(
            source_file_name=os.path.join(input_dir, 'a/b/c/d/file2.sym'),
            relative_path='a/b/c/d/file2.sym'),
        artifacts.SymbolFileTuple(
            source_file_name=os.path.join(input_dir, 'a/file3.sym'),
            relative_path='a/file3.sym'),
        artifacts.SymbolFileTuple(
            source_file_name=os.path.join(input_dir, 'a/b/c/d/e/file1.sym'),
            relative_path='a/b/c/d/e/file1.sym')
    ]

    # Sort symbol_files and expected_output_files by the relative_path
    # attribute.
    symbol_files = sorted(symbol_files, key=attrgetter('relative_path'))
    expected_symbol_files = sorted(expected_symbol_files,
                                   key=attrgetter('relative_path'))
    # Compare the files to the expected files. This verifies the size and
    # contents, and on failure shows the full contents.
    self.assertEqual(symbol_files, expected_symbol_files)

    # Verify that the files in output_dir match the SymbolFile relative_paths.
    files_in_output_dir = self.getFilesWithRelativeDir(output_dir)
    files_in_output_dir.sort()
    symbol_file_relative_paths = [obj.relative_path for obj in symbol_files]
    symbol_file_relative_paths.sort()
    self.assertEqual(files_in_output_dir, symbol_file_relative_paths)

    # Verify that the display_name of each symbol does not contain pathsep.
    symbol_file_relative_paths = [
        os.path.basename(obj.relative_path) for obj in symbol_files
    ]
    for display_name in symbol_file_relative_paths:
      self.assertEqual(-1, display_name.find(os.path.sep))

  def test_GatherSymbolTarFiles(self):
    """Test that symbol files in tar files are extracted."""
    output_dir = os.path.join(self.tempdir, 'output')
    osutils.SafeMakedirs(output_dir)

    # Set up test input directory.
    tarball_dir = os.path.join(self.tempdir, 'some/path')
    files_in_tarball = ['dir1/fileZ.sym', 'dir2/fileY.sym', 'dir2/fileX.sym',
                        'fileA.sym', 'fileB.sym', 'fileC.sym']
    for filename in files_in_tarball:
      self.createSymbolFile(os.path.join(tarball_dir, filename))
    temp_tarball_file_path = os.path.join(self.tempdir, 'symfiles.tar')
    cros_build_lib.CreateTarball(temp_tarball_file_path, tarball_dir)
    # Now that we've created the tarball, remove the .sym files in
    # the tarball dir and move the tarball to that dir.
    for filename in files_in_tarball:
      os.remove(os.path.join(tarball_dir, filename))
    tarball_path = os.path.join(tarball_dir, 'symfiles.tar')
    shutil.move(temp_tarball_file_path, tarball_path)

    # Execute artifacts.GatherSymbolFiles where the path contains the tarball.
    symbol_files = list(artifacts.GatherSymbolFiles(
        tarball_dir, output_dir, [tarball_path]))

    self.assertEqual(len(symbol_files), 6)
    # Verify the symbol_file relative_paths.
    symbol_file_relative_paths = [
        obj.relative_path for obj in symbol_files
    ]
    symbol_file_relative_paths.sort()
    self.assertEqual(symbol_file_relative_paths,
                     ['dir1/fileZ.sym', 'dir2/fileX.sym', 'dir2/fileY.sym',
                      'fileA.sym', 'fileB.sym', 'fileC.sym'])
    # Verify the symbol_file source_file_names.
    symbol_file_source_file_names = [
        obj.source_file_name for obj in symbol_files
    ]
    symbol_file_source_file_names.sort()
    # Note that the expected symbol_file_source_names are the full path to
    # the tarfile followed by the relative path, such as
    # /tmp/chromite.test2ng92vzo/some/path/symfiles.tar/dir1/fileZ.sym
    expected_symbol_file_source_names = [
        os.path.join(tarball_path, 'dir1/fileZ.sym'),
        os.path.join(tarball_path, 'dir2/fileX.sym'),
        os.path.join(tarball_path, 'dir2/fileY.sym'),
        os.path.join(tarball_path, 'fileA.sym'),
        os.path.join(tarball_path, 'fileB.sym'),
        os.path.join(tarball_path, 'fileC.sym')
    ]
    self.assertEqual(symbol_file_source_file_names,
                     expected_symbol_file_source_names)

    # Verify that the files in output_dir match the SymbolFile relative_paths.
    files_in_output_dir = self.getFilesWithRelativeDir(output_dir)
    files_in_output_dir.sort()
    symbol_file_relative_paths = [obj.relative_path for obj in symbol_files]
    symbol_file_relative_paths.sort()
    self.assertEqual(files_in_output_dir, symbol_file_relative_paths)
    # Verify that the display_name of each symbol does not contain pathsep.
    symbol_file_relative_paths = [
        os.path.basename(obj.relative_path) for obj in symbol_files
    ]
    for display_name in symbol_file_relative_paths:
      self.assertEqual(-1, display_name.find(os.path.sep))

  def test_GatherSymbolTarFilesWithNonSymFiles(self):
    """Test that non-symbol files in tar files are not extracted."""
    output_dir = os.path.join(self.tempdir, 'output')
    osutils.SafeMakedirs(output_dir)

    # Set up test input directory.
    tarball_dir = os.path.join(self.tempdir, 'some/path')
    files_in_tarball = ['dir1/fileU.sym', 'dir1/fileU.txt',
                        'fileD.sym', 'fileD.txt']
    for filename in files_in_tarball:
      # we don't care about file contents, so we are using createSymbolFile
      # for files whether they end with .sym or not.
      self.createSymbolFile(os.path.join(tarball_dir, filename))
    temp_tarball_file_path = os.path.join(self.tempdir, 'symfiles.tar')
    cros_build_lib.CreateTarball(temp_tarball_file_path, tarball_dir)
    # Now that we've created the tarball, remove the .sym files in
    # the tarball dir and move the tarball to that dir.
    for filename in files_in_tarball:
      os.remove(os.path.join(tarball_dir, filename))
    tarball_path = os.path.join(tarball_dir, 'symfiles.tar')
    shutil.move(temp_tarball_file_path, tarball_path)

    # Execute artifacts.GatherSymbolFiles where the path contains the tarball.
    symbol_files = list(artifacts.GatherSymbolFiles(
        tarball_dir, output_dir, [tarball_path]))

    # Verify the symbol_file relative_paths only has .sym files.
    symbol_file_relative_paths = [
        obj.relative_path for obj in symbol_files
    ]
    symbol_file_relative_paths.sort()
    self.assertEqual(symbol_file_relative_paths,
                     ['dir1/fileU.sym', 'fileD.sym'])
    for symfile in symbol_file_relative_paths:
      extension = symfile.split('.')[1]
      self.assertEqual(extension, 'sym')

  def test_GatherSymbolFileFullFilePaths(self):
    """Test full filepaths (.sym and .txt) only gather .sym files."""
    tar_tmp_dir = os.path.join(self.tempdir, 'tar_tmp')
    output_dir = os.path.join(self.tempdir, 'output')
    input_dir = os.path.join(self.tempdir, 'input')
    osutils.SafeMakedirs(output_dir)
    # We don't care about contents, so use createSymbolFiles for all files.
    self.createSymbolFile(os.path.join(input_dir, 'a_file.sym'))
    self.createSymbolFile(os.path.join(input_dir, 'a_file.txt'))

    # Call artifacts.GatherSymbolFiles with full paths to files, some of which
    # don't end in .sym, verify that only .sym files get copied to output_dir.
    symbol_files = list(artifacts.GatherSymbolFiles(
        tar_tmp_dir, output_dir,
        [os.path.join(input_dir, 'a_file.sym'),
         os.path.join(input_dir, 'a_file.txt')]))

    # Construct the expected symbol files. Note that the SymbolFileTuple
    # field source_file_name is the full path to where a symbol file was found,
    # while relative_path is the relative path (from the search) where
    # it is created in the output directory.
    expected_symbol_files = [
        artifacts.SymbolFileTuple(
            source_file_name=os.path.join(input_dir, 'a_file.sym'),
            relative_path='a_file.sym')
    ]

    # Compare the files to the expected files. This verifies the size and
    # contents, and on failure shows the full contents.
    self.assertEqual(symbol_files, expected_symbol_files)
    # Verify that only a_file.sym is in the output_dir.
    files_in_output_dir = self.getFilesWithRelativeDir(output_dir)
    self.assertEqual(files_in_output_dir, ['a_file.sym'])

  def test_IsTarball(self):
    """Test IsTarball helper function."""
    self.assertTrue(artifacts.IsTarball('file.tar'))
    self.assertTrue(artifacts.IsTarball('file.tar.bz2'))
    self.assertTrue(artifacts.IsTarball('file.tar.gz'))
    self.assertTrue(artifacts.IsTarball('file.tbz'))
    self.assertTrue(artifacts.IsTarball('file.txz'))
    self.assertFalse(artifacts.IsTarball('file.txt'))
    self.assertFalse(artifacts.IsTarball('file.tart'))
    self.assertFalse(artifacts.IsTarball('file.bz2'))

  def getFilesWithRelativeDir(self, dest_dir):
    """Find all files below dest_dir using dir relative to dest_dir."""
    relative_files = []
    for path, __, files in os.walk(dest_dir):
      for filename in files:
        fullpath = os.path.join(path, filename)
        relpath = os.path.relpath(fullpath, dest_dir)
        relative_files.append(relpath)
    return relative_files


class GenerateBreakpadSymbolsTest(cros_test_lib.MockTempDirTestCase):
  """Base class for testing GenerateBreakpadSymbols."""

  def setUp(self):
    self.chroot_dir = os.path.join(self.tempdir, 'chroot_dir')
    osutils.SafeMakedirs(self.chroot_dir)

  def test_generateBreakpadSymbols(self):
    """Verify that calling the service layer invokes the script as expected."""
    chroot = chroot_lib.Chroot(self.chroot_dir)
    build_target = build_target_lib.BuildTarget('board')
    self.PatchObject(cros_build_lib, 'run')

    # Call the method being tested.
    artifacts.GenerateBreakpadSymbols(chroot, build_target, False)

    cros_build_lib.run.assert_called_with(['cros_generate_breakpad_symbols',
                                           '--board=board',
                                           '--jobs', mock.ANY,
                                           '--exclude-dir=firmware'],
                                          capture_output=True,
                                          enter_chroot=True,
                                          chroot_args=['--chroot', mock.ANY])

  def test_generateBreakpadSymbolsWithDebug(self):
    """Verify that calling with debug invokes the script as expected."""
    chroot = chroot_lib.Chroot(self.chroot_dir)
    build_target = build_target_lib.BuildTarget('board')
    self.PatchObject(cros_build_lib, 'run')

    # Call the method being tested.
    artifacts.GenerateBreakpadSymbols(chroot, build_target, True)

    cros_build_lib.run.assert_called_with(['cros_generate_breakpad_symbols',
                                           '--debug',
                                           '--board=board',
                                           '--jobs', mock.ANY,
                                           '--exclude-dir=firmware'],
                                          capture_output=True,
                                          enter_chroot=True,
                                          chroot_args=['--chroot', mock.ANY])
