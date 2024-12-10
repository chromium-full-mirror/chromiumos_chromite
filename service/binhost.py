# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The Binhost API interacts with Portage binhosts and Packages files."""

import base64
import logging
import os
from pathlib import Path
import subprocess
from typing import List, NamedTuple, Optional, TYPE_CHECKING, Union

from chromite.third_party import requests

from chromite.api.gen.chromiumos import prebuilts_cloud_pb2
from chromite.lib import binpkg
from chromite.lib import config_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import git
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib import repo_util
from chromite.lib import sysroot_lib
from chromite.utils import gs_urls_util
from chromite.utils import key_value_store


if TYPE_CHECKING:
    from chromite.lib import build_target_lib
    from chromite.lib import chroot_lib

# The name of the ACL argument file.
_GOOGLESTORAGE_GSUTIL_FILE = "googlestorage_acl.txt"

# The name of the package file (relative to sysroot) where the list of packages
# for dev-install is stored.
_DEV_INSTALL_PACKAGES_FILE = "build/dev-install/package.installable"

# The maximum number of binhosts to return from the lookup service.
_MAX_BINHOSTS = 5

# Parameters for the Lookup Binhosts Service endpoint.
_PROTOCOL = "https"
_CHROMEOS_PREBUILTS_DOMAIN = "us-central1-chromeos-prebuilts.cloudfunctions.net"
_LOOKUP_BINHOSTS_ENDPOINT_STAGING = "staging-lookup-service-binhosts"
_LOOKUP_BINHOSTS_ENDPOINT_PROD = "prod-lookup-service-binhosts"

# Timeout for the API call to the binhost lookup service.
_BINHOST_LOOKUP_SERVICE_TIMEOUT = 60

# Google storage bucket which contains binhosts.
_BINHOSTS_GS_BUCKET_NAME_STAGING = "staging-chromeos-prebuilt"
_BINHOSTS_GS_BUCKET_NAME_PROD = "chromeos-prebuilt"


class Error(Exception):
    """Base error class for the module."""


class EmptyPrebuiltsRoot(Error):
    """When a prebuilts root is unexpectedly empty."""


class NoAclFileFound(Error):
    """No ACL file could be found."""


class InvalidMaxUris(Error):
    """When maximum number of uris to store is less than or equal to 0."""


class BinhostsLookupServiceError(Error):
    """When the binhost lookup service returns an error."""


def _ValidateBinhostConf(path: Path, key: str) -> None:
    """Validates the binhost conf file defines only one environment variable.

    This function checks to ensure unexpected configuration is not clobbered by
    conf overwrites.

    Args:
        path: Path to the file to validate.
        key: Expected binhost key.

    Raises:
        ValueError: If file defines != 1 environment variable.
    """
    if not path.exists():
        # If the conf file does not exist, e.g. with new targets, then whatever.
        return

    kvs = key_value_store.LoadFile(path)

    if not kvs:
        raise ValueError(
            "Found empty .conf file %s when a non-empty one was expected."
            % path
        )
    elif len(kvs) > 1:
        raise ValueError(
            "Conf file %s must define exactly 1 variable. "
            "Instead found: %r" % (path, kvs)
        )
    elif key not in kvs:
        raise KeyError("Did not find key %s in %s" % (key, path))


def _ValidatePrebuiltsFiles(
    prebuilts_root: str, prebuilts_paths: List[str]
) -> None:
    """Validate all prebuilt files exist.

    Args:
        prebuilts_root: Absolute path to root directory containing prebuilts.
        prebuilts_paths: List of file paths relative to root, to be verified.

    Raises:
        LookupError: If any prebuilt archive does not exist.
    """
    for prebuilt_path in prebuilts_paths:
        full_path = os.path.join(prebuilts_root, prebuilt_path)
        if not os.path.exists(full_path):
            raise LookupError("Prebuilt archive %s does not exist" % full_path)


def _ValidatePrebuiltsRoot(
    target: "build_target_lib.BuildTarget", prebuilts_root: str
) -> None:
    """Validate the given prebuilts root exists.

    If the root does not exist, it probably means the build target did not build
    successfully, so warn callers appropriately.

    Args:
        target: The build target in question.
        prebuilts_root: The expected root directory for the target's prebuilts.

    Raises:
        EmptyPrebuiltsRoot: If prebuilts root does not exist.
    """
    if not os.path.exists(prebuilts_root):
        raise EmptyPrebuiltsRoot(
            "Expected to find prebuilts for build target %s at %s. "
            "Did %s build successfully?" % (target, prebuilts_root, target)
        )


