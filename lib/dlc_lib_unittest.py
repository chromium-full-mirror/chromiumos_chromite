# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for dlc_lib."""

import itertools
import json
import os
import string
from unittest import mock

import pytest

from chromite.lib import cros_build_lib
from chromite.lib import cros_test_lib
from chromite.lib import dlc_allowlist
from chromite.lib import dlc_lib
from chromite.lib import osutils
from chromite.lib import partial_mock
from chromite.scripts import cros_set_lsb_release


_PRE_ALLOCATED_BLOCKS = 100
_VERSION = "1.0"
_ID = "id"
_ID_FOO = "id-foo"
_PACKAGE = "package"
_NAME = "name"
_DESCRIPTION = "description"
_BOARD = "test_board"
_FULLNAME_REV = None
_BLOCK_SIZE = 4096
_IMAGE_SIZE_NEARING_RATIO = 1.05
_IMAGE_SIZE_GROWTH_RATIO = 1.2
_DLC_LOADPIN_FILE_HEADER = "# LOADPIN_TRUSTED_VERITY_ROOT_DIGESTS"

# pylint: disable=protected-access


class DlcArtifactsTest(cros_test_lib.TempDirTestCase):
    """Test dlc_lib DlcArtifacts."""

    def testInit(self) -> None:
        """Test init and attributes are as expected."""
        image_path = os.path.join(self.tempdir, dlc_lib.DLC_IMAGE)
        osutils.WriteFile(image_path, "0")
        art = dlc_lib.DlcArtifacts(
            image=image_path,
            meta="some/meta",
        )
        self.assertEqual(art.image_name, dlc_lib.DLC_IMAGE)
        self.assertEqual(
            art.image_hash,
            "5feceb66ffc86f38d952786c6d696c79c2dbc239dd4e91b46729d73a27fb57e9",
        )

    def testBadNamingInit(self) -> None:
        """Test that DLC image names are as expected."""
        with self.assertRaises(dlc_lib.Error):
            dlc_lib.DlcArtifacts(
                image="not_dlc.img",
                meta="some/meta",
            )


class UtilsTest(cros_test_lib.TempDirTestCase):
    """Tests dlc_lib utility functions."""

    def testHashFile(self) -> None:
        """Test the hash of a simple file."""
        file_path = os.path.join(self.tempdir, "f.txt")
        osutils.WriteFile(file_path, "0123")
        hash_value = dlc_lib.HashFile(file_path)
        self.assertEqual(
            hash_value,
            "1be2e452b46d7a0d9656bbb1f768e824"
            "8eba1b75baed65f5d99eafa948899a6a",
        )

    def testValidateDlcIdentifier(self) -> None:
        """Tests dlc_lib.ValidateDlcIdentifier."""
        dlc_lib.ValidateDlcIdentifier("hello-world")
        dlc_lib.ValidateDlcIdentifier("hello-world2")
        # Keep as previous max ID length.
        dlc_lib.ValidateDlcIdentifier(
            "this-string-has-length-40-exactly-now---"
        )
        # Exactly 80 characters.
        dlc_lib.ValidateDlcIdentifier("a" * 80)

        self.assertRaises(Exception, dlc_lib.ValidateDlcIdentifier, "")
        self.assertRaises(Exception, dlc_lib.ValidateDlcIdentifier, "-")
        self.assertRaises(Exception, dlc_lib.ValidateDlcIdentifier, "-hi")
        self.assertRaises(Exception, dlc_lib.ValidateDlcIdentifier, "hello%")
        self.assertRaises(
            Exception, dlc_lib.ValidateDlcIdentifier, "hello_world"
        )
        self.assertRaises(
            Exception,
            dlc_lib.ValidateDlcIdentifier,
            "a" * 81,
        )


