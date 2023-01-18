# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utility for performing Android uprev."""

import json
import logging
import os
import re
import time
from typing import Dict, Optional, Tuple, Union

from chromite.lib import constants
from chromite.lib import gs


# Regex patterns of artifacts to copy for each branch and build target.
ARTIFACTS_TO_COPY = {
    constants.ANDROID_PI_BUILD_BRANCH: {
        # Roll XkbToKcmConverter with system image. It's a host executable and
        # doesn't depend on the target as long as it's pi-arc branch. The
        # converter is ARC specific and not a part of Android SDK. Having a
        # custom target like SDK_TOOLS might be better in the long term, but
        # let's use one from ARM or X86 target as there's no other similar
        # executables right now.  We put it in two buckets because we have
        # separate ACLs for arm and x86.  http://b/128405786
        "apps": "org.chromium.arc.cachebuilder.jar",
        "cheets_arm-user": r"(\.zip|/XkbToKcmConverter)$",
        "cheets_arm64-user": r"(\.zip|/XkbToKcmConverter)$",
        "cheets_x86-user": r"(\.zip|/XkbToKcmConverter)$",
        "cheets_x86_64-user": r"\.zip$",
        "cheets_arm-userdebug": r"\.zip$",
        "cheets_arm64-userdebug": r"\.zip$",
        "cheets_x86-userdebug": r"\.zip$",
        "cheets_x86_64-userdebug": r"\.zip$",
        "sdk_cheets_x86-userdebug": r"\.zip$",
        "sdk_cheets_x86_64-userdebug": r"\.zip$",
    },
    constants.ANDROID_VMRVC_BUILD_BRANCH: {
        # For XkbToKcmConverter, see the comment in pi-arc targets.
        # org.chromium.cts.helpers.apk contains helpers needed for CTS.  It is
        # installed on the board, but not into the VM.
        "apps": "org.chromium.arc.cachebuilder.jar",
        "bertha_arm64-user": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_x86_64-user": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_arm64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_x86_64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
    },
    constants.ANDROID_VMSC_BUILD_BRANCH: {
        # For XkbToKcmConverter, see the comment in pi-arc targets.
        # org.chromium.cts.helpers.apk contains helpers needed for CTS.  It is
        # installed on the board, but not into the VM.
        "bertha_arm64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_x86_64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
    },
    constants.ANDROID_VMTM_BUILD_BRANCH: {
        # For XkbToKcmConverter, see the comment in pi-arc targets.
        # org.chromium.cts.helpers.apk contains helpers needed for CTS.  It is
        # installed on the board, but not into the VM.
        "bertha_arm64-user": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_x86_64-user": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_arm64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_x86_64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
    },
    constants.ANDROID_VMUDC_BUILD_BRANCH: {
        # For XkbToKcmConverter, see the comment in pi-arc targets.
        # org.chromium.cts.helpers.apk contains helpers needed for CTS.  It is
        # installed on the board, but not into the VM.
        "bertha_arm64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
        "bertha_x86_64-userdebug": (
            r"(\.zip|/XkbToKcmConverter" r"|/org.chromium.arc.cts.helpers.apk)$"
        ),
    },
}

# The bucket where Android infra publishes build artifacts. Files are only kept
# for 90 days.
ANDROID_BUCKET_URL = "gs://android-build-chromeos/builds"

# ACL definition files that live under the Portage package directory.
# We set ACLs when copying Android artifacts to the ARC bucket, using
# definitions for corresponding architecture (and public for the `apps` target).
ARC_BUCKET_ACL_ARM = "googlestorage_acl_arm.txt"
ARC_BUCKET_ACL_X86 = "googlestorage_acl_x86.txt"
ARC_BUCKET_ACL_PUBLIC = "googlestorage_acl_public.txt"


# The overlay that hosts Android packages.
OVERLAY_DIR = os.path.join(
    constants.SOURCE_ROOT, "src", "private-overlays", "project-cheets-private"
)


def GetAndroidPackageDir(
    android_package: str, overlay_dir: str = OVERLAY_DIR
) -> str:
    """Returns the Portage package directory of the given Android package.

    Args:
      android_package: the Android package name e.g. 'android-vm-rvc'
      overlay_dir: specify to override the default overlay.

    Returns:
      The Portage package directory
    """
    return os.path.join(overlay_dir, "chromeos-base", android_package)