def _ValidateBinhostMaxURIs(max_uris: int) -> None:
    """Validates that the max_uris is greater or equal to 1.

    Args:
        max_uris: Maximum number of uris that we need to store in Binhost conf
            file.

    Raises:
        InvalidMaxUris: If max_uris is None or less than or equal to zero.
    """
    if max_uris is None or max_uris <= 0:
        raise InvalidMaxUris(
            f"Binhost file cannot have {max_uris} number of URIs."
        )


def GetPrebuiltsRoot(
    chroot: "chroot_lib.Chroot",
    sysroot: "sysroot_lib.Sysroot",
    build_target: "build_target_lib.BuildTarget",
) -> str:
    """Find the root directory with binary prebuilts for the given sysroot.

    Args:
        chroot: The chroot where the sysroot lives.
        sysroot: The sysroot.
        build_target: The build target.

    Returns:
        Absolute path to the root directory with the target's prebuilt archives.
    """
    root = chroot.full_path(sysroot.JoinPath("packages"))
    _ValidatePrebuiltsRoot(build_target, root)
    return root


def GetPrebuiltsFiles(
    prebuilts_root: str,
    package_index_paths: Optional[List[str]] = None,
    sudo=False,
) -> List[str]:
    """Find paths to prebuilts at the given root directory.

    Assumes the root contains a Portage package index named Packages.

    Args:
        prebuilts_root: Absolute path to root directory containing a package
            index.
        package_index_paths: A list of paths to previous package index files
            used to de-duplicate prebuilts.
        sudo: Whether to write the file as the root user.

    Returns:
        List of paths to all prebuilt archives, relative to the root.
    """
    indexes = []
    for package_index_path in package_index_paths or []:
        index = binpkg.PackageIndex()
        index.ReadFilePath(package_index_path)
        indexes.append(index)

    package_index = binpkg.GrabLocalPackageIndex(prebuilts_root)
    packages = package_index.ResolveDuplicateUploads(indexes)
    # Save the PATH changes from the deduplication.
    package_index.WriteFile(Path(prebuilts_root) / "Packages", sudo=sudo)

    prebuilt_paths = []
    for package in packages:
        prebuilt_paths.append(package["CPV"] + ".tbz2")

        include_debug_symbols = package.get("DEBUG_SYMBOLS")
        if cros_build_lib.BooleanShellValue(
            include_debug_symbols, default=False
        ):
            prebuilt_paths.append(package["CPV"] + ".debug.tbz2")

    _ValidatePrebuiltsFiles(prebuilts_root, prebuilt_paths)
    return prebuilt_paths


def UpdatePackageIndex(
    prebuilts_root: str, upload_uri: str, upload_path: str, sudo: bool = False
) -> str:
    """Update package index with information about where it will be uploaded.

    This causes the existing Packages file to be overwritten.

    Args:
        prebuilts_root: Absolute path to root directory containing binary
            prebuilts.
        upload_uri: The URI (typically GS bucket) where prebuilts will be
            uploaded.
        upload_path: The path at the URI for the prebuilts.
        sudo: Whether to write the file as the root user.

    Returns:
        Path to the new Package index.
    """
    assert not upload_path.startswith("/")
    package_index = binpkg.GrabLocalPackageIndex(prebuilts_root)
    package_index.SetUploadLocation(upload_uri, upload_path)
    package_index.header["TTL"] = 60 * 60 * 24 * 365
    package_index_path = os.path.join(prebuilts_root, "Packages")
    package_index.WriteFile(package_index_path, sudo=sudo)
    return package_index_path


def _get_current_uris(
    conf_file_path: Union[str, "Path"], key: str
) -> List[str]:
    """Returns the uri values of the key from the conf file.

    If the file does not exist, then it returns an empty list.

    Args:
        conf_file_path: Path to the conf file.
        key: Expected binhost key.

    Returns:
        List of the current values for the key.
    """
    kvs = key_value_store.LoadFile(str(conf_file_path), ignore_missing=True)
    value = kvs.get(key)
    return value.split(" ") if value is not None else []