class EbuildParamsTest(cros_test_lib.MockTempDirTestCase):
    """Tests EbuildParams functions."""

    def GetVaryingEbuildParams(self):
        return {
            "dlc_id": f"{_ID}_new",
            "dlc_package": f"{_PACKAGE}_new",
            "fs_type": dlc_lib.EXT4_TYPE,
            "name": f"{_NAME}_new",
            "description": f"{_DESCRIPTION}_new",
            "pre_allocated_blocks": _PRE_ALLOCATED_BLOCKS * 2,
            "powerwash_safe": True,
            "version": f"{_VERSION}_new",
            "preload": True,
            "factory_install": False,
            "loadpin_verity_digest": False,
            "mount_file_required": True,
            "reserved": False,
            "critical_update": False,
            "scaled": True,
            "force_ota": False,
            "use_logical_volume": True,
        }

    def testGetParamsPath(self) -> None:
        """Tests EbuildParams.GetParamsPath"""
        install_root_dir = os.path.join(self.tempdir, "install_root_dir")

        self.assertEqual(
            dlc_lib.EbuildParams.GetParamsPath(
                install_root_dir, _ID, _PACKAGE, False
            ),
            os.path.join(
                install_root_dir,
                dlc_lib.DLC_BUILD_DIR,
                _ID,
                _PACKAGE,
                dlc_lib.EBUILD_PARAMETERS,
            ),
        )
        self.assertEqual(
            dlc_lib.EbuildParams.GetParamsPath(
                install_root_dir, _ID, _PACKAGE, True
            ),
            os.path.join(
                install_root_dir,
                dlc_lib.DLC_BUILD_DIR_SCALED,
                _ID,
                _PACKAGE,
                dlc_lib.EBUILD_PARAMETERS,
            ),
        )

    def CheckParams(
        self,
        ebuild_params,
        dlc_id=_ID,
        dlc_package=_PACKAGE,
        fs_type=dlc_lib.SQUASHFS_TYPE,
        name=_NAME,
        description=_DESCRIPTION,
        pre_allocated_blocks=_PRE_ALLOCATED_BLOCKS,
        version=_VERSION,
        preload=False,
        factory_install=False,
        loadpin_verity_digest=False,
        mount_file_required=False,
        reserved=False,
        critical_update=False,
        fullnamerev=_FULLNAME_REV,
        scaled=False,
        force_ota=False,
        powerwash_safe=False,
        use_logical_volume=False,
        user_tied=False,
    ) -> None:
        """Tests EbuildParams JSON values"""
        self.assertDictEqual(
            ebuild_params,
            {
                "dlc_id": dlc_id,
                "dlc_package": dlc_package,
                "fs_type": fs_type,
                "pre_allocated_blocks": pre_allocated_blocks,
                "version": version,
                "name": name,
                "description": description,
                "preload": preload,
                "factory_install": factory_install,
                "loadpin_verity_digest": loadpin_verity_digest,
                "mount_file_required": mount_file_required,
                "reserved": reserved,
                "critical_update": critical_update,
                "fullnamerev": fullnamerev,
                "scaled": scaled,
                "force_ota": force_ota,
                "powerwash_safe": powerwash_safe,
                "use_logical_volume": use_logical_volume,
                "user_tied": user_tied,
            },
        )

    def GenerateParams(
        self,
        install_root_dir,
        dlc_id=_ID,
        dlc_package=_PACKAGE,
        fs_type=dlc_lib.SQUASHFS_TYPE,
        name=_NAME,
        description=_DESCRIPTION,
        pre_allocated_blocks=_PRE_ALLOCATED_BLOCKS,
        version=_VERSION,
        preload=False,
        factory_install=False,
        loadpin_verity_digest=False,
        mount_file_required=False,
        reserved=False,
        critical_update=False,
        fullnamerev=_FULLNAME_REV,
        scaled=False,
        force_ota=False,
        powerwash_safe=False,
        use_logical_volume=False,
    ) -> dlc_lib.EbuildParams:
        """Creates and Stores DLC params at install_root_dir"""
        params = dlc_lib.EbuildParams(
            dlc_id=dlc_id,
            dlc_package=dlc_package,
            fs_type=fs_type,
            name=name,
            description=description,
            pre_allocated_blocks=pre_allocated_blocks,
            version=version,
            preload=preload,
            factory_install=factory_install,
            loadpin_verity_digest=loadpin_verity_digest,
            mount_file_required=mount_file_required,
            reserved=reserved,
            critical_update=critical_update,
            fullnamerev=fullnamerev,
            scaled=scaled,
            force_ota=force_ota,
            powerwash_safe=powerwash_safe,
            use_logical_volume=use_logical_volume,
        )
        params.StoreDlcParameters(install_root_dir=install_root_dir, sudo=False)
        return params

    def testGetUriPathMissingId(self) -> None:
        """Tests EbuildParams.GetUriPath missing ID"""
        params = self.GenerateParams(os.path.join(self.tempdir, "build_root"))
        params.dlc_id = None
        with self.assertRaises(Exception):
            params.GetUriPath()
        params.dlc_id = ""
        with self.assertRaises(Exception):
            params.GetUriPath()

    def testGetUriPathMissingPackage(self) -> None:
        """Tests EbuildParams.GetUriPath missing package"""
        params = self.GenerateParams(os.path.join(self.tempdir, "build_root"))
        params.dlc_package = None
        with self.assertRaises(Exception):
            params.GetUriPath()
        params.dlc_package = ""
        with self.assertRaises(Exception):
            params.GetUriPath()

    def testGetUriPathMissingVersion(self) -> None:
        """Tests EbuildParams.GetUriPath missing version"""
        params = self.GenerateParams(os.path.join(self.tempdir, "build_root"))
        params.version = None
        with self.assertRaises(Exception):
            params.GetUriPath()
        params.version = ""
        with self.assertRaises(Exception):
            params.GetUriPath()

    def testGetUriPath(self) -> None:
        """Tests EbuildParams.GetUriPath"""
        params = self.GenerateParams(os.path.join(self.tempdir, "build_root"))
        self.assertEqual(
            params.GetUriPath(),
            os.path.join(
                dlc_lib.GS_LOCALMIRROR_BUCKET,
                dlc_lib.GS_DLC_IMAGES_DIR,
                params.dlc_id,
                params.dlc_package,
                params.version,
            ),
        )

    def testVerifyDlcParametersFactoryInstallable(self) -> None:
        """Tests EbuildParams.VerifyDlcParameters"""
        dlc_allowlist_mock = self.PatchObject(
            dlc_allowlist, "IsFactoryInstallAllowlisted", return_value=True
        )
        params = self.GenerateParams(os.path.join(self.tempdir, "build_root"))
        params.dlc_id = "foo"
        params.factory_install = True
        params.VerifyDlcParameters()
        dlc_allowlist_mock.assert_called_once_with(params.dlc_id)

    def testVerifyDlcParametersNotAllowedToFactoryInstall(self) -> None:
        """Tests EbuildParams.VerifyDlcParameters"""
        dlc_allowlist_mock = self.PatchObject(
            dlc_allowlist, "IsFactoryInstallAllowlisted", return_value=False
        )
        params = self.GenerateParams(os.path.join(self.tempdir, "build_root"))
        params.dlc_id = "foo"
        params.factory_install = True
        with self.assertRaises(Exception):
            params.VerifyDlcParameters()
        dlc_allowlist_mock.assert_called_once_with(params.dlc_id)

    def testStoreDlcParameters(self) -> None:
        """Tests EbuildParams.StoreDlcParameters"""
        sysroot = os.path.join(self.tempdir, "build_root")
        self.GenerateParams(sysroot)
        ebuild_params_path = os.path.join(
            sysroot,
            dlc_lib.DLC_BUILD_DIR,
            _ID,
            _PACKAGE,
            dlc_lib.EBUILD_PARAMETERS,
        )
        self.assertExists(ebuild_params_path)

        with open(ebuild_params_path, "rb") as f:
            self.CheckParams(json.load(f))

    def testStoreVaryingDlcParameters(self) -> None:
        """Tests EbuildParams.StoreDlcParameters with non default values"""
        sysroot = os.path.join(self.tempdir, "build_root")
        params = self.GetVaryingEbuildParams()
        self.GenerateParams(sysroot, **params)
        ebuild_params_path = os.path.join(
            sysroot,
            dlc_lib.DLC_BUILD_DIR_SCALED,
            params["dlc_id"],
            params["dlc_package"],
            dlc_lib.EBUILD_PARAMETERS,
        )
        self.assertExists(ebuild_params_path)

        with open(ebuild_params_path, "rb") as f:
            self.CheckParams(json.load(f), **params)

    def testStorePreAllocatedSizeAsDevSize(self) -> None:
        """Tests EbuildParams.LoadDlcParameters"""
        sysroot = os.path.join(self.tempdir, "build_root")
        self.GenerateParams(
            sysroot, pre_allocated_blocks=dlc_lib.MAGIC_DEV_SIZE
        )
        ebuild_params_path = os.path.join(
            sysroot,
            dlc_lib.DLC_BUILD_DIR,
            _ID,
            _PACKAGE,
            dlc_lib.EBUILD_PARAMETERS,
        )
        self.assertExists(ebuild_params_path)

        with open(ebuild_params_path, "rb") as f:
            self.CheckParams(
                json.load(f), pre_allocated_blocks=dlc_lib.MAGIC_DEV_SIZE
            )

    def testLoadDlcParameters(self) -> None:
        """Tests EbuildParams.LoadDlcParameters"""
        sysroot = os.path.join(self.tempdir, "build_root")
        self.GenerateParams(sysroot)
        ebuild_params_class = dlc_lib.EbuildParams.LoadEbuildParams(
            sysroot,
            _ID,
            _PACKAGE,
            False,
        )
        self.CheckParams(ebuild_params_class.__dict__)

    def testLoadVaryingDlcParameters(self) -> None:
        """Tests EbuildParams.LoadDlcParameters"""
        sysroot = os.path.join(self.tempdir, "build_root")
        params = self.GetVaryingEbuildParams()
        self.GenerateParams(sysroot, **params)
        ebuild_params_class = dlc_lib.EbuildParams.LoadEbuildParams(
            sysroot,
            params["dlc_id"],
            params["dlc_package"],
            params["scaled"],
        )
        self.CheckParams(ebuild_params_class.__dict__, **params)