def GetAndroidBranchForPackage(android_package: str) -> str:
    """Returns the corresponding Android branch of given Android package.

    Args:
      android_package: the Android package name e.g. 'android-vm-rvc'

    Returns:
      The corresponding Android branch e.g. 'git_rvc-arc'
    """
    mapping = {
        constants.ANDROID_PI_PACKAGE: constants.ANDROID_PI_BUILD_BRANCH,
        constants.ANDROID_VMRVC_PACKAGE: constants.ANDROID_VMRVC_BUILD_BRANCH,
        constants.ANDROID_VMSC_PACKAGE: constants.ANDROID_VMSC_BUILD_BRANCH,
        constants.ANDROID_VMTM_PACKAGE: constants.ANDROID_VMTM_BUILD_BRANCH,
        constants.ANDROID_VMUDC_PACKAGE: constants.ANDROID_VMUDC_BUILD_BRANCH,
    }
    try:
        return mapping[android_package]
    except KeyError:
        raise ValueError(f'Unknown Android package "{android_package}"')


def IsBuildIdValid(
    build_branch: str, build_id: str, bucket_url: str = ANDROID_BUCKET_URL
) -> Optional[dict]:
    """Checks that a specific build_id is valid.

    Looks for that build_id for all builds. Confirms that the subpath can
    be found and that the zip file is present in that subdirectory.

    Args:
      build_branch: branch of Android builds
      build_id: A string. The Android build id number to check.
      bucket_url: URL of Android build gs bucket

    Returns:
      Returns subpaths dictionary if build_id is valid.
      None if the build_id is not valid.
    """
    targets = ARTIFACTS_TO_COPY[build_branch]
    gs_context = gs.GSContext()
    subpaths_dict = {}
    for target in targets:
        build_dir = f"{build_branch}-linux-{target}"
        build_id_path = os.path.join(bucket_url, build_dir, build_id)

        # Find name of subpath.
        try:
            subpaths = gs_context.List(build_id_path)
        except gs.GSNoSuchKey:
            logging.warning(
                "Directory [%s] does not contain any subpath, ignoring it.",
                build_id_path,
            )
            return None
        # b/215041592: Sometimes there can be multiple subpaths which presumably
        # contain the exact same artifacts.
        if len(subpaths) > 1:
            logging.warning(
                "Directory [%s] contains more than one subpath, using the first one.",
                build_id_path,
            )

        subpath_dir = subpaths[0].url.rstrip("/")
        subpath_name = os.path.basename(subpath_dir)

        # Look for a zipfile ending in the build_id number.
        try:
            gs_context.List(subpath_dir)
        except gs.GSNoSuchKey:
            logging.warning(
                "Did not find a file for build id [%s] in directory [%s].",
                build_id,
                subpath_dir,
            )
            return None

        # Record subpath for the target.
        subpaths_dict[target] = subpath_name

    # If we got here, it means we found an appropriate build for all platforms.
    return subpaths_dict


def GetLatestBuild(
    build_branch: str, bucket_url: str = ANDROID_BUCKET_URL
) -> Union[Tuple[None, None], Tuple[str, dict]]:
    """Searches the gs bucket for the latest green build.

    Args:
      build_branch: branch of Android builds
      bucket_url: URL of Android build gs bucket

    Returns:
      Tuple of (latest version string, subpaths dictionary)
      If no latest build can be found, returns None, None
    """
    targets = ARTIFACTS_TO_COPY[build_branch]
    gs_context = gs.GSContext()
    common_build_ids = None
    # Find builds for each target.
    for target in targets:
        build_dir = f"{build_branch}-linux-{target}"
        base_path = os.path.join(bucket_url, build_dir)
        build_ids = []
        for gs_result in gs_context.List(base_path):
            # Remove trailing slashes and get the base name, which is the build_id.
            build_id = os.path.basename(gs_result.url.rstrip("/"))
            if not build_id.isdigit():
                logging.warning(
                    "Directory [%s] does not look like a valid build_id.",
                    gs_result.url,
                )
                continue
            build_ids.append(build_id)

        # Update current list of builds.
        if common_build_ids is None:
            # First run, populate it with the first platform.
            common_build_ids = set(build_ids)
        else:
            # Already populated, find the ones that are common.
            common_build_ids.intersection_update(build_ids)

    if common_build_ids is None:
        logging.warning("Did not find a build_id common to all platforms.")
        return None, None

    # Otherwise, find the most recent one that is valid.
    for build_id in sorted(common_build_ids, key=int, reverse=True):
        subpaths = IsBuildIdValid(build_branch, build_id, bucket_url)
        if subpaths:
            return build_id, subpaths

    # If not found, no build_id is valid.
    logging.warning("Did not find a build_id valid on all platforms.")
    return None, None