def SetBinhost(
    target: str, key: str, uri: str, private: bool = True, max_uris=1
) -> str:
    """Set binhost configuration for the given build target.

    A binhost is effectively a key (Portage env variable) pointing to a set of
    URLs that contains binaries. The configuration is set in .conf files at
    static directories on a build target by build target (and host by host)
    basis.

    This function updates the .conf file by updating the url list.
    The list is updated in the FIFO order.

    Args:
        target: The build target to set configuration for.
        key: The binhost key to set, e.g. POSTSUBMIT_BINHOST.
        uri: The new value for the binhost key,
            e.g. gs://chromeos-prebuilt/foo/bar.
        private: Whether the build target is private.
        max_uris: Maximum number of uris to keep in the conf.

    Returns:
        Path to the updated .conf file.
    """
    _ValidateBinhostMaxURIs(max_uris)
    host = bool("/host/" in uri and key == "POSTSUBMIT_BINHOST")
    conf_path = GetBinhostConfPath(target, key, private, host)
    uris = _get_current_uris(conf_path, key) + [uri]
    osutils.WriteFile(conf_path, '%s="%s"' % (key, " ".join(uris[-max_uris:])))
    return str(conf_path)


def GetBinhostConfPath(
    target: str, key: str, private: bool = True, host: bool = False
) -> Path:
    """Returns binhost conf file path.

    Args:
        target: The build target to get configuration file path for.
        key: The binhost key to get, e.g. POSTSUBMIT_BINHOST.
        private: Whether the build target is private.
        host: Whether to return the path for the host.

    Returns:
        Path to the .conf file.
    """
    conf_dir_name = (
        constants.PRIVATE_BINHOST_CONF_DIR
        if private
        else constants.PUBLIC_BINHOST_CONF_DIR
    )
    binhost_type = "host" if host else "target"
    conf_path = (
        constants.SOURCE_ROOT
        / conf_dir_name
        / binhost_type
        / f"{target}-{key}.conf"
    )
    _ValidateBinhostConf(conf_path, key)
    return conf_path


def RegenBuildCache(
    chroot: "chroot_lib.Chroot",
    overlay_type: str,
    buildroot: Union[str, Path] = constants.SOURCE_ROOT,
) -> List[str]:
    """Regenerate the Build Cache for the given target.

    Args:
        chroot: The chroot where the regen command will be run.
        overlay_type: one of "private", "public", or "both".
        buildroot: Source root to find overlays.

    Returns:
        The overlays with updated caches.
    """
    cmd = [
        chroot.chroot_path(
            Path(buildroot)
            / "chromite"
            / "scripts"
            / "cros_update_metadata_cache"
        ),
        "--overlay-type",
        overlay_type,
        "--debug",
    ]
    result = chroot.run(cmd, stdout=subprocess.PIPE, encoding="utf-8")

    return [str(Path(buildroot) / x) for x in result.stdout.splitlines()]


def GetPrebuiltAclArgs(
    build_target: "build_target_lib.BuildTarget",
) -> List[List[str]]:
    """Read and parse the GS ACL file from the private overlays.

    Args:
        build_target: The build target.

    Returns:
        A list containing all of the [arg, value] pairs. E.g.
        [['-g', 'group_id:READ'], ['-u', 'user:FULL_CONTROL']]
    """
    acl_file = portage_util.FindOverlayFile(
        _GOOGLESTORAGE_GSUTIL_FILE, board=build_target.name
    )

    if not acl_file:
        raise NoAclFileFound("No ACL file found for %s." % build_target.name)

    lines = osutils.ReadFile(acl_file).splitlines()  # type: List[str]
    # Remove comments.
    lines = [line.split("#", 1)[0].strip() for line in lines]
    # Remove empty lines.
    lines = [line for line in lines if line]

    return [line.split() for line in lines]


def GetBinhosts(build_target: "build_target_lib.BuildTarget") -> List[str]:
    """Get the binhosts for the build target.

    Args:
        build_target: The build target.

    Returns:
        The build target's binhosts.
    """
    binhosts = portage_util.PortageqEnvvar(
        "PORTAGE_BINHOST",
        board=build_target.name,
        allow_undefined=True,
    )
    return binhosts.split() if binhosts else []