class DlcMetadataTest(cros_test_lib.TempDirTestCase):
    """Tests DlcMetadata."""

    # Smaller file_size setting to test creating multiple metadata files.
    _FILE_SIZE = 256

    def setUp(self) -> None:
        """Create DLC metadata files for test"""
        self._sysroot = os.path.join(self.tempdir, "build_root")
        self._src_dir = os.path.join(self.tempdir, "src_dir")
        # Create 'dlc-a' to 'dlc-z' source metadata files for testing.
        self._dlc_all = []
        for i in string.ascii_lowercase:
            d_id = f"dlc-{i}"
            self.MakeSrcMetadata(d_id)
            self._dlc_all.append((d_id, self._src_dir))

        with dlc_lib.DlcMetadata(
            metadata_path=self._sysroot,
            max_file_size=self._FILE_SIZE,
        ) as metadata:
            metadata.Create(self._dlc_all)

    def MakeSrcMetadata(self, dlc_id: str, extra: dict = None) -> None:
        """Create source metadata files for test.

        Args:
            dlc_id: The dlc id to be created.
            extra: Add additional manifest fields.
        """
        src_dir = os.path.join(
            self._src_dir, dlc_id, _PACKAGE, dlc_lib.DLC_TMP_META_DIR
        )
        src_manifest = {"description": f"test manifest for {dlc_id}"}
        if extra:
            src_manifest.update(extra)
        src_table = f"test table for {dlc_id}"
        osutils.SafeMakedirs(src_dir)
        with open(
            os.path.join(src_dir, dlc_lib.IMAGELOADER_JSON),
            mode="w",
            encoding="utf-8",
        ) as f:
            json.dump(src_manifest, f)
        osutils.WriteFile(
            path=os.path.join(src_dir, dlc_lib.DLC_VERITY_TABLE),
            content=src_table,
        )

    def VerifyMetadata(self) -> None:
        """Verifies metadata.

        Load and compare to the source metadata file content.
        """
        i = 0
        metadata_reader = dlc_lib.DlcMetadata(metadata_path=self._sysroot)
        for f in sorted(metadata_reader.ListFiles()):
            parsed = metadata_reader.LoadDestMetadata(f)
            for d_id, metadata in sorted(parsed.items()):
                self.assertEqual(d_id, self._dlc_all[i][0])
                src_dir = os.path.join(
                    self._src_dir, d_id, _PACKAGE, dlc_lib.DLC_TMP_META_DIR
                )
                src_manifest = osutils.ReadFile(
                    os.path.join(src_dir, dlc_lib.IMAGELOADER_JSON)
                )
                src_table = osutils.ReadFile(
                    os.path.join(src_dir, dlc_lib.DLC_VERITY_TABLE)
                )
                dest_manifest = json.dumps(metadata["manifest"])
                dest_table = metadata["table"]
                self.assertEqual(src_manifest, dest_manifest)
                self.assertEqual(src_table, dest_table)
                i += 1

    def testCreateDlcMetadata(self) -> None:
        """Tests creating metadata, and verifies the generated files"""
        self.VerifyMetadata()

    def testAddDlcMetadata(self) -> None:
        """Tests adding a metadata"""
        dlc_info = ("dlc-nn", self._src_dir)
        self.MakeSrcMetadata(dlc_info[0])
        self._dlc_all.append(dlc_info)
        self._dlc_all.sort()
        with dlc_lib.DlcMetadata(
            metadata_path=self._sysroot, max_file_size=self._FILE_SIZE
        ) as metadata:
            metadata.Create(self._dlc_all)
        self.VerifyMetadata()

    def testModifyDlcMetadata(self) -> None:
        """Tests modifying a metadata, and verifies it"""
        dlc_info = ("dlc-n", self._src_dir)
        self.MakeSrcMetadata(dlc_info[0], extra={"modified": True})
        with dlc_lib.DlcMetadata(
            metadata_path=self._sysroot, max_file_size=self._FILE_SIZE
        ) as metadata:
            metadata.Create(self._dlc_all)
        self.VerifyMetadata()

    def testRemoveDlcMetadata(self) -> None:
        """Tests removing a metadata, and verifies it"""
        dlc_info = ("dlc-n", self._src_dir)
        self._dlc_all.remove(dlc_info)
        osutils.RmDir(os.path.join(self._src_dir, dlc_info[0]))
        with dlc_lib.DlcMetadata(
            metadata_path=self._sysroot, max_file_size=self._FILE_SIZE
        ) as metadata:
            metadata.Create(self._dlc_all)
        self.VerifyMetadata()