def _GetAcl(target: str, package_dir: str) -> str:
    """Returns the path to ACL file corresponding to target.

    Args:
      target: Android build target.
      package_dir: Path to the Android portage package.

    Returns:
      Path to the ACL definition file.
    """
    if "arm" in target:
        return os.path.join(package_dir, ARC_BUCKET_ACL_ARM)
    if "x86" in target:
        return os.path.join(package_dir, ARC_BUCKET_ACL_X86)
    if target == "apps":
        return os.path.join(package_dir, ARC_BUCKET_ACL_PUBLIC)
    raise ValueError(f"Unknown target {target}")


def CopyToArcBucket(
    android_bucket_url: str,
    build_branch: str,
    build_id: str,
    subpaths: Dict[str, str],
    arc_bucket_url: str,
    package_dir: str,
) -> None:
    """Copies from source Android bucket to ARC++ specific bucket.

    Copies each build to the ARC bucket eliminating the subpath.
    Applies build specific ACLs for each file.

    Args:
      android_bucket_url: URL of Android build gs bucket
      build_branch: branch of Android builds
      build_id: A string. The Android build id number to check.
      subpaths: Subpath dictionary for each build to copy.
      arc_bucket_url: URL of the target ARC build gs bucket
      package_dir: Path to the Android portage package.
    """
    targets = ARTIFACTS_TO_COPY[build_branch]
    gs_context = gs.GSContext()
    for target, pattern in targets.items():
        subpath = subpaths[target]
        build_dir = f"{build_branch}-linux-{target}"
        android_dir = os.path.join(
            android_bucket_url, build_dir, build_id, subpath
        )
        arc_dir = os.path.join(arc_bucket_url, build_dir, build_id)
        acl = _GetAcl(target, package_dir)

        # Copy all target files from android_dir to arc_dir, setting ACLs.
        for targetfile in gs_context.List(android_dir):
            if re.search(pattern, targetfile.url):
                arc_path = os.path.join(
                    arc_dir, os.path.basename(targetfile.url)
                )
                needs_copy = True
                retry_count = 2

                # Retry in case race condition when several boards trying to copy the
                # same resource
                while True:
                    # Check a pre-existing file with the original source.
                    if gs_context.Exists(arc_path):
                        if (
                            gs_context.Stat(targetfile.url).hash_crc32c
                            != gs_context.Stat(arc_path).hash_crc32c
                        ):
                            logging.warning(
                                "Removing incorrect file %s", arc_path
                            )
                            gs_context.Remove(arc_path)
                        else:
                            logging.info(
                                "Skipping already copied file %s", arc_path
                            )
                            needs_copy = False

                    # Copy if necessary, and set the ACL unconditionally.
                    # The Stat() call above doesn't verify the ACL is correct and
                    # the ChangeACL should be relatively cheap compared to the copy.
                    # This covers the following caes:
                    # - handling an interrupted copy from a previous run.
                    # - rerunning the copy in case one of the googlestorage_acl_X.txt
                    #   files changes (e.g. we add a new variant which reuses a build).
                    if needs_copy:
                        logging.info(
                            "Copying %s -> %s (acl %s)",
                            targetfile.url,
                            arc_path,
                            acl,
                        )
                        try:
                            gs_context.Copy(targetfile.url, arc_path, version=0)
                        except gs.GSContextPreconditionFailed as error:
                            if not retry_count:
                                raise error
                            # Retry one more time after a short delay
                            logging.warning(
                                "Will retry copying %s -> %s",
                                targetfile.url,
                                arc_path,
                            )
                            time.sleep(5)
                            retry_count = retry_count - 1
                            continue
                    gs_context.ChangeACL(arc_path, acl_args_file=acl)
                    break