def GetHostBinhosts() -> List[Optional[str]]:
    """Get the binhosts for the host.

    Returns:
        The host's binhosts.
    """
    # Get the current value for PORTAGE_BINHOST.
    portage_binhost = portage_util.PortageqEnvvar("PORTAGE_BINHOST")
    binhosts = portage_binhost.split() if portage_binhost else []

    # Read the host BINHOST.conf file storing additional host binhosts to use.
    # Currently, only amd64-generic-snapshot updates the contents of the
    # BINHOST.conf file.
    host_binhost_conf = (
        constants.SOURCE_ROOT
        / constants.PUBLIC_BINHOST_CONF_DIR
        / "host"
        / "amd64-generic-POSTSUBMIT_BINHOST.conf"
    )
    kvs = key_value_store.LoadFile(str(host_binhost_conf), ignore_missing=True)
    value = kvs.get("POSTSUBMIT_BINHOST")
    if value:
        binhosts.extend(value.split())

    return binhosts


def ReadDevInstallPackageFile(filename: str) -> List[str]:
    """Parse the dev-install package file.

    Args:
        filename: The full path to the dev-install package list.

    Returns:
        The packages in the package list file.
    """
    with open(filename, encoding="utf-8") as f:
        return [line.strip() for line in f]


def ReadDevInstallFilesToCreatePackageIndex(
    chroot: "chroot_lib.Chroot",
    sysroot: "sysroot_lib.Sysroot",
    package_index_path: str,
    upload_uri: str,
    upload_path: str,
) -> List[str]:
    """Create dev-install Package index specified by package_index_path

    The current Packages file is read and a new Packages file is created based
    on the subset of packages in the _DEV_INSTALL_PACKAGES_FILE.

    Args:
        chroot: The chroot where the sysroot lives.
        sysroot: The sysroot.
        package_index_path: Path to the Packages file to be created.
        upload_uri: The URI (typically GS bucket) where prebuilts will be
            uploaded.
        upload_path: The path at the URI for the prebuilts.

    Returns:
        The list of packages contained in package_index_path, where each package
            string is a category/file.
    """
    # Read the dev-install binhost package file
    devinstall_binhost_filename = chroot.full_path(
        sysroot.path, _DEV_INSTALL_PACKAGES_FILE
    )
    devinstall_package_list = ReadDevInstallPackageFile(
        devinstall_binhost_filename
    )

    # Read the Packages file, remove packages not in package_list
    package_path = chroot.full_path(sysroot.path, "packages")
    CreateFilteredPackageIndex(
        package_path,
        devinstall_package_list,
        package_index_path,
        ConvertGsUploadUri(upload_uri),
        upload_path,
    )

    # We have the list of packages, create full path and verify each one.
    upload_targets_list = GetPrebuiltsForPackages(
        package_path, devinstall_package_list
    )

    return upload_targets_list


def CreateChromePackageIndex(
    chroot: "chroot_lib.Chroot",
    sysroot: "sysroot_lib.Sysroot",
    package_index_path: str,
    gs_bucket: str,
    upload_path: str,
) -> List[str]:
    """Create Chrome package index specified by package_index_path.

    The current Packages file is read and a new Packages file is created based
    on the subset of Chrome packages.

    Args:
        chroot: The chroot where the sysroot lives.
        sysroot: The sysroot.
        package_index_path: Path to the Packages file to be created.
        gs_bucket: The GS bucket where prebuilts will be uploaded.
        upload_path: The path from the GS bucket for the prebuilts.

    Returns:
        The list of packages contained in package_index_path, where each package
            string is a category/file.
    """
    # Get the list of Chrome packages to filter by.
    installed_packages = portage_util.PortageDB(
        chroot.full_path(sysroot.path)
    ).InstalledPackages()
    chrome_packages = []
    for pkg in installed_packages:
        if pkg.category == constants.CHROME_CN and any(
            pn in pkg.pf for pn in (constants.CHROME_PN, "chrome-icu")
        ):
            chrome_packages.append(pkg.package_info.cpvr)

    # Read the Packages file, remove packages not in the packages list.
    packages_path = chroot.full_path(sysroot.path, "packages")
    CreateFilteredPackageIndex(
        packages_path,
        chrome_packages,
        package_index_path,
        gs_bucket,
        upload_path,
        sudo=True,
    )

    # We have the list of packages, create the full path and verify each one.
    upload_targets_list = GetPrebuiltsForPackages(
        packages_path, chrome_packages
    )

    return upload_targets_list