class DlcGeneratorTest(
    cros_test_lib.LoggingTestCase, cros_test_lib.RunCommandTempDirTestCase
):
    """Tests DlcGenerator."""

    def setUp(self) -> None:
        self.ExpectRootOwnedFiles()

    def GetDlcGenerator(
        self,
        fs_type=dlc_lib.SQUASHFS_TYPE,
        pre_allocated_blocks=_PRE_ALLOCATED_BLOCKS,
    ):
        """Factory method for a DcGenerator object"""
        src_dir = os.path.join(self.tempdir, "src")
        osutils.SafeMakedirs(src_dir)

        sysroot = os.path.join(self.tempdir, "build_root")
        osutils.WriteFile(
            os.path.join(sysroot, dlc_lib.LSB_RELEASE),
            "%s=%s\n" % (cros_set_lsb_release.LSB_KEY_APPID_RELEASE, "foo"),
            makedirs=True,
        )
        ue_conf = os.path.join(sysroot, "etc", "update_engine.conf")
        osutils.WriteFile(ue_conf, "foo-content", makedirs=True)

        params = dlc_lib.EbuildParams(
            dlc_id=_ID,
            dlc_package=_PACKAGE,
            fs_type=fs_type,
            name=_NAME,
            description=_DESCRIPTION,
            pre_allocated_blocks=pre_allocated_blocks,
            version=_VERSION,
            preload=False,
            factory_install=False,
            mount_file_required=False,
            reserved=False,
            critical_update=False,
            fullnamerev=_FULLNAME_REV,
        )
        return dlc_lib.DlcGenerator(
            ebuild_params=params, src_dir=src_dir, sysroot=sysroot, board=_BOARD
        )

    def testSquashOwnerships(self) -> None:
        """Test dlc_lib.SquashOwnershipsTest"""
        self.GetDlcGenerator().SquashOwnerships(self.tempdir)
        self.assertCommandContains(["chown", "-R", "0:0"])
        self.assertCommandContains(["find"])

    def testCreateExt2Image(self) -> None:
        """Test CreateExtImage to create ext2 DLC."""
        mount_mock = self.PatchObject(
            osutils, "MountDirContext", side_effect=osutils.MountDirContext
        )
        umount_mock = self.PatchObject(osutils, "UmountDir")

        self.GetDlcGenerator().CreateExtImage(dlc_lib.EXT2_TYPE)
        self.assertCommandContains(["/sbin/mkfs.ext2", "-b", "4096"])
        self.assertCommandContains(["/sbin/e2fsck", "-y", "-f"])
        self.assertCommandContains(["/sbin/resize2fs", "-M"])
        self.assertCommandContains(
            [
                "cp",
                "-dR",
                partial_mock.HasString("src/."),
                partial_mock.HasString("root"),
            ]
        )
        mount_mock.assert_called_once_with(
            mock.ANY,
            partial_mock.HasString("mount_point"),
            fs_type=dlc_lib.EXT2_TYPE,
            mount_opts=("loop", "rw"),
        )
        umount_mock.assert_called_once_with(
            partial_mock.HasString("mount_point")
        )

    def testCreateExt4Image(self) -> None:
        """Test CreateExtImage to create ext4 DLC."""
        mount_mock = self.PatchObject(
            osutils, "MountDirContext", side_effect=osutils.MountDirContext
        )
        umount_mock = self.PatchObject(osutils, "UmountDir")

        self.GetDlcGenerator().CreateExtImage(dlc_lib.EXT4_TYPE)
        self.assertCommandContains(
            ["/sbin/mkfs.ext4", "-b", "4096", "-O", "^has_journal"]
        )
        self.assertCommandContains(["/sbin/e2fsck", "-y", "-f"])
        self.assertCommandContains(["/sbin/resize2fs", "-M"])
        self.assertCommandContains(
            [
                "cp",
                "-dR",
                partial_mock.HasString("src/."),
                partial_mock.HasString("root"),
            ]
        )
        mount_mock.assert_called_once_with(
            mock.ANY,
            partial_mock.HasString("mount_point"),
            fs_type=dlc_lib.EXT4_TYPE,
            mount_opts=("loop", "rw"),
        )
        umount_mock.assert_called_once_with(
            partial_mock.HasString("mount_point")
        )

    def testCreateSquashfsImage(self) -> None:
        """Verify creating squashfs commands are run with correct parameters."""
        self.PatchObject(os.path, "getsize", return_value=(_BLOCK_SIZE * 2))
        copy_dir_mock = self.PatchObject(osutils, "CopyDirContents")

        self.GetDlcGenerator().CreateSquashfsImage()
        self.assertCommandContains(
            [
                "mksquashfs",
                "-4k-align",
                "-noappend",
                "-comp",
                dlc_lib.ZSTD_COMP_NAME,
                dlc_lib.ZSTD_COMP_LEVEL_OPT,
                dlc_lib.ZSTD_MAX_COMP_LEVEL,
            ]
        )
        self.assertCommandContains(
            [
                "unsquashfs",
                "-d",
            ]
        )
        copy_dir_mock.assert_called_once_with(
            partial_mock.HasString("src"),
            partial_mock.HasString("root"),
            symlinks=True,
        )

    def testCreateSquashfsImagePageAlignment(self) -> None:
        """Test that creating squashfs commands are run with page alignment."""
        self.PatchObject(os.path, "getsize", return_value=(_BLOCK_SIZE * 1))
        truncate_mock = self.PatchObject(os, "truncate")
        copy_dir_mock = self.PatchObject(osutils, "CopyDirContents")

        self.GetDlcGenerator().CreateSquashfsImage()
        self.assertCommandContains(
            [
                "mksquashfs",
                "-4k-align",
                "-noappend",
                "-comp",
                dlc_lib.ZSTD_COMP_NAME,
                dlc_lib.ZSTD_COMP_LEVEL_OPT,
                dlc_lib.ZSTD_MAX_COMP_LEVEL,
            ]
        )
        self.assertCommandContains(
            [
                "unsquashfs",
                "-d",
            ]
        )
        truncate_mock.asset_called()
        copy_dir_mock.assert_called_once_with(
            partial_mock.HasString("src"),
            partial_mock.HasString("root"),
            symlinks=True,
        )

    def testCreateSquashfsReproducible(self) -> None:
        """Test that squashfs commands are run with reproducible args."""
        self.PatchObject(os.path, "getsize", return_value=(_BLOCK_SIZE * 1))
        truncate_mock = self.PatchObject(os, "truncate")
        copy_dir_mock = self.PatchObject(osutils, "CopyDirContents")

        gen = self.GetDlcGenerator()
        gen.reproducible = True
        gen.CreateSquashfsImage()
        self.assertCommandContains(
            [
                "mksquashfs",
                "-4k-align",
                "-noappend",
                "-comp",
                dlc_lib.ZSTD_COMP_NAME,
                dlc_lib.ZSTD_COMP_LEVEL_OPT,
                dlc_lib.ZSTD_MAX_COMP_LEVEL,
                "-mkfs-time",
                "0",
                "-all-time",
                "0",
            ]
        )
        self.assertCommandContains(
            [
                "unsquashfs",
                "-d",
            ]
        )
        truncate_mock.asset_called()
        copy_dir_mock.assert_called_once_with(
            partial_mock.HasString("src"),
            partial_mock.HasString("root"),
            symlinks=True,
        )

    def testPrepareLsbRelease(self) -> None:
        """Tests that lsb-release is created correctly."""
        generator = self.GetDlcGenerator()
        dlc_dir = os.path.join(self.tempdir, "dlc_dir")

        generator.PrepareLsbRelease(dlc_dir)

        expected_lsb_release = (
            "\n".join(
                [
                    "DLC_ID=%s" % _ID,
                    "DLC_PACKAGE=%s" % _PACKAGE,
                    "DLC_NAME=%s" % _NAME,
                    "DLC_RELEASE_APPID=foo_%s" % _ID,
                ]
            )
            + "\n"
        )

        self.assertEqual(
            osutils.ReadFile(os.path.join(dlc_dir, "etc/lsb-release")),
            expected_lsb_release,
        )

    def testCollectExtraResources(self) -> None:
        """Tests that extra resources are collected correctly."""
        generator = self.GetDlcGenerator()

        dlc_dir = os.path.join(self.tempdir, "dlc_dir")
        generator.CollectExtraResources(dlc_dir)

        ue_conf = "etc/update_engine.conf"
        self.assertEqual(
            osutils.ReadFile(os.path.join(self.tempdir, "build_root", ue_conf)),
            "foo-content",
        )

    def testGetImageloaderJsonContent(self) -> None:
        """Test that GetImageloaderJsonContent returns correct content."""
        blocks = 100
        content = self.GetDlcGenerator().GetImageloaderJsonContent(
            "01234567", "deadbeef", blocks
        )
        self.assertEqual(
            content,
            {
                "fs-type": dlc_lib.SQUASHFS_TYPE,
                "pre-allocated-size": str(_PRE_ALLOCATED_BLOCKS * _BLOCK_SIZE),
                "id": _ID,
                "package": _PACKAGE,
                "size": str(blocks * _BLOCK_SIZE),
                "table-sha256-hash": "deadbeef",
                "name": _NAME,
                "description": _DESCRIPTION,
                "image-sha256-hash": "01234567",
                "image-type": "dlc",
                "version": _VERSION,
                "is-removable": True,
                "manifest-version": 1,
                "mount-file-required": False,
                "preload-allowed": False,
                "powerwash-safe": False,
                "factory-install": False,
                "reserved": False,
                "critical-update": False,
                "loadpin-verity-digest": False,
                "scaled": False,
                "force-ota": False,
                "use-logical-volume": False,
                "user-tied": False,
            },
        )

    def testLogicalVolumeJson(self) -> None:
        """Test that GetImageloaderJsonContent logical volume value is set."""
        gen = self.GetDlcGenerator()

        # Values should always be what `scaled` is set to.
        for pr in list(itertools.product((False, True), repeat=2)):
            gen.ebuild_params.scaled = pr[0]
            gen.ebuild_params.use_logical_volume = pr[1]

            content = gen.GetImageloaderJsonContent("", "", 100)

            self.assertEqual(content["scaled"], pr[0])
            self.assertEqual(content["use-logical-volume"], pr[0] or pr[1])

    def testVerifyImageSize(self) -> None:
        """Test that VerifyImageSize throws exception on errors only."""
        # Succeeds since image size is smaller than preallocated size.
        self.PatchObject(
            os.path,
            "getsize",
            return_value=(_PRE_ALLOCATED_BLOCKS - 1) * _BLOCK_SIZE,
        )
        self.GetDlcGenerator().VerifyImageSize(image="")

        with self.assertRaises(ValueError):
            # Fails since image size is bigger than preallocated size.
            self.PatchObject(
                os.path,
                "getsize",
                return_value=(_PRE_ALLOCATED_BLOCKS + 1) * _BLOCK_SIZE,
            )
            self.GetDlcGenerator().VerifyImageSize(image="")

    def testVerifyImageSizeNearingWarning(self) -> None:
        """Test that VerifyImageSize logs the correct nearing warning."""
        # Logs a warning that actual size is near the preallocated size.
        with cros_test_lib.LoggingCapturer() as logs:
            self.PatchObject(
                os.path,
                "getsize",
                return_value=(
                    _PRE_ALLOCATED_BLOCKS
                    * _BLOCK_SIZE
                    / _IMAGE_SIZE_NEARING_RATIO
                ),
            )
            self.GetDlcGenerator().VerifyImageSize(image="")
            self.AssertLogsContain(logs, "is nearing the preallocated size")

    def testVerifyImageSizeGrowthWarning(self) -> None:
        """Test that VerifyImageSize logs the correct growth warning."""
        # Logs a warning that actual size is significantly less than the
        # preallocated size.
        with cros_test_lib.LoggingCapturer() as logs:
            self.PatchObject(
                os.path,
                "getsize",
                return_value=(
                    _PRE_ALLOCATED_BLOCKS
                    * _BLOCK_SIZE
                    / _IMAGE_SIZE_GROWTH_RATIO
                ),
            )
            self.GetDlcGenerator().VerifyImageSize(image="")
            self.AssertLogsContain(
                logs, "is significantly less than the preallocated size"
            )

    def testVerifyImageSizeDevSizeWarning(self) -> None:
        """Test that VerifyImageSize logs the DEV_SIZE warning."""
        # Logs a warning that the preallocated size is set to DEV_SIZE.
        with cros_test_lib.LoggingCapturer() as logs:
            self.PatchObject(
                os.path,
                "getsize",
                return_value=_BLOCK_SIZE,
            )
            self.GetDlcGenerator(
                pre_allocated_blocks=dlc_lib.MAGIC_DEV_SIZE
            ).VerifyImageSize(image="")
            self.AssertLogsContain(
                logs, "The DLC image size will not be verified"
            )

    def testGetOptimalImageBlockSize(self) -> None:
        """Test that GetOptimalImageBlockSize returns the valid block size."""
        dlc_generator = self.GetDlcGenerator()
        self.assertEqual(dlc_generator.GetOptimalImageBlockSize(0), 0)
        self.assertEqual(dlc_generator.GetOptimalImageBlockSize(1), 1)
        self.assertEqual(dlc_generator.GetOptimalImageBlockSize(_BLOCK_SIZE), 1)
        self.assertEqual(
            dlc_generator.GetOptimalImageBlockSize(_BLOCK_SIZE + 1), 2
        )

    @mock.patch.object(cros_build_lib, "run", side_effect=cros_build_lib.run)
    def testGenerateVerityRandomSalting(self, run_mock) -> None:
        """Test GenerateVerity is salting correctly"""
        gen = self.GetDlcGenerator()
        osutils.WriteFile(
            gen.dest_image,
            "a" * _BLOCK_SIZE * 2,
            makedirs=True,
        )

        gen.GenerateVerity()

        run_mock.assert_called_with(
            [
                "verity",
                "--mode=create",
                "--alg=sha256",
                f"--payload={gen.dest_image}",
                "--payload_blocks=2",
                mock.ANY,
                "--salt=random",
            ],
            capture_output=True,
        )

    @mock.patch.object(cros_build_lib, "run", side_effect=cros_build_lib.run)
    def testGenerateVerityReproducibleSalting(self, run_mock) -> None:
        """Test GenerateVerity is reproducibly salting correctly"""
        gen = self.GetDlcGenerator()
        osutils.WriteFile(
            gen.dest_image,
            "a" * _BLOCK_SIZE * 2,
            makedirs=True,
        )

        salt = "1337D00D"
        gen.GenerateVerity(salt)

        run_mock.assert_called_with(
            [
                "verity",
                "--mode=create",
                "--alg=sha256",
                f"--payload={gen.dest_image}",
                "--payload_blocks=2",
                mock.ANY,
                f"--salt={salt}",
            ],
            capture_output=True,
        )