def MirrorArtifacts(
    android_bucket_url: str,
    android_build_branch: str,
    arc_bucket_url: str,
    package_dir: str,
    version: Optional[str] = None,
) -> Optional[str]:
    """Mirrors artifacts from Android bucket to ARC bucket.

    First, this function identifies which build version should be copied,
    if not given. Please see GetLatestBuild() and IsBuildIdValid() for details.

    On build version identified, then copies target artifacts to the ARC bucket,
    with setting ACLs.

    Args:
      android_bucket_url: URL of Android build gs bucket
      android_build_branch: branch of Android builds
      arc_bucket_url: URL of the target ARC build gs bucket
      package_dir: Path to the Android portage package.
      version: A string. The Android build id number to check.
          If not passed, detect latest good build version.

    Returns:
      Mirrored version.
    """
    if version:
        subpaths = IsBuildIdValid(
            android_build_branch, version, android_bucket_url
        )
        if not subpaths:
            logging.error("Requested build %s is not valid", version)
    else:
        version, subpaths = GetLatestBuild(
            android_build_branch, android_bucket_url
        )

    CopyToArcBucket(
        android_bucket_url,
        android_build_branch,
        version,
        subpaths,
        arc_bucket_url,
        package_dir,
    )

    return version


_LKGB_JSON = "LKGB.json"


class MissingLKGBError(Exception):
    """LKGB file for the given Android package is missing."""


class InvalidLKGBError(Exception):
    """LKGB file for the given Android package contains invalid content."""


def LKGB(
    build_id: str,
    runtime_artifacts_pin: Optional[str] = None,
    **kwargs,
) -> dict:
    """Constructs an "LKGB object".

    The LKGB object is basically a dict with additional handling for optional
    keys to make sure two LKGB objects are comparable, and to discard unwanted
    fields from the JSON file (absorbed by **kwargs).

    Args:
        build_id: The last known good Android build ID.
        runtime_artifacts_pin: (Optional) The runtime artifacts pin, if present.

    Returns:
        The constructed LKGB object.
    """
    del kwargs  # Delete unused var to make pylint happy.

    lkgb = dict(build_id=build_id)
    if runtime_artifacts_pin is not None:
        lkgb["runtime_artifacts_pin"] = runtime_artifacts_pin
    return lkgb


def WriteLKGB(android_package_dir: str, lkgb: dict) -> str:
    """Writes the LKGB file under the given Android package directory.

    Args:
      android_package_dir: The Android package directory.
      lkgb: The LKGB object; see LKGB().

    Returns:
      Path to the updated file.
    """
    path = os.path.join(android_package_dir, _LKGB_JSON)
    with open(path, "w") as f:
        json.dump(lkgb, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def ReadLKGB(android_package_dir: str) -> dict:
    """Reads the LKGB file under the given Android package directory.

    See LKGB() for possible fields in the dict; if additional fields are found
    in the LKGB file, they are silently discarded without triggering an error.

    Args:
      android_package_dir: The Android package directory.

    Returns:
      An LKGB object from the file; see LKGB().

    Raises:
      MissingLKGBError: If the LKGB file is not found under android_package_dir.
      InvalidLKGBError: If the LKGB file contains invalid content.
    """
    path = os.path.join(android_package_dir, _LKGB_JSON)
    if not os.path.exists(path):
        raise MissingLKGBError(path)

    try:
        with open(path, "r") as f:
            lkgb = json.load(f)
    except json.JSONDecodeError as e:
        raise InvalidLKGBError("Error decoding LKGB file as JSON: " + str(e))

    if "build_id" not in lkgb:
        raise InvalidLKGBError("Field build_id not found in LKGB file")
    return LKGB(**lkgb)


_RUNTIME_ARTIFACTS_BUCKET_URL = "gs://chromeos-arc-images/runtime_artifacts"


def FindRuntimeArtifactsPin(
    android_branch: str,
    runtime_artifacts_bucket_url: Optional[str] = _RUNTIME_ARTIFACTS_BUCKET_URL,
) -> Optional[str]:
    """Finds the runtime artifacts pin for given package/milestone, if present.

    TODO(b/258558620): The code here is intentionally duplicated from
    cros_mark_android_as_stable.py to maximize cherry-pick-ability. Refactor
    away dupe code on main branch.

    Args:
        android_branch: The Android branch.
        runtime_artifacts_bucket_url: URL of the runtime artifacts bucket.

    Returns:
        The pinned version, or None if not present.
    """
    gs_context = gs.GSContext()
    pin_path = f"{runtime_artifacts_bucket_url}/{android_branch}_pin_version"
    if not gs_context.Exists(pin_path):
        return None

    return gs_context.Cat(pin_path, encoding="utf-8").rstrip()