def ConvertGsUploadUri(upload_uri: str) -> str:
    """Convert a GS URI to the equivalent https:// URI.

    Args:
        upload_uri: The base URI provided (could be GS, https, or really any
            format).

    Returns:
        A new https URL if a gs URI was provided and original URI otherwise.
    """
    if not gs_urls_util.PathIsGs(upload_uri):
        return upload_uri
    return gs_urls_util.GsUrlToHttp(upload_uri)


def CreateFilteredPackageIndex(
    package_path: str,
    package_list: List[str],
    package_index_path: str,
    upload_uri: str,
    upload_path: str,
    sudo: bool = False,
) -> None:
    """Create Package file with filtered packages.

    The created package file (package_index_path) contains only the
    specified packages. The new package file will use the provided values
    for upload_uri and upload_path.

    Args:
        package_path: Absolute path to the standard Packages file.
        package_list: Packages to filter.
        package_index_path: Absolute path for new Packages file.
        upload_uri: The URI where prebuilts will be uploaded.
        upload_path: The path at the URI for the prebuilts.
        sudo: Whether to write the file as the root user.
    """

    def ShouldFilterPackage(package: dict) -> bool:
        """Local func to filter packages not in the package_list.

        Args:
            package: Dictionary with key 'CPV' and package name as value.

        Returns:
            True (filter) if not in the package_list, else False
                (don't filter) if in the package_list.
        """
        value = package["CPV"]
        if value in package_list:
            return False
        else:
            return True

    package_index = binpkg.GrabLocalPackageIndex(package_path)
    package_index.RemoveFilteredPackages(ShouldFilterPackage)
    package_index.SetUploadLocation(upload_uri, upload_path)
    package_index.header["TTL"] = 60 * 60 * 24 * 365
    package_index.WriteFile(package_index_path, sudo=sudo)


def GetPrebuiltsForPackages(
    package_root: str, package_list: List[str]
) -> List[str]:
    """Create list of file paths for the package list and validate they exist.

    Args:
        package_root: Path to 'packages' directory.
        package_list: List of packages.

    Returns:
        List of validated targets.
    """
    upload_targets_list = []
    for pkg in package_list:
        zip_target = pkg + ".tbz2"
        upload_targets_list.append(zip_target)
        full_pkg_path = os.path.join(package_root, pkg) + ".tbz2"
        if not os.path.exists(full_pkg_path):
            raise LookupError("Archive %s does not exist" % full_pkg_path)
    return upload_targets_list


class SnapshotShas(NamedTuple):
    """External and internal snapshot SHAs for the lookup service."""

    external: List[Optional[str]]
    internal: List[Optional[str]]