class FinalizeDlcsTest(cros_test_lib.MockTempDirTestCase):
    """Tests functions that generate the final DLC images."""

    def setUp(self) -> None:
        """Setup FinalizeDlcsTest."""
        self.ExpectRootOwnedFiles()

    def testInstallDlcImagesFactoryInstallDisallowed(self) -> None:
        """Verify InstallDlcImages validity checks build packaged parameters."""
        sysroot = os.path.join(self.tempdir, "sysroot")
        params = dlc_lib.EbuildParams(
            dlc_id=_ID,
            dlc_package=_PACKAGE,
            fs_type=dlc_lib.SQUASHFS_TYPE,
            name=_NAME,
            description=_DESCRIPTION,
            pre_allocated_blocks=_PRE_ALLOCATED_BLOCKS,
            version=_VERSION,
            preload=False,
            mount_file_required=False,
            reserved=False,
            critical_update=False,
            fullnamerev=_FULLNAME_REV,
            factory_install=True,
        )
        params.StoreDlcParameters(sysroot, False)
        output = os.path.join(self.tempdir, "output")

        with self.assertRaises(Exception) as e:
            dlc_lib.InstallDlcImages(
                board=_BOARD, sysroot=sysroot, install_root_dir=output
            )
        self.assertIn(
            "DLC=id is not allowed to be factory installed.",
            str(e.exception),
        )

    def testInstallDlcImagesPowerwashSafeDisallowed(self) -> None:
        """Verify InstallDlcImages sanity checks powerwash safe parameter."""
        sysroot = os.path.join(self.tempdir, "sysroot")
        params = dlc_lib.EbuildParams(
            dlc_id=_ID,
            dlc_package=_PACKAGE,
            fs_type=dlc_lib.SQUASHFS_TYPE,
            name=_NAME,
            description=_DESCRIPTION,
            pre_allocated_blocks=_PRE_ALLOCATED_BLOCKS,
            version=_VERSION,
            preload=False,
            mount_file_required=False,
            reserved=False,
            critical_update=False,
            fullnamerev=_FULLNAME_REV,
            powerwash_safe=True,
        )
        params.StoreDlcParameters(sysroot, False)
        output = os.path.join(self.tempdir, "output")

        with self.assertRaises(Exception) as e:
            dlc_lib.InstallDlcImages(
                board=_BOARD, sysroot=sysroot, install_root_dir=output
            )
        self.assertIn(
            "DLC=id is not allowed to be powerwash safe.",
            str(e.exception),
        )

    def testInstallDlcImagesLegacy(self) -> None:
        """Verify InstallDlcImages copies all legacy DLCs correctly."""
        sysroot = os.path.join(self.tempdir, "sysroot")
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID,
                dlc_lib.DLC_PACKAGE,
                dlc_lib.DLC_IMAGE,
            ),
            "content",
            makedirs=True,
        )
        osutils.SafeMakedirs(
            os.path.join(
                sysroot, dlc_lib.DLC_BUILD_DIR, _ID, dlc_lib.DLC_PACKAGE
            )
        )
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(
            board=_BOARD, sysroot=sysroot, install_root_dir=output
        )
        self.assertExists(
            os.path.join(output, _ID, dlc_lib.DLC_PACKAGE, dlc_lib.DLC_IMAGE)
        )

    def testInstallDlcImagesScaled(self) -> None:
        """Verifies InstallDlcImages copies all scaled DLCs correctly."""
        sysroot = os.path.join(self.tempdir, "sysroot")
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR_SCALED,
                _ID,
                dlc_lib.DLC_PACKAGE,
                dlc_lib.DLC_IMAGE,
            ),
            "content",
            makedirs=True,
        )
        osutils.SafeMakedirs(
            os.path.join(
                sysroot, dlc_lib.DLC_BUILD_DIR_SCALED, _ID, dlc_lib.DLC_PACKAGE
            )
        )
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(
            board=_BOARD,
            sysroot=sysroot,
            install_root_dir=output,
        )
        self.assertExists(
            os.path.join(output, _ID, dlc_lib.DLC_PACKAGE, dlc_lib.DLC_IMAGE)
        )

    def testInstallDlcImagesAll(self) -> None:
        """Verifies InstallDlcImages copies all types of DLCs correctly."""
        sysroot = os.path.join(self.tempdir, "sysroot")
        for p, _id in (
            (dlc_lib.DLC_BUILD_DIR, _ID),
            (dlc_lib.DLC_BUILD_DIR_SCALED, _ID_FOO),
        ):
            osutils.WriteFile(
                os.path.join(
                    sysroot, p, _id, dlc_lib.DLC_PACKAGE, dlc_lib.DLC_IMAGE
                ),
                "content",
                makedirs=True,
            )
            osutils.SafeMakedirs(
                os.path.join(sysroot, p, _id, dlc_lib.DLC_PACKAGE)
            )
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(
            board=_BOARD,
            sysroot=sysroot,
            install_root_dir=output,
        )
        self.assertExists(
            os.path.join(output, _ID, dlc_lib.DLC_PACKAGE, dlc_lib.DLC_IMAGE)
        )
        self.assertExists(
            os.path.join(
                output, _ID_FOO, dlc_lib.DLC_PACKAGE, dlc_lib.DLC_IMAGE
            )
        )

    def testInstallDlcImagesNoDlc(self) -> None:
        copy_contents_mock = self.PatchObject(osutils, "CopyDirContents")
        sysroot = os.path.join(self.tempdir, "sysroot")
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(
            board=_BOARD, sysroot=sysroot, install_root_dir=output
        )
        copy_contents_mock.assert_not_called()

    def testInstallDlcImagesWithFactoryInstallAllowed(self) -> None:
        """Verify InstallDlcImages factory installs DLCs."""
        self.PatchObject(
            dlc_allowlist, "IsFactoryInstallAllowlisted", return_value=True
        )
        package_nums = 2
        factory_install_allowed_json = '{"factory-install": true}'
        sysroot = os.path.join(self.tempdir, "sysroot")
        for package_num in range(package_nums):
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_IMAGE,
                ),
                "image content",
                makedirs=True,
            )
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_TMP_META_DIR,
                    dlc_lib.IMAGELOADER_JSON,
                ),
                factory_install_allowed_json,
                makedirs=True,
            )
        stateful = os.path.join(self.tempdir, "stateful")
        dlc_lib.InstallDlcImages(
            board=_BOARD,
            sysroot=sysroot,
            install_root_dir=None,
            factory_install=True,
            stateful=stateful,
        )
        for package_num in range(package_nums):
            self.assertExists(
                os.path.join(
                    stateful,
                    dlc_lib.DLC_FACTORY_INSTALL_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_IMAGE,
                )
            )

    def testInstallDlcImagesWithFactoryInstallSomeAllowed(self) -> None:
        """Verify InstallDlcImages factory installs some DLCs."""
        self.PatchObject(
            dlc_allowlist, "IsFactoryInstallAllowlisted", return_value=True
        )
        nums = 10
        factory_install_allowed_json = '{"factory-install": true}'
        factory_install_not_allowed_json = '{"factory-install": false}'
        sysroot = os.path.join(self.tempdir, "sysroot")
        for num in range(nums):
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID + str(num),
                    _PACKAGE,
                    dlc_lib.DLC_IMAGE,
                ),
                "image content",
                makedirs=True,
            )
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID + str(num),
                    _PACKAGE,
                    dlc_lib.DLC_TMP_META_DIR,
                    dlc_lib.IMAGELOADER_JSON,
                ),
                factory_install_allowed_json
                if num % 2
                else factory_install_not_allowed_json,
                makedirs=True,
            )
        stateful = os.path.join(self.tempdir, "stateful")
        dlc_lib.InstallDlcImages(
            board=_BOARD,
            sysroot=sysroot,
            install_root_dir=None,
            factory_install=True,
            stateful=stateful,
        )
        for num in range(nums):
            if num % 2:
                self.assertExists(
                    os.path.join(
                        stateful,
                        dlc_lib.DLC_FACTORY_INSTALL_DIR,
                        _ID + str(num),
                        _PACKAGE,
                        dlc_lib.DLC_IMAGE,
                    )
                )
            else:
                self.assertNotExists(
                    os.path.join(
                        stateful,
                        dlc_lib.DLC_FACTORY_INSTALL_DIR,
                        _ID + str(num),
                        _PACKAGE,
                        dlc_lib.DLC_IMAGE,
                    )
                )

    def testInstallDlcImagesWithPreloadAllowed(self) -> None:
        package_nums = 2
        preload_allowed_json = '{"preload-allowed": true}'
        sysroot = os.path.join(self.tempdir, "sysroot")
        for package_num in range(package_nums):
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_IMAGE,
                ),
                "image content",
                makedirs=True,
            )
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_TMP_META_DIR,
                    dlc_lib.IMAGELOADER_JSON,
                ),
                preload_allowed_json,
                makedirs=True,
            )
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(
            board=_BOARD, sysroot=sysroot, install_root_dir=output, preload=True
        )
        for package_num in range(package_nums):
            self.assertExists(
                os.path.join(
                    output, _ID, _PACKAGE + str(package_num), dlc_lib.DLC_IMAGE
                )
            )

    def testInstallDlcImagesWithPreloadNotAllowed(self) -> None:
        package_nums = 2
        preload_not_allowed_json = '{"preload-allowed": false}'
        sysroot = os.path.join(self.tempdir, "sysroot")
        for package_num in range(package_nums):
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_IMAGE,
                ),
                "image content",
                makedirs=True,
            )
            osutils.WriteFile(
                os.path.join(
                    sysroot,
                    dlc_lib.DLC_BUILD_DIR,
                    _ID,
                    _PACKAGE + str(package_num),
                    dlc_lib.DLC_TMP_META_DIR,
                    dlc_lib.IMAGELOADER_JSON,
                ),
                preload_not_allowed_json,
                makedirs=True,
            )
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(
            board=_BOARD, sysroot=sysroot, install_root_dir=output, preload=True
        )
        for package_num in range(package_nums):
            self.assertNotExists(
                os.path.join(
                    output, _ID, _PACKAGE + str(package_num), dlc_lib.DLC_IMAGE
                )
            )

    def testInstallDlcImagesTrustedVerityDigests(self) -> None:
        """Tests InstallDlcImages to verify verity digests are written."""
        sysroot = self.tempdir / "sysroot"
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID,
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.IMAGELOADER_JSON,
            ),
            '{"loadpin-verity-digest": true}',
            makedirs=True,
        )
        root_hexdigest = (
            "af7d331ac908dd6e4f6771a3146310bc7edcfe8d9794abcd34512e1a7b704adc"
        )
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID,
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.DLC_VERITY_TABLE,
            ),
            "0 128 verity payload=ROOT_DEV hashtree=HASH_DEV hashstart=128 "
            f"alg=sha256 root_hexdigest={root_hexdigest} "
            "salt="
            "471347ffffff2f4a1cff1224ff7b04ffff68ff19ff2dffff63ff47ffffff387c",
            makedirs=True,
        )
        output = os.path.join(self.tempdir, "output")
        dlc_lib.InstallDlcImages(board=_BOARD, sysroot=sysroot, rootfs=output)
        self.assertEqual(
            osutils.ReadFile(
                os.path.join(
                    output,
                    dlc_lib.DLC_META_DIR,
                    dlc_lib.DLC_LOADPIN_TRUSTED_VERITY_DIGESTS,
                )
            ),
            f"{_DLC_LOADPIN_FILE_HEADER}\n{root_hexdigest}\n",
        )

    def testInstallDlcImagesMultiDlcTrustedVerityDigests(self) -> None:
        """Verifies InstallDlcImages writes multiple verity digests."""
        sysroot = self.tempdir / "sysroot"
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID + "1",
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.IMAGELOADER_JSON,
            ),
            '{"loadpin-verity-digest": true}',
            makedirs=True,
        )
        root_hexdigest1 = (
            "af7d331ac908dd6e4f6771a3146310bc7edcfe8d9794abcd34512e1a7b704adc"
        )
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID + "1",
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.DLC_VERITY_TABLE,
            ),
            "0 128 verity payload=ROOT_DEV hashtree=HASH_DEV hashstart=128 "
            f"alg=sha256 root_hexdigest={root_hexdigest1} "
            "salt="
            "471347ffffff2f4a1cff1224ff7b04ffff68ff19ff2dffff63ff47ffffff387c",
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID + "1dupe",
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.IMAGELOADER_JSON,
            ),
            '{"loadpin-verity-digest": true}',
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID + "1dupe",
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.DLC_VERITY_TABLE,
            ),
            "0 128 verity payload=ROOT_DEV hashtree=HASH_DEV hashstart=128 "
            f"alg=sha256 root_hexdigest={root_hexdigest1} "
            "salt="
            "471347ffffff2f4a1cff1224ff7b04ffff68ff19ff2dffff63ff47ffffff387c",
            makedirs=True,
        )
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID + "2",
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.IMAGELOADER_JSON,
            ),
            '{"loadpin-verity-digest": true}',
            makedirs=True,
        )
        root_hexdigest2 = (
            "cdefedb2405a5d87a1e441caf0b3a6fd4d59947597149215ba9ef7d88e269004"
        )
        osutils.WriteFile(
            os.path.join(
                sysroot,
                dlc_lib.DLC_BUILD_DIR,
                _ID + "2",
                _PACKAGE,
                dlc_lib.DLC_TMP_META_DIR,
                dlc_lib.DLC_VERITY_TABLE,
            ),
            "0 196184 verity payload=ROOT_DEV hashtree=HASH_DEV "
            "hashstart=196184 "
            f"alg=sha256 root_hexdigest={root_hexdigest2} "
            "salt="
            "44ff73ff18ff59ff765aff4fffffff45ff2b60ffff2915ff3fffffffff3aff33",
            makedirs=True,
        )
        output = self.tempdir / "output"
        dlc_lib.InstallDlcImages(board=_BOARD, sysroot=sysroot, rootfs=output)
        self.assertEqual(
            osutils.ReadFile(
                os.path.join(
                    output,
                    dlc_lib.DLC_META_DIR,
                    dlc_lib.DLC_LOADPIN_TRUSTED_VERITY_DIGESTS,
                )
            ),
            f"{_DLC_LOADPIN_FILE_HEADER}\n"
            f"{root_hexdigest1}\n{root_hexdigest2}\n",
        )

    def testInstallDlcImagesWithArtifactsMeta(self) -> None:
        """Verifies InstallDlcImages with artifacts meta DLC(s)."""
        sysroot = self.tempdir / "sysroot"

        imageloader_json_data = '{"i am": "a dict"}'
        osutils.WriteFile(
            sysroot
            / dlc_lib.DLC_BUILD_DIR_ARTIFACTS_META
            / _ID
            / _PACKAGE
            / dlc_lib.IMAGELOADER_JSON,
            imageloader_json_data,
            makedirs=True,
        )

        verity_table_data = (
            "0 128 verity payload=ROOT_DEV hashtree=HASH_DEV hashstart=128 "
            "alg=sha256 "
            "root_hexdigest="
            "beef0000c908dd6e4f6771a3146310bc7edcfe8d9794abcd34512e1a0000beef "
            "salt="
            "471347ffffff2f4a1cff1224ff7b04ffff68ff19ff2dffff63ff47ffffff387c"
        )
        osutils.WriteFile(
            sysroot
            / dlc_lib.DLC_BUILD_DIR_ARTIFACTS_META
            / _ID
            / _PACKAGE
            / dlc_lib.DLC_VERITY_TABLE,
            verity_table_data,
            makedirs=True,
        )

        foobar_file = "foobar"
        osutils.WriteFile(
            sysroot
            / dlc_lib.DLC_BUILD_DIR_ARTIFACTS_META
            / _ID
            / _PACKAGE
            / foobar_file,
            "please don't be copied",
            makedirs=True,
        )

        output = self.tempdir / "output"
        dlc_lib.InstallDlcImages(board=_BOARD, sysroot=sysroot, rootfs=output)

        self.assertNotExists(
            output / dlc_lib.DLC_META_DIR / _ID / _PACKAGE / foobar_file
        )
        self.assertExists(
            output
            / dlc_lib.DLC_META_DIR
            / f"{dlc_lib.DLC_META_FILE_PREFIX}{_ID}"
        )
        parsed = dlc_lib.DlcMetadata(
            metadata_path=output / dlc_lib.DLC_META_DIR
        ).LoadDestMetadata(_ID)
        self.assertEqual(
            json.dumps(parsed[_ID]["manifest"]), imageloader_json_data
        )
        self.assertEqual(parsed[_ID]["table"], verity_table_data)