def _fetch_binhosts(
    snapshot_shas: List[str],
    build_target: str,
    profile: str,
    private: bool,
    get_corresponding_binhosts: bool,
    generic_build_target: str,
    generic_profile: str,
    is_staging: bool = False,
) -> List[Optional[str]]:
    """Call the binhost lookup service to get locations of BINHOSTs.

    Args:
        snapshot_shas: List of snapshot shas of the binhosts.
        build_target: build target (also known as board) of the binhosts.
        profile: profile associated with the build target.
        private: True if the binhosts are private.
        get_corresponding_binhosts: True if the corresponding internal/external
            binhosts should also be returned.
        generic_build_target: The base architecture board for the
            build target (e.g. amd64-generic).
        generic_profile: The profile of the base architecture board.
        is_staging: Denote which lookup service endpoint should be called.

    Returns:
        A list of Google Storage URIs of binhosts, sorted by created
        time (descending). Can be empty if no binhosts are found.

    Raises:
        BinhostsLookupServiceError: When there's an error from the binhost
            lookup service.
        google.protobuf.message.DecodeError: When the protobuf message from the
            API response cannot be parsed.
    """
    gs_bucket_name = (
        _BINHOSTS_GS_BUCKET_NAME_STAGING
        if is_staging
        else _BINHOSTS_GS_BUCKET_NAME_PROD
    )
    # Construct and encode the filter parameters.
    lookup_binhosts_request = prebuilts_cloud_pb2.LookupBinhostsRequest(
        gs_bucket_name=gs_bucket_name,
        snapshot_shas=snapshot_shas,
        build_target=build_target,
        profile=profile,
        private=private,
        get_corresponding_binhosts=get_corresponding_binhosts,
        generic_build_target=generic_build_target,
        generic_profile=generic_profile,
    )

    # Encode the request with base64 and convert to a string.
    lookup_binhosts_request_encoded = base64.urlsafe_b64encode(
        lookup_binhosts_request.SerializeToString()
    ).decode()

    # Call the appropriate lookup service endpoint based on the env.
    binhost_lookup_service_uri = "%s://%s/%s" % (
        _PROTOCOL,
        _CHROMEOS_PREBUILTS_DOMAIN,
        _LOOKUP_BINHOSTS_ENDPOINT_STAGING
        if is_staging
        else _LOOKUP_BINHOSTS_ENDPOINT_PROD,
    )
    response = requests.request(
        "GET",
        "%s?filter=%s"
        % (
            binhost_lookup_service_uri,
            lookup_binhosts_request_encoded,
        ),
        timeout=_BINHOST_LOOKUP_SERVICE_TIMEOUT,
    )

    if response.status_code == 200:
        lookup_binhosts_response = prebuilts_cloud_pb2.LookupBinhostsResponse()
        lookup_binhosts_response.ParseFromString(
            base64.urlsafe_b64decode(response.content)
        )
        # The response contains a list of binhost metadata objects which are
        # sorted in descending order of the time they were created at.
        return [x.gs_uri for x in lookup_binhosts_response.binhosts]
    elif response.status_code == 404:
        logging.warning(
            "No suitable binhosts found in the binhost lookup service"
        )
        return []
    else:
        raise BinhostsLookupServiceError(
            "Error while fetching binhosts from the binhost lookup service, "
            "status code: %i, body: %s"
            % (response.status_code, response.content)
        )


def _get_snapshot_shas() -> SnapshotShas:
    """Get snapshot SHAs for different checkout types.

    Returns:
        A SnapshotShas object with the internal, external SHAs populated based
        on the checkout types.
    """
    site_params = config_lib.GetSiteParams()
    snapshot_shas = SnapshotShas([], [])

    # Get the repo.
    try:
        repo = repo_util.Repository.MustFind(constants.SOURCE_ROOT)
    except repo_util.NotInRepoError as e:
        logging.error("Unable to determine a repo directory: %s", e)
        return snapshot_shas

    manifest = repo.Manifest()

    # Get the snapshot SHAs for each checkout type.
    if manifest.HasRemote(site_params.EXTERNAL_REMOTE):
        snapshot_shas.external.extend(
            _get_snapshot_shas_from_git_log(site_params, False)
        )
    if manifest.HasRemote(site_params.INTERNAL_REMOTE):
        snapshot_shas.internal.extend(
            _get_snapshot_shas_from_git_log(site_params, True)
        )
    return snapshot_shas


def _get_snapshot_shas_from_git_log(
    site_params: config_lib.AttrDict, internal: bool
) -> List[Optional[str]]:
    """Get the last n=_MAX_BINHOSTS snapshot SHAs using git log.

    We're intentionally swallowing errors related to determining the snapshot
    SHAs since the lookup service will contain logic for these error cases.

    Args:
        site_params: site parameter configs.
        internal: Whether to get snapshot SHAs of the internal or external
            manifest.

    Returns:
        A list of snapshot SHAs.
    """
    # Determine manifest constants.
    manifest_type = "manifest-internal" if internal else "manifest"
    manifest_dir = os.path.join(constants.SOURCE_ROOT, manifest_type)
    manifest_remote_name = (
        site_params.INTERNAL_REMOTE if internal else site_params.EXTERNAL_REMOTE
    )

    # Determine repo constants.
    repo_branch = "snapshot"
    repo_dir = git.FindRepoDir(".")
    repo_manifests_dir = Path(repo_dir) / "manifests" if repo_dir else None
    if repo_manifests_dir:
        branch = git.ManifestCheckout(repo_manifests_dir).manifest_branch
        if branch in ("stable", "green"):
            repo_branch = branch
    try:
        return git.Log(
            manifest_dir,
            format="format:%H",
            max_count=_MAX_BINHOSTS,
            rev=f"{manifest_remote_name}/{repo_branch}",
        ).splitlines()
    except cros_build_lib.RunCommandError as e:
        logging.warning(e)
        return []


def lookup_binhosts(
    build_target: "build_target_lib.BuildTarget",
    binhost_lookup_service_data: Optional[
        prebuilts_cloud_pb2.BinhostLookupServiceData
    ] = None,
) -> List[Optional[str]]:
    """Get binhost locations from the binhost lookup service.

    Args:
        build_target: Details of the build target.
        binhost_lookup_service_data: Data needed for fetching binhosts.

    Returns:
        A list of Google Storage URIs of binhosts, sorted by created
        time (descending).
    """
    is_staging = False
    if (
        binhost_lookup_service_data
        and binhost_lookup_service_data.snapshot_shas
    ):
        # Use snapshot SHAs if they are passed from the builder.
        snapshot_shas = binhost_lookup_service_data.snapshot_shas
        get_corresponding_binhosts = False
        private = binhost_lookup_service_data.private
        is_staging = binhost_lookup_service_data.is_staging
    else:
        site_params = config_lib.GetSiteParams()
        # Get the repo.
        try:
            repo = repo_util.Repository.MustFind(constants.SOURCE_ROOT)
        except repo_util.NotInRepoError as e:
            logging.error("Unable to determine a repo directory: %s", e)
            raise e

        branch = repo.GetBranch()

        # We have two types of manifests:
        # 1. Pinned manifests - In these manifests all the repositories are
        #    pinned to a specific SHA. This means we can sync the repo to a
        #    known state. The `stable` and `snapshot` branches use pinned
        #    manifests. We then use the SHA of the manifest commit as a stable
        #    identifier to describe the repo state. This identifier is what the
        #    bin lookup services uses to find matching binhosts.
        #
        #    The logic we are using to fetch the SHAs relies on looking at the
        #    `snapshot`/`stable` ref in the `manifest` and `manifest-internal`
        #    repositories instead of the `.repo/manifests` repository. This is
        #    because we need both the public and private SHAs. It does mean that
        #    if someone checks out a previous snapshot commit in their
        #    `.repo/manifest` repository, we ignore it continue to use the
        #    `snapshot`/`stable` refs. This is something that could be improved.
        #    The `stable`/`snapshot` refs might not exist if a `repo sync -c`
        #    was used to sync the `manifest` or `manifest-internal` repos.
        #
        # 2. Unpinned manifests - These manifests don't have a stable identifier
        #    that can represent the entire repo state. The manifests points to
        #    branches and those branches all sync asynchronously. There is also
        #    no way to go back in history. Git super-projects solve this by
        #    providing a stable identifier, but we aren't using that right now.
        #    Unpinned manifests are used when working on ToT, a factory branch,
        #    etc. When working on ToT, we make the assumption that the
        #    `snapshot`/`stable` ref is a close approximation of the repository
        #    state. For non-main branches, this assumption doesn't hold true.
        #    The `stable`/`snapshot` refs might not even exist if a
        #    `repo sync -c` was performed.
        if not branch in ["main", "snapshot", "stable"]:
            logging.info(
                "Manifest is not tracking main, skipping lookup service."
            )
            # Fall back to using the POSTSUBMIT binhost make.conf from the
            # repository.
            return []

        # Get snapshot SHAs from the git log.
        snapshot_shas_combined = _get_snapshot_shas()

        manifest = repo.Manifest()

        if manifest.HasRemote(
            site_params.INTERNAL_REMOTE
        ) and manifest.HasRemote(site_params.EXTERNAL_REMOTE):
            # Googlers
            if snapshot_shas_combined.internal:
                snapshot_shas = snapshot_shas_combined.internal
                get_corresponding_binhosts = True
                private = True
            # Partners
            else:
                snapshot_shas = snapshot_shas_combined.external
                get_corresponding_binhosts = True
                private = False
        # External Developers
        else:
            snapshot_shas = snapshot_shas_combined.external
            get_corresponding_binhosts = False
            private = False

    # Get generic build target.
    board_root = sysroot_lib.Sysroot(build_target.root)
    base_board = board_root.GetBaseArchBoard()

    binhost_gs_uris = _fetch_binhosts(
        snapshot_shas,
        build_target.name,
        build_target.profile or "base",
        private,
        get_corresponding_binhosts,
        base_board,
        "base",
        is_staging,
    )
    binhost_gs_uris.reverse()

    return binhost_gs_uris