class PowerwashSafeDlcsInRootfsTest(cros_test_lib.TempDirTestCase):
    """Tests dlc_lib powerwash safety related functions."""

    def constructDlc(
        self, dlc_id: str, rootfs: str, powerwash_safe: bool
    ) -> None:
        """Constructs the DLC in given rootfs

        Args:
            dlc_id: The DLC ID to construct.
            rootfs: The rootfs to construct DLC in.
            powerwash_safe: Boolean indicating if powerwash safety.
        """
        p = os.path.join(rootfs, dlc_id, dlc_lib.DLC_PACKAGE)
        osutils.SafeMakedirs(p)
        with open(
            os.path.join(p, dlc_lib.IMAGELOADER_JSON), "w", encoding="utf-8"
        ) as fp:
            json.dump({dlc_lib.POWERWASH_SAFE_KEY: powerwash_safe}, fp)
        osutils.WriteFile(os.path.join(p, dlc_lib.DLC_VERITY_TABLE), "")

    def testMissingMeta(self) -> None:
        """Test missing meta rootfs for UniquePowerwashSafeDlcsInRootfs."""
        with self.assertRaises(dlc_lib.Error) as e:
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir)
        self.assertEqual(
            str(e.exception),
            "Missing metadata path: "
            f"{os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)}",
        )

    def testEmpty(self) -> None:
        """Test empty meta rootfs for UniquePowerwashSafeDlcsInRootfs."""
        osutils.SafeMakedirs(os.path.join(self.tempdir, dlc_lib.DLC_META_DIR))
        self.assertEqual(
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir),
            set(),
        )

    def testInvalidDlc(self) -> None:
        """Test invalid DLC in rootfs for unique set."""
        self.constructDlc("-foo", self.tempdir, True)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create([("-foo", self.tempdir)])

        with self.assertRaises(dlc_lib.Error) as e:
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir)
        self.assertEqual(
            str(e.exception),
            "-foo is invalid:\n"
            "Must start with alphanumeric character.\n"
            "Must only use alphanumeric and - (dash).",
        )

    def testPowerwashSafeDlc(self) -> None:
        """Test rootfs with powerwash safe DLC for unique set"""
        self.constructDlc("foo", self.tempdir, True)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create([("foo", self.tempdir)])

        self.assertEqual(
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir),
            {"foo"},
        )

    def testPowerwashSafeDlcs(self) -> None:
        """Test rootfs with powerwash safe DLCs for unique set."""
        self.constructDlc("foo", self.tempdir, True)
        self.constructDlc("bar", self.tempdir, True)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create([("foo", self.tempdir), ("bar", self.tempdir)])

        self.assertEqual(
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir),
            {"foo", "bar"},
        )

    def testNoPowerwashSafeDlcs(self) -> None:
        """Test rootfs with no powerwash safe DLCs for unique set."""
        self.constructDlc("foo", self.tempdir, False)
        self.constructDlc("bar", self.tempdir, False)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create([("foo", self.tempdir), ("bar", self.tempdir)])

        self.assertEqual(
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir),
            set(),
        )

    def testMixedPowerwashSafeDlcs(self) -> None:
        """Test rootfs with mixed powerwash safe DLCs for unique set."""
        self.constructDlc("foo", self.tempdir, True)
        self.constructDlc("bar", self.tempdir, False)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create([("foo", self.tempdir), ("bar", self.tempdir)])

        self.assertEqual(
            dlc_lib.UniquePowerwashSafeDlcsInRootfs(self.tempdir),
            {"foo"},
        )

    def testCreationOfPowerwashSafeFileInEmptyMetaRootfs(self) -> None:
        """Test empty rootfs for powerwash safe file creation."""
        osutils.SafeMakedirs(os.path.join(self.tempdir, dlc_lib.DLC_META_DIR))
        dlc_lib.CreatePowerwashSafeFileInRootfs(self.tempdir)
        powerwash_safe_file_content = osutils.ReadFile(
            os.path.join(
                self.tempdir,
                dlc_lib.DLC_META_DIR,
                dlc_lib.DLC_META_POWERWASH_SAFE_FILE,
            )
        )
        self.assertEqual(
            powerwash_safe_file_content,
            "",
        )

    def testCreationOfPowerwashSafeFileInRootfsWithDlc(self) -> None:
        """Test rootfs with powerwash safe DLC for meta file creation."""
        self.constructDlc("foo", self.tempdir, True)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create([("foo", self.tempdir)])

        dlc_lib.CreatePowerwashSafeFileInRootfs(self.tempdir)
        powerwash_safe_file_content = osutils.ReadFile(
            os.path.join(
                self.tempdir,
                dlc_lib.DLC_META_DIR,
                dlc_lib.DLC_META_POWERWASH_SAFE_FILE,
            )
        )
        self.assertEqual(
            powerwash_safe_file_content,
            "foo",
        )

    def testCreationOfPowerwashSafeFileInRootfsWithMixedDlc(self) -> None:
        """Test rootfs with mixed powerwash safe DLC for meta file creation."""
        self.constructDlc("hello", self.tempdir, True)
        self.constructDlc("there", self.tempdir, False)
        self.constructDlc("world", self.tempdir, True)
        self.constructDlc("a", self.tempdir, True)
        metadata_dir = os.path.join(self.tempdir, dlc_lib.DLC_META_DIR)
        with dlc_lib.DlcMetadata(metadata_dir) as metadata:
            metadata.Create(
                [
                    ("hello", self.tempdir),
                    ("there", self.tempdir),
                    ("world", self.tempdir),
                    ("a", self.tempdir),
                ]
            )

        dlc_lib.CreatePowerwashSafeFileInRootfs(self.tempdir)
        powerwash_safe_file_content = osutils.ReadFile(
            os.path.join(
                self.tempdir,
                dlc_lib.DLC_META_DIR,
                dlc_lib.DLC_META_POWERWASH_SAFE_FILE,
            )
        )
        self.assertEqual(
            set(powerwash_safe_file_content.splitlines()),
            {"hello", "world", "a"},
        )


@pytest.mark.parametrize("bd", (True, False))
@pytest.mark.parametrize("bd_scaled", (True, False))
@pytest.mark.parametrize("bd_artifacts_meta", (True, False))
def test_install_dlc_images_duplicate_ids_sanity_check(
    tmp_path, bd: bool, bd_scaled: bool, bd_artifacts_meta: bool
) -> None:
    """Verify InstallDlcImages sanity checks duplicate DLC IDs.

    Args:
        tmp_path: A pytest injected temporary path.
        bd: True to add DLC into the DLC builder directory.
        bd_scaled: True to add DLC into the DLC scaled builder directory.
        bd_artifacts_meta: True to add DLC into the DLC artifacts meta builder
            directory.
    """
    sysroot = tmp_path / "sysroot"
    if bd:
        osutils.SafeMakedirs(sysroot / dlc_lib.DLC_BUILD_DIR / _ID)
    if bd_scaled:
        osutils.SafeMakedirs(sysroot / dlc_lib.DLC_BUILD_DIR_SCALED / _ID)
    if bd_artifacts_meta:
        osutils.SafeMakedirs(
            sysroot / dlc_lib.DLC_BUILD_DIR_ARTIFACTS_META / _ID
        )
    fnc = lambda: dlc_lib.InstallDlcImages(
        board=_BOARD,
        sysroot=sysroot,
    )
    if [bd, bd_scaled, bd_artifacts_meta].count(True) > 1:
        with cros_test_lib.LoggingCapturer() as logs:
            fnc()
            assert logs.LogsMatch(
                "There are duplicate DLC IDs: {'" f"{_ID}" "'}"
            )
    else:
        fnc()
