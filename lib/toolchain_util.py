# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Toolchain and related functionality."""

import base64
import collections
import datetime
import glob
import json
import logging
import os
import re
import shutil
from typing import Any, Callable, Iterable, Optional

from chromite.lib import alerts
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import gob_util
from chromite.lib import gs
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.lib.parser import package_info
from chromite.utils import pformat


class PrepareForBuildReturn(object):
    """Return values for PrepareForBuild call."""

    UNSPECIFIED = 0
    # Build is necessary to generate artifacts.
    NEEDED = 1
    # Defer to other artifacts.  Used primarily for aggregation of artifact
    # results.
    UNKNOWN = 2
    # Artifacts are already generated.  The build is pointless.
    POINTLESS = 3


# URLs
# FIXME(tcwang): Remove access to GS buckets from this lib.
# There are plans in the future to remove all network
# operations from chromite, including access to GS buckets.
# Need to use build API and recipes to communicate to GS buckets in
# the future.
ORDERFILE_GS_URL_UNVETTED = (
    "gs://chromeos-toolchain-artifacts/orderfile/unvetted"
)
BENCHMARK_AFDO_GS_URL = (
    "gs://chromeos-toolchain-artifacts/afdo/unvetted/benchmark"
)
CWP_AFDO_GS_URL = "gs://chromeos-prebuilt/afdo-job/cwp/chrome/"
KERNEL_PROFILE_URL = "gs://chromeos-prebuilt/afdo-job/cwp/kernel/"
KERNEL_ARM_PROFILE_URL = os.path.join(KERNEL_PROFILE_URL, "arm")
AFDO_GS_URL_VETTED = "gs://chromeos-prebuilt/afdo-job/vetted/"
KERNEL_AFDO_GS_URL_VETTED = os.path.join(AFDO_GS_URL_VETTED, "kernel")
RELEASE_AFDO_GS_URL_VETTED = os.path.join(AFDO_GS_URL_VETTED, "release")
KERNEL_ARM_AFDO_GS_URL_VETTED = os.path.join(KERNEL_AFDO_GS_URL_VETTED, "arm")

# Constants
AFDO_SUFFIX = ".afdo"
BZ2_COMPRESSION_SUFFIX = ".bz2"
XZ_COMPRESSION_SUFFIX = ".xz"
KERNEL_AFDO_COMPRESSION_SUFFIX = ".gcov.xz"
# FIXME: we should only use constants.SOURCE_ROOT and use
# path_util.ToChrootPath to convert to inchroot path when needed. So we
# need fix all the use cases for this variable (we can remove all but one
# when legacy is retired).
TOOLCHAIN_UTILS_PATH = os.path.join(
    constants.CHROOT_SOURCE_ROOT, "src/third_party/toolchain-utils"
)
AFDO_PROFILE_PATH_IN_CHROMIUM = "src/chromeos/profiles/%s.afdo.newest.txt"
MERGED_AFDO_NAME = "chromeos-chrome-{arch}-{name}"

# How old can the Kernel AFDO data be? (in days).
KERNEL_ALLOWED_STALE_DAYS = 42
# How old can the Kernel AFDO data be before detective got noticed? (in days).
KERNEL_WARN_STALE_DAYS = 14
# How old an Arm profile can be before it gets replaced with atom.
CHROME_ARM_CWP_ALLOWED_STALE_DAYS = 21

# For merging release Chrome profiles.
RELEASE_CWP_MERGE_WEIGHT = 75
RELEASE_BENCHMARK_MERGE_WEIGHT = 100 - RELEASE_CWP_MERGE_WEIGHT

# Paths used in AFDO generation.
_AFDO_GENERATE_LLVM_PROF = "/usr/bin/create_llvm_prof"
_CHROME_DEBUG_BIN = os.path.join(
    "%(root)s", "%(sysroot)s/usr/lib/debug", "opt/google/chrome/chrome.debug"
)

# Set of boards that can generate the AFDO profile (can generate 'perf'
# data with LBR events). Currently, it needs to be a device that has
# at least 4GB of memory.
#
# This must be consistent with the definitions in autotest.
CHROME_AFDO_VERIFIER_BOARDS = {"chell": "atom", "eve": "bigcore"}

AFDO_ALERT_RECIPIENTS = ["chromeos-toolchain-oncall1@google.com"]

# Full path to the chromiumos-overlay directory.
_CHROMIUMOS_OVERLAY = os.path.join(
    constants.CHROMITE_DIR, "..", constants.CHROMIUMOS_OVERLAY_DIR
)

# RegExps
AFDO_ARTIFACT_EBUILD_REGEX = r'(?P<bef>%s=)(?P<name>("[^"]*"|.*))(?P<aft>.*)'
AFDO_ARTIFACT_EBUILD_REPL = r'\g<bef>"%s"\g<aft>'

ChromeVersion = collections.namedtuple(
    "ChromeVersion", ["major", "minor", "build", "patch", "revision"]
)

BENCHMARK_PROFILE_NAME_REGEX = r"""
       ^chromeos-chrome-(?:\w+)-
       (\d+)\.                    # Major
       (\d+)\.                    # Minor
       (\d+)\.                    # Build
       (\d+)                      # Patch
       (?:_rc)?-r(\d+)            # Revision
       (-merged)?\.
       afdo(?:\.bz2)?$            # We don't care about the presence of .bz2,
                                  # so we use the ignore-group '?:' operator.
"""

BenchmarkProfileVersion = collections.namedtuple(
    "BenchmarkProfileVersion",
    ["major", "minor", "build", "patch", "revision", "is_merged"],
)

CWP_PROFILE_NAME_REGEX = r"""
      ^R(\d+)-                      # Major
       (\d+)\.                      # Build
       (\d+)-                       # Patch
       (\d+)                        # Clock; breaks ties sometimes.
       (?:\.afdo|\.gcov)?           # Optional: CWP for Chrome has `afdo`,
                                    # and kernel has `gcov`. Also this regex
                                    # is also used to match names in ebuild and
                                    # sometimes names in ebuild don't have
                                    # suffix.
       (?:\.xz)?$                   # We don't care about the presence of xz
    """

CWPProfileVersion = collections.namedtuple(
    "CWPProfileVersion", ["major", "build", "patch", "clock"]
)

MERGED_PROFILE_NAME_REGEX = r"""
      ^chromeos-chrome
      -(?:orderfile|amd64|arm)                   # prefix for either orderfile
                                                 # or release profile.
      # CWP parts
      -(?:field|atom|bigcore|none)               # Valid names
      -(\d+)                                     # Major
      -(\d+)                                     # Build
      \.(\d+)                                    # Patch
      -(\d+)                                     # Clock; breaks ties sometimes.
      # Benchmark parts
      -benchmark
      -(\d+)                                     # Major
      \.(\d+)                                    # Minor
      \.(\d+)                                    # Build
      \.(\d+)                                    # Patch
      -r(\d+)                                    # Revision
      (?:\.orderfile|-redacted\.afdo)            # suffix for either orderfile
                                                 # or release profile.
      (?:\.xz)?$
"""

CHROME_ARCH_VERSION = "%(package)s-%(arch)s-%(version)s"
CHROME_PERF_AFDO_FILE = "%(package)s-%(arch)s-%(versionnorev)s.perf.data"
CHROME_BENCHMARK_AFDO_FILE = "%s%s" % (CHROME_ARCH_VERSION, AFDO_SUFFIX)
CHROME_DEBUG_BINARY_NAME = "%s.debug" % CHROME_ARCH_VERSION


class Error(Exception):
    """Base module error class."""


class PrepareForBuildHandlerError(Error):
    """Error for PrepareForBuildHandler class."""


class BundleArtifactsHandlerError(Error):
    """Error for BundleArtifactsHandler class."""


class GetUpdatedFilesForCommitError(Error):
    """Error for GetUpdatedFilesForCommit class."""


class NoArtifactsToBundleError(Error):
    """Error for bundling empty collection of artifacts."""


class GenerateChromeOrderfileError(Error):
    """Error for GenerateChromeOrderfile class."""


class ProfilesNameHelperError(Error):
    """Error for helper functions related to profile naming."""


class UpdateEbuildWithAFDOArtifactsError(Error):
    """Error for UpdateEbuildWithAFDOArtifacts class."""


class NoProfilesInGsBucketError(Error):
    """Raised when _FindLatestAFDOArtifact doesn't find profiles."""


def _ParseBenchmarkProfileName(profile_name):
    """Parse the name of a benchmark profile for Chrome.

    Examples:
      with input: profile_name='chromeos-chrome-amd64-77.0.3849.0_rc-r1.afdo'
      the function returns:
      BenchmarkProfileVersion(
        major=77, minor=0, build=3849, patch=0, revision=1, is_merged=False)

    Args:
      profile_name: The name of a benchmark profile.

    Returns:
      Named tuple of BenchmarkProfileVersion if the profile is parsable

    Raises if the name is not parsable.
    """
    pattern = re.compile(BENCHMARK_PROFILE_NAME_REGEX, re.VERBOSE)
    match = pattern.match(profile_name)
    if not match:
        raise ProfilesNameHelperError(
            "Unparseable benchmark profile name: %s" % profile_name
        )

    groups = match.groups()
    version_groups = groups[:-1]
    is_merged = groups[-1]
    return BenchmarkProfileVersion(
        *[int(x) for x in version_groups], is_merged=bool(is_merged)
    )


def _ParseCWPProfileName(profile_name):
    """Parse the name of a CWP profile for Chrome.

    Examples:
      With input profile_name='R77-3809.38-1562580965.afdo',
      the function returns:
      CWPProfileVersion(major=77, build=3809, patch=38, clock=1562580965)

    Args:
      profile_name: The name of a CWP profile.

    Returns:
      Named tuple of CWPProfileVersion.
    """
    pattern = re.compile(CWP_PROFILE_NAME_REGEX, re.VERBOSE)
    match = pattern.match(profile_name)
    if not match:
        raise ProfilesNameHelperError(
            "Unparseable CWP profile name: %s" % profile_name
        )
    return CWPProfileVersion(*[int(x) for x in match.groups()])


def _ParseMergedProfileName(artifact_name):
    """Parse the name of an orderfile or a release profile for Chrome.

    Examples:
      With input: profile_name='chromeos-chrome-orderfile
      -field-77-3809.38-1562580965
      -benchmark-77.0.3849.0_rc-r1.orderfile.xz'
      the function returns:
      (BenchmarkProfileVersion(
       major=77, minor=0, build=3849, patch=0, revision=1, is_merged=False),
       CWPProfileVersion(major=77, build=3809, patch=38, clock=1562580965))

    Args:
      artifact_name: The name of an orderfile, or a release AFDO profile.

    Returns:
      A tuple of (BenchmarkProfileVersion, CWPProfileVersion)
    """
    pattern = re.compile(MERGED_PROFILE_NAME_REGEX, re.VERBOSE)
    match = pattern.match(artifact_name)
    if not match:
        raise ProfilesNameHelperError(
            "Unparseable merged AFDO name: %s" % artifact_name
        )
    groups = match.groups()
    cwp_groups = groups[:4]
    benchmark_groups = groups[4:]
    return (
        BenchmarkProfileVersion(
            *[int(x) for x in benchmark_groups], is_merged=False
        ),
        CWPProfileVersion(*[int(x) for x in cwp_groups]),
    )


def _GetArtifactVersionInChromium(arch, chrome_root):
    """Find the version (name) of AFDO artifact from chromium source.

    Args:
      arch: There are two AFDO profiles in chromium: atom or bigcore
      chrome_root: The path to Chrome root.

    Returns:
      The name of the AFDO artifact found in the chroot.
      None if not found.

    Raises:
      ValueError: when "arch" is not a supported.
      RuntimeError: when the file containing AFDO profile name can't be found.
    """
    if arch not in list(CHROME_AFDO_VERIFIER_BOARDS.values()):
        raise ValueError(
            "Invalid architecture %s to use in AFDO profile" % arch
        )

    if not os.path.exists(chrome_root):
        raise RuntimeError("chrome_root %s does not exist." % chrome_root)

    profile_file = os.path.join(
        chrome_root, AFDO_PROFILE_PATH_IN_CHROMIUM % arch
    )
    if not os.path.exists(profile_file):
        logging.info(
            "Files in chrome_root profile: %r",
            os.listdir(
                os.path.join(
                    chrome_root, AFDO_PROFILE_PATH_IN_CHROMIUM % arch, ".."
                )
            ),
        )
        raise RuntimeError(
            "File %s containing profile name does not exist" % (profile_file,)
        )

    return osutils.ReadFile(profile_file)


def _GetCombinedAFDOName(cwp_versions, cwp_arch, benchmark_versions):
    """Construct a name mixing CWP and benchmark AFDO names.

    Examples:
      If benchmark AFDO is BenchmarkProfileVersion(
        major=77, minor=0, build=3849, patch=0, revision=1, is_merged=False)
      and CWP AFDO is CWPProfileVersion(
        major=77, build=3809, patch=38, clock=1562580965),
      and cwp_arch is 'atom',
      the returned name is:
      atom-77-3809.38-1562580965-benchmark-77.0.3849.0-r1

    Args:
      cwp_versions: CWP profile as a namedtuple CWPProfileVersion.
      cwp_arch: Architecture used to differentiate CWP profiles.
      benchmark_versions: Benchmark profile as a namedtuple
      BenchmarkProfileVersion.

    Returns:
      A name using the combination of CWP + benchmark AFDO names.
    """
    cwp_piece = "%s-%d-%d.%d-%d" % (
        cwp_arch,
        cwp_versions.major,
        cwp_versions.build,
        cwp_versions.patch,
        cwp_versions.clock,
    )
    benchmark_piece = "benchmark-%d.%d.%d.%d-r%d" % (
        benchmark_versions.major,
        benchmark_versions.minor,
        benchmark_versions.build,
        benchmark_versions.patch,
        benchmark_versions.revision,
    )
    return "%s-%s" % (cwp_piece, benchmark_piece)


def _GetOrderfileName(chrome_root):
    """Construct an orderfile name for the current Chrome OS checkout.

    Args:
      chrome_root: The path to chrome_root.

    Returns:
      An orderfile name using CWP + benchmark AFDO name.
    """
    benchmark_afdo_version, cwp_afdo_version = _ParseMergedProfileName(
        _GetArtifactVersionInChromium(arch="atom", chrome_root=chrome_root)
    )
    return "chromeos-chrome-orderfile-%s" % (
        _GetCombinedAFDOName(cwp_afdo_version, "field", benchmark_afdo_version)
    )


def _CompressAFDOFiles(targets, input_dir, output_dir, suffix):
    """Compress files using AFDO compression type.

    Args:
      targets: List of files to compress. Only the basename is needed.
      input_dir: Paths to the targets (outside chroot). If None, use
      the targets as full path.
      output_dir: Paths to save the compressed file (outside chroot).
      suffix: Compression suffix.

    Returns:
      List of full paths of the generated tarballs.

    Raises:
      RuntimeError if the file to compress does not exist.
    """
    ret = []
    for t in targets:
        name = os.path.basename(t)
        compressed = name + suffix
        if input_dir:
            input_path = os.path.join(input_dir, name)
        else:
            input_path = t
        if not os.path.exists(input_path):
            raise RuntimeError(
                "file %s to compress does not exist" % input_path
            )
        output_path = os.path.join(output_dir, compressed)
        cros_build_lib.CompressFile(input_path, output_path)
        logging.info(
            "_CompressAFDOFiles produced %s, size %.1fMB",
            output_path,
            os.path.getsize(output_path) / (1024 * 1024),
        )
        ret.append(output_path)
    return ret


# TODO(b/187794927): Refactor the class.
# The class was shared with the legacy builders. Legacy was removed and
# now we can merge this code into the BundleArtifactHandler class.
class GenerateChromeOrderfile(object):
    """Class to handle generation of orderfile for Chrome.

    This class takes orderfile containing symbols ordered by Call-Chain
    Clustering (C3), produced when linking Chrome, and uses a toolchain
    script to perform post processing to generate an orderfile that can
    be used for linking Chrome and creates tarball. The output of this
    script is a tarball of the orderfile and a tarball of the NM output
    of the built Chrome binary.

    The whole class runs outside chroot, so use paths relative outside
    chroot, except the functions noted otherwise.
    """

    PROCESS_SCRIPT = os.path.join(
        TOOLCHAIN_UTILS_PATH, "orderfile/post_process_orderfile.py"
    )
    CHROME_BINARY_PATH = (
        "/var/cache/chromeos-chrome/chrome-src-internal/"
        "src/out_${BOARD}/Release/chrome"
    )
    INPUT_ORDERFILE_PATH = (
        "/build/${BOARD}/opt/google/chrome/chrome.orderfile.txt"
    )

    def __init__(
        self, board, output_dir, chrome_root, chroot_path, chroot_args
    ):
        """Construct an object for generating orderfile for Chrome.

        Args:
          board: Name of the board.
          output_dir: Directory (outside chroot) to save the output artifacts.
          chrome_root: Path to the Chrome source.
          chroot_path: Path to the chroot.
          chroot_args: The arguments used to enter the chroot.
        """
        self.output_dir = output_dir
        self.orderfile_name = _GetOrderfileName(chrome_root)
        self.chrome_binary = self.CHROME_BINARY_PATH.replace("${BOARD}", board)
        self.input_orderfile = self.INPUT_ORDERFILE_PATH.replace(
            "${BOARD}", board
        )
        self.chroot_path = chroot_path
        self.working_dir = os.path.join(self.chroot_path, "tmp")
        self.working_dir_inchroot = "/tmp"
        self.chroot_args = chroot_args
        self.tarballs = []

    def _CheckArguments(self):
        """Make sure the arguments received are correct."""
        if not os.path.isdir(self.output_dir):
            raise GenerateChromeOrderfileError(
                "Non-existent directory %s specified for --out-dir"
                % (self.output_dir,)
            )

        chrome_binary_path_outside = os.path.join(
            self.chroot_path, self.chrome_binary[1:]
        )
        if not os.path.exists(chrome_binary_path_outside):
            raise GenerateChromeOrderfileError(
                "Chrome binary does not exist at %s in chroot"
                % (chrome_binary_path_outside,)
            )

        chrome_orderfile_path_outside = os.path.join(
            self.chroot_path, self.input_orderfile[1:]
        )
        if not os.path.exists(chrome_orderfile_path_outside):
            raise GenerateChromeOrderfileError(
                "No orderfile generated in the builder."
            )

    def _GenerateChromeNM(self):
        """Generate symbols by running nm command on Chrome binary.

        This command runs inside chroot.
        """
        cmd = ["llvm-nm", "-n", self.chrome_binary]
        result_inchroot = os.path.join(
            self.working_dir_inchroot, self.orderfile_name + ".nm"
        )
        result_out_chroot = os.path.join(
            self.working_dir, self.orderfile_name + ".nm"
        )

        try:
            cros_build_lib.run(
                cmd,
                stdout=result_out_chroot,
                enter_chroot=True,
                chroot_args=self.chroot_args,
            )
        except cros_build_lib.RunCommandError:
            raise GenerateChromeOrderfileError(
                "Unable to run %s to get nm on Chrome binary" % (cmd)
            )

        # Return path inside chroot
        return result_inchroot

    def _PostProcessOrderfile(self, chrome_nm):
        """Use toolchain script to do post-process on the orderfile.

        This command runs inside chroot.
        """
        result = os.path.join(
            self.working_dir_inchroot, self.orderfile_name + ".orderfile"
        )
        cmd = [
            self.PROCESS_SCRIPT,
            "--chrome",
            chrome_nm,
            "--input",
            self.input_orderfile,
            "--output",
            result,
        ]

        try:
            cros_build_lib.run(
                cmd,
                enter_chroot=True,
                chroot_args=self.chroot_args,
                check=True,
                capture_output=True,
            )
        except cros_build_lib.RunCommandError as e:
            raise GenerateChromeOrderfileError(
                f"Unable to run %s to process orderfile {cmd} "
                f"with error: {e.stdout} {e.stderr}."
            )

        # Return path inside chroot
        return result

    def Bundle(self):
        """Generate post-processed Chrome orderfile and create tarball."""
        self._CheckArguments()
        chrome_nm = self._GenerateChromeNM()
        orderfile = self._PostProcessOrderfile(chrome_nm)
        self.tarballs = _CompressAFDOFiles(
            [chrome_nm, orderfile],
            self.working_dir,
            self.output_dir,
            XZ_COMPRESSION_SUFFIX,
        )


def _RankValidCWPProfiles(name: str) -> int:
    """Calculate a value used to rank valid CWP profiles.

    Args:
      name: A name or a full path of a possible CWP profile.

    Returns:
      The "clock" part of the CWP profile, used for ranking if the
      name is a valid CWP profile. Otherwise, returns None.
    """
    try:
        return _ParseCWPProfileName(os.path.basename(name)).clock
    except ProfilesNameHelperError:
        return None


def _GetProfileAge(profile: str, artifact_type: str) -> int:
    """Tell the age of profile_version in days.

    Args:
      profile: Name of the profile. Different artifact_type has different
      format. For kernel_afdo, it looks like: R78-12371.11-1565602499.
      The last part is the timestamp.
      artifact_type: Only 'kernel_afdo' and 'cwp' are supported now.

    Returns:
      Age of profile_version in days.

    Raises:
      ValueError: if the artifact_type is not supported.
    """
    if artifact_type in ("kernel_afdo", "cwp"):
        return (
            datetime.datetime.now(tz=datetime.timezone.utc)
            - datetime.datetime.fromtimestamp(
                int(profile.split("-")[-1]), datetime.timezone.utc
            )
        ).days

    raise ValueError(
        f"'{artifact_type}' is currently not supported to check profile age."
    )


def _WarnDetectiveAboutKernelProfileExpiration(
    kver: str, profile_path: str
) -> None:
    """Send emails to toolchain detective to warn the soon expired profiles.

    Args:
      kver: Kernel version.
      profile_path: Absolute path to the profile.
    """
    subject_msg = (
        f"[Test Async builder] Kernel AutoFDO profile too old for kernel {kver}"
    )
    alert_msg = (
        f"The latest AutoFDO profile is too old for the kernel {kver}.\n"
        f"Path={profile_path}.\n"
        "Check if this is a known bug at "
        "https://buganizer.corp.google.com/issues?q=componentid:87200"
        "%20%22AutoFDO%20profile%20generation%20for%20kernel%22 or contact "
        "the cwp-team@google.com."
    )
    alerts.SendEmailLog(
        subject_msg,
        AFDO_ALERT_RECIPIENTS,
        message=alert_msg,
    )


_EbuildInfo = collections.namedtuple("_EbuildInfo", ["path", "CPV"])


class _CommonPrepareBundle(object):
    """Information about Ebuild files we care about."""

    def __init__(
        self,
        artifact_name,
        chroot=None,
        sysroot_path=None,
        build_target=None,
        input_artifacts=None,
        profile_info=None,
    ):
        self._gs_context = None
        self.artifact_name = artifact_name
        self.chroot = chroot
        self.sysroot_path = sysroot_path
        self.build_target = build_target
        self.input_artifacts = input_artifacts or {}
        self.profile_info = profile_info or {}
        # TODO(b/246457583): Pass arch, uarch, and kernel in proto.
        profile = self.profile_info.get("chrome_cwp_profile")
        if profile in ("atom", "bigcore"):
            self.arch = "amd64"
            self.uarch = profile
        elif profile in ("arm", "arm32"):
            self.arch = "arm"
            self.uarch = "armv7a" if profile == "arm32" else "none"
        else:
            # "chrome_cwp_profile" can be unset,
            # in this case default arch is amd64.
            self.arch = "amd64"
            self.uarch = None
        self._ebuild_info = {}

    @property
    def gs_context(self):
        """Get the current GS context.  May create one."""
        if not self._gs_context:
            self._gs_context = gs.GSContext()
        return self._gs_context

    @property
    def chrome_branch(self):
        """Return the branch number for chrome."""
        pkg = constants.CHROME_PN
        info = self._ebuild_info.get(pkg, self._GetEbuildInfo(pkg))
        return info.CPV.version.split(".")[0]

    def _GetEbuildInfo(
        self, package: str, category: Optional[str] = None
    ) -> _EbuildInfo:
        """Get the ebuild info for a cataegory/package in chromiumos-overlay.

        Args:
          package: package name (e.g. chromeos-chrome or chromeos-kernel-4_4)
          category: category (e.g. chromeos-base, or sys-kernel)

        Returns:
          _EbuildInfo for the stable ebuild.
        """
        if package in self._ebuild_info:
            return self._ebuild_info[package]

        if category is None:
            if package == constants.CHROME_PN:
                category = constants.CHROME_CN
            else:
                category = "sys-kernel"

        # The stable ebuild path has at least one '.' in the version.
        paths = glob.glob(
            os.path.join(_CHROMIUMOS_OVERLAY, category, package, "*-*.*.ebuild")
        )
        if len(paths) == 1:
            PV = os.path.splitext(os.path.split(paths[0])[1])[0]
            info = _EbuildInfo(
                paths[0], package_info.parse("%s/%s" % (category, PV))
            )
            self._ebuild_info[constants.CHROME_PN] = info
            return info
        else:
            latest_version = ChromeVersion(0, 0, 0, 0, 0)
            candidate = None
            for p in paths:
                PV = os.path.splitext(os.path.split(p)[1])[0]
                info = _EbuildInfo(
                    p, package_info.parse("%s/%s" % (category, PV))
                )
                if not info.CPV.revision:
                    # Ignore versions without a rev
                    continue
                version_re = re.compile(
                    r"^chromeos-chrome-(\d+)\.(\d+)\.(\d+)\.(\d+)_rc-r(\d+)"
                )
                m = version_re.search(PV)
                assert m, f"failed to recognize Chrome ebuild name {p}"
                version = ChromeVersion(*[int(x) for x in m.groups()])
                if version > latest_version:
                    latest_version = version
                    candidate = info
            if not candidate:
                raise PrepareForBuildHandlerError(
                    f"No valid Chrome ebuild found among: {paths}"
                )
            self._ebuild_info[constants.CHROME_PN] = candidate
            return candidate

    def _GetBenchmarkAFDOName(
        self, template=CHROME_BENCHMARK_AFDO_FILE, wildcard_version=False
    ):
        """Get the name of the benchmark AFDO file from the Chrome ebuild.

        wildcard_version=True replaces chrome version with *.
        """
        pkg = self._GetEbuildInfo(constants.CHROME_PN).CPV
        if wildcard_version:
            ver = "*"
            vernorev = "*"
        else:
            ver = pkg.vr
            vernorev = pkg.version.split("_")[0]
        afdo_spec = {
            "arch": self.arch,
            "package": pkg.package,
            "version": ver,
            "versionnorev": vernorev,
        }
        return template % afdo_spec

    def _GetArtifactVersionInGob(self, arch):
        """Find the version (name) of AFDO artifact from GoB.

        Args:
          arch: There are two AFDO profiles in chromium: atom or bigcore.

        Returns:
          The name of the AFDO artifact found on GoB, or None if not found.

        Raises:
          ValueError: when "arch" is not a supported.
          RuntimeError: when the file containing AFDO profile name can't be found.
        """
        if arch not in list(CHROME_AFDO_VERIFIER_BOARDS.values()):
            raise ValueError(
                "Invalid architecture %s to use in AFDO profile" % arch
            )

        chrome_info = self._GetEbuildInfo(constants.CHROME_PN)
        version = chrome_info.CPV.version
        if version.endswith("_rc"):
            version = version[:-3]
        profile_path = (
            "chromium/src/+/refs/tags/%s/chromeos/profiles/%s.afdo.newest.txt"
            "?format=text" % (version, arch)
        )

        contents = gob_util.FetchUrl(constants.EXTERNAL_GOB_HOST, profile_path)
        if not contents:
            raise RuntimeError(
                "Could not fetch https://%s/%s"
                % (constants.EXTERNAL_GOB_HOST, profile_path)
            )

        return base64.decodebytes(contents).decode("utf-8")

    def _GetArtifactVersionInEbuild(self, package, variable):
        """Find the version (name) of AFDO artifact from the ebuild.

        Args:
          package: name of the package (such as, 'chromeos-chrome')
          variable: name of the variable to find.

        Returns:
          The name of the AFDO artifact found in the ebuild, or None if not found.
        """
        info = self._GetEbuildInfo(package)
        ebuild = info.path
        pattern = re.compile(AFDO_ARTIFACT_EBUILD_REGEX % variable)
        with open(ebuild) as f:
            for line in f:
                match = pattern.search(line)
                if match:
                    ret = match.group("name")
                    if ret.startswith('"') and ret.endswith('"'):
                        return ret[1:-1]
                    return ret

        logging.info("%s is not found in the ebuild: %s", variable, ebuild)
        return None

    def _GetOrderfileName(self):
        """Get the name of the orderfile."""
        artifact_version = self._GetArtifactVersionInGob(arch="atom")
        logging.info("Orderfile artifact version = %s", artifact_version)
        benchmark_afdo, cwp_afdo = _ParseMergedProfileName(artifact_version)
        return "chromeos-chrome-orderfile-%s.orderfile" % (
            _GetCombinedAFDOName(cwp_afdo, "field", benchmark_afdo)
        )

    def _FindLatestOrderfileArtifact(self, gs_urls):
        """Find the latest Ordering file artifact in a bucket.

        Args:
          gs_urls: List of full gs:// directory paths to check.

        Returns:
          The path of the latest eligible ordering file artifact.

        Raises:
          See _FindLatestAFDOArtifact.
        """
        return self._FindLatestAFDOArtifact(
            gs_urls, self._ValidOrderfileVersion
        )

    def _FindLatestAFDOArtifact(
        self,
        gs_urls: Iterable[str],
        rank_func: Callable[[str], Any],
    ) -> str:
        """Find the latest AFDO artifact in a bucket.

        Args:
          gs_urls: List of full gs:// directory paths to check.
          rank_func: A function to compare two URLs.  It is passed two URLs, and
              returns whether the first is more or less preferred than the second:
                negative: less preferred.
                zero: equally preferred.
                positive: more preferred.

        Returns:
          The path of the latest eligible AFDO artifact.

        Raises:
          NoProfilesInGsBucketError: If no profiles in GS bucket.
          RuntimeError: If no valid latest profiles.
          ValueError: if regex is not valid.
        """

        def _FilesOnBranch(all_files, branch):
            """Return the files that are on this branch.

            Legacy PFQ results look like: latest-chromeos-chrome-amd64-79.afdo.
            The branch should appear in the name either as:
            - R78-12371.22-1566207135 for kernel/CWP profiles, OR
            - chromeos-chrome-amd64-78.0.3877.0 for benchmark profiles

            Args:
              all_files: (list(string)) list of files from GS.
              branch: (string) branch number.

            Returns:
              Files matching the branch.
            """
            # Filter out those not match pattern. And filter out text files for legacy
            # PFQ like latest-chromeos-chrome-amd64-79.afdo.
            results = []
            for x in all_files:
                if "latest-" in x.url:
                    continue

                x_name = os.path.basename(x.url)
                # Filter in CWP, benchmark AFDO and Orderfiles.
                if (
                    x_name.startswith(f"R{branch}")
                    or x_name.startswith(
                        f"chromeos-chrome-orderfile-field-{branch}"
                    )
                    or x_name.startswith(
                        f"chromeos-chrome-{self.arch}-{branch}"
                    )
                ):
                    results.append(x)

            return results

        # Obtain all files from the gs_urls.
        all_files = []
        for gs_url in gs_urls:
            try:
                all_files += self.gs_context.List(gs_url, details=True)
            except gs.GSNoSuchKey:
                pass

        results = _FilesOnBranch(all_files, self.chrome_branch)
        if not results:
            # If no results found, it's maybe because we just branched.
            # Try to find the latest profile from last branch.
            results = _FilesOnBranch(
                all_files, str(int(self.chrome_branch) - 1)
            )

        if not results:
            raise NoProfilesInGsBucketError(
                "No files for branch %s found in %s"
                % (self.chrome_branch, " ".join(gs_urls))
            )

        latest = None
        for res in results:
            rank = rank_func(res.url)
            if rank and (not latest or [rank, ""] > latest):
                latest = [rank, res.url]

        if not latest:
            raise RuntimeError(
                "No valid latest artifact was found in %s"
                "(example invalid artifact: %s)."
                % (" ".join(gs_urls), results[0].url)
            )

        name = latest[1]
        logging.info("Latest AFDO artifact is %s", name)
        return name

    def _AfdoTmpPath(self, path: str = "") -> str:
        """Return the directory for benchmark-afdo-generate artifacts.

        Args:
          path: path relative to the directory.

        Returns:
          Path to the directory.
        """
        gen_dir = "/tmp/benchmark-afdo-generate"
        if path:
            return os.path.join(gen_dir, path.lstrip(os.path.sep))
        else:
            return gen_dir

    def _FindArtifact(self, name: str, gs_urls: Iterable[str]) -> Optional[str]:
        """Find an artifact |name|, from a list of |gs_urls|.

        Args:
          name: The name of the artifact (supports wildcards).
          gs_urls: List of full gs:// directory paths to check.

        Returns:
          The url of the located artifact, or None.
        """
        for url in gs_urls:
            path = os.path.join(url, name)
            found_paths = self.gs_context.LS(path)
            if found_paths:
                if len(found_paths) > 1:
                    raise PrepareForBuildHandlerError(
                        f"Found {found_paths} artifacts at {url}. Expected ONE file."
                    )
                return found_paths[0]
        return None

    def _PatchEbuild(self, info, rules, uprev):
        """Patch an ebuild file, possibly uprevving it.

        Args:
          info: _EbuildInfo describing the ebuild file.
          rules: dict of key:value pairs to apply to the ebuild.
          uprev: whether to increment the revision.  Should be False for 9999
              ebuilds, and True otherwise.

        Returns:
          Updated CPV for the ebuild.
        """
        logging.info("Patching %s with %s", info.path, str(rules))
        old_name = info.path
        new_name = "%s.new" % old_name

        _Patterns = collections.namedtuple("_Patterns", ["match", "sub"])
        patterns = set(
            _Patterns(
                re.compile(AFDO_ARTIFACT_EBUILD_REGEX % k),
                AFDO_ARTIFACT_EBUILD_REPL % v,
            )
            for k, v in rules.items()
        )

        want = patterns.copy()
        with open(old_name) as old, open(new_name, "w") as new:
            for line in old:
                for match, sub in patterns:
                    line, count = match.subn(sub, line, count=1)
                    if count:
                        want.remove((match, sub))
                        # Can only match one pattern.
                        break
                new.write(line)
            if want:
                logging.info(
                    "Unable to update %s in the ebuild", [x.sub for x in want]
                )
                raise UpdateEbuildWithAFDOArtifactsError(
                    "Ebuild file does not have appropriate marker for AFDO/orderfile."
                )

        CPV = info.CPV
        if uprev:
            assert CPV.version != "9999"
            new_CPV = f"{CPV.category}/{CPV.package}-{CPV.version}-r{CPV.revision + 1}"
            new_path = os.path.join(
                os.path.dirname(info.path),
                "%s.ebuild" % os.path.basename(new_CPV),
            )
            os.rename(new_name, new_path)
            osutils.SafeUnlink(old_name)
            ebuild_file = new_path
            CPV = _EbuildInfo(new_path, package_info.SplitCPV(new_CPV))
        else:
            assert CPV.version == "9999"
            os.rename(new_name, old_name)
            ebuild_file = old_name

        if self.build_target:
            ebuild_prog = "ebuild-%s" % self.build_target
            cmd = [
                ebuild_prog,
                self.chroot.chroot_path(ebuild_file),
                "manifest",
                "--force",
            ]
            cros_build_lib.run(cmd, enter_chroot=True)

        return CPV

    @staticmethod
    def _ValidOrderfileVersion(url):
        """Convert the given URL to a version for rank comparison."""
        try:
            bench, cwp = _ParseMergedProfileName(os.path.basename(url))
            if bench.is_merged:
                raise ValueError(
                    "-merged should not appear in orderfile or release AFDO name."
                )
            return bench, cwp
        except ProfilesNameHelperError:
            return None

    @staticmethod
    def _ValidBenchmarkProfileVersion(name):
        """Calculate a value used to rank valid benchmark profiles.

        Args:
          name: A name or a full path of a possible benchmark profile.

        Returns:
          A BenchmarkProfileNamedTuple used for ranking if the name
          of the benchmark profile is valid and it's not merged.
          Otherwise, returns None.
        """
        try:
            version = _ParseBenchmarkProfileName(os.path.basename(name))
            # Filter out merged benchmark profiles.
            if version.is_merged:
                return None
            return version
        except ProfilesNameHelperError:
            return None

    def _CreateReleaseChromeAFDO(
        self, cwp_url, bench_url, output_dir, merged_name
    ):
        """Create an AFDO profile to be used in release Chrome.

        This means we want to merge the CWP and benchmark AFDO profiles into
        one, and redact all ICF symbols.

        Args:
          cwp_url: Full (GS) path to the discovered CWP file to use.
          bench_url: Full (GS) path to the verified benchmark profile.
          output_dir: A directory to store the created artifact.  Must be inside of
              the chroot.
          merged_name: Basename for the merged profile.

        Returns:
          Full path to a generated release AFDO profile.
        """
        # Download the compressed profiles from GS.
        cwp_compressed = os.path.join(output_dir, os.path.basename(cwp_url))
        bench_compressed = os.path.join(output_dir, os.path.basename(bench_url))
        self.gs_context.Copy(cwp_url, cwp_compressed)
        self.gs_context.Copy(bench_url, bench_compressed)

        # Decompress the files.
        cwp_local = os.path.splitext(cwp_compressed)[0]
        bench_local = os.path.splitext(bench_compressed)[0]
        cros_build_lib.UncompressFile(cwp_compressed, cwp_local)
        cros_build_lib.UncompressFile(bench_compressed, bench_local)

        # Merge profiles.
        merge_weights = [
            (cwp_local, RELEASE_CWP_MERGE_WEIGHT),
            (bench_local, RELEASE_BENCHMARK_MERGE_WEIGHT),
        ]
        merged_path = os.path.join(output_dir, merged_name)
        self._MergeAFDOProfiles(merge_weights, merged_path)

        # Redact profiles.
        redacted_path = merged_path + "-redacted.afdo"
        # Trim the profile to contain 20k functions, as our current profile has
        # ~20k functions so this modification brings less impact on prod.
        self._ProcessAFDOProfile(
            merged_path,
            redacted_path,
            redact=True,
            remove=True,
            reduce_functions=20000,
            compbinary=True,
        )

        return redacted_path

    def _MergeAFDOProfiles(
        self, profile_list, output_profile, use_compbinary=False
    ):
        """Merges the given profile list.

        This is ultimately derived from afdo.py, but runs OUTSIDE of the chroot.
        It converts paths to chroot-relative paths, and runs llvm-profdata in the
        chroot.

        Args:
          profile_list: a list of (profile_path, profile_weight).
            Profile_weight is an int that tells us how to weight the profile
            relative to everything else.
          output_profile: where to store the result profile.
          use_compbinary: whether to use the new compressed binary AFDO profile
            format.
        """
        if not profile_list:
            raise ValueError("Need profiles to merge")

        # A regular llvm-profdata command looks like:
        # llvm-profdata merge [-sample] -output=/path/to/output input1 [...]
        #
        # Alternatively, we can specify inputs by `-weighted-input=A,file`, where A
        # is a multiplier of the sample counts in the profile.
        merge_command = [
            "llvm-profdata",
            "merge",
            "-sample",
            "-output=" + self.chroot.chroot_path(output_profile),
        ] + [
            "-weighted-input=%d,%s" % (weight, self.chroot.chroot_path(name))
            for name, weight in profile_list
        ]

        # Here only because this was copied from afdo.py
        if use_compbinary:
            merge_command.append("-compbinary")
        cros_build_lib.run(merge_command, enter_chroot=True, print_cmd=True)

    def _ProcessAFDOProfile(
        self,
        input_path,
        output_path,
        redact=False,
        remove=False,
        reduce_functions=None,
        compbinary=False,
    ):
        """Process the AFDO profile with different editings.

        In this function, we will convert an AFDO profile into textual version,
        do the editings and convert it back.

        This function runs outside of the chroot, and enters the chroot.

        Args:
          input_path: Full path (outside chroot) to input AFDO profile.
          output_path: Full path (outside chroot) to output AFDO profile.
          redact: Redact ICF'ed symbols from AFDO profiles.
            ICF can cause inflation on AFDO sampling results, so we want to remove
            them from AFDO profiles used for Chrome.
            See http://crbug.com/916024 for more details.
          remove: Remove indirect call targets from the given profile.
          reduce_functions: Remove the cold functions in the profile until the
            given number is met.
          compbinary: Whether to convert the final profile into compbinary type.

        Raises:
          BundleArtifactsHandlerError: If the output profile is empty.
        """
        profdata_command_base = ["llvm-profdata", "merge", "-sample"]
        # Convert the compbinary profiles to text profiles.
        input_to_text_temp = input_path + ".text.temp"
        cmd_to_text = profdata_command_base + [
            "-text",
            self.chroot.chroot_path(input_path),
            "-output",
            self.chroot.chroot_path(input_to_text_temp),
        ]
        cros_build_lib.run(cmd_to_text, enter_chroot=True, print_cmd=True)

        current_input_file = input_to_text_temp
        if redact:
            # Call the redaction script.
            redacted_temp = input_path + ".redacted.temp"
            with open(current_input_file, "rb") as f:
                cros_build_lib.run(
                    ["redact_textual_afdo_profile"],
                    input=f,
                    stdout=redacted_temp,
                    enter_chroot=True,
                    print_cmd=True,
                )
            current_input_file = redacted_temp

        if remove:
            # Call the remove indirect call script
            removed_temp = input_path + ".removed.temp"
            cros_build_lib.run(
                [
                    "remove_indirect_calls",
                    "--input=" + self.chroot.chroot_path(current_input_file),
                    "--output=" + self.chroot.chroot_path(removed_temp),
                ],
                enter_chroot=True,
                print_cmd=True,
            )
            current_input_file = removed_temp

        if reduce_functions:
            # Remove cold functions in the profile. Trim the profile to contain 20k
            # functions, as our current profile has ~20k functions so this
            # modification brings less impact on prod.
            reduced_tmp = input_path + ".reduced.tmp"
            cros_build_lib.run(
                [
                    "remove_cold_functions",
                    "--input=" + self.chroot.chroot_path(current_input_file),
                    "--output=" + self.chroot.chroot_path(reduced_tmp),
                    "--number=" + str(reduce_functions),
                ],
                enter_chroot=True,
                print_cmd=True,
            )
            current_input_file = reduced_tmp

        # Convert the profiles back to binary profiles.
        cmd_to_binary = profdata_command_base + [
            self.chroot.chroot_path(current_input_file),
            "-output",
            self.chroot.chroot_path(output_path),
        ]
        if compbinary:
            # Using `compbinary` profiles saves us hundreds of MB of RAM per
            # compilation, since it allows profiles to be lazily loaded.
            cmd_to_binary.append("-compbinary")
        cros_build_lib.run(cmd_to_binary, enter_chroot=True, print_cmd=True)

        profile_size = os.path.getsize(output_path)
        logging.info(
            "_ProcessAFDOProfile produced AFDO profile %s, size %.1fMB",
            output_path,
            profile_size / (1024 * 1024),
        )
        # Verify the profile size.
        # Empty profiles in a binary format can have a non-zero size
        # because of the header but they won't exceed the page size.
        # Normal profiles are usually >1MB.
        if profile_size < 4096:
            raise BundleArtifactsHandlerError(
                f"_ProcessAFDOProfile produced empty AFDO profile, {profile_size}"
            )

    def _CreateAndUploadMergedAFDOProfile(
        self, unmerged_profile, output_dir, recent_to_merge=5, max_age_days=14
    ):
        """Create a merged AFDO profile from recent AFDO profiles and upload it.

        Args:
          unmerged_profile: Path to the AFDO profile we've just created. No
            profiles whose names are lexicographically ordered after this are
            candidates for selection.
          output_dir: Path to location to store merged profiles for uploading.
          recent_to_merge: The maximum number of profiles to merge (include the
            current profile).
          max_age_days: Don't merge profiles older than max_age_days days old.

        Returns:
          The name of a merged profile if the AFDO profile is a candidate for
          merging and ready to be merged and uploaded. Otherwise, None.
        """
        if recent_to_merge == 1:
            # Merging the unmerged_profile into itself is a NOP.
            return None

        unmerged_name = os.path.basename(unmerged_profile)
        merged_suffix = "-merged"
        profile_suffix = AFDO_SUFFIX + BZ2_COMPRESSION_SUFFIX
        benchmark_url = self.input_artifacts.get(
            "UnverifiedChromeBenchmarkAfdoFile", [BENCHMARK_AFDO_GS_URL]
        )[0]
        try:
            benchmark_listing = self.gs_context.List(
                os.path.join(
                    benchmark_url,
                    f"chromeos-chrome-{self.arch}-*" + profile_suffix,
                ),
                details=True,
            )
        except (gs.GSCommandError, gs.GSNoSuchKey):
            # This can happen in a new GS bucket where there are no profiles
            # yet.
            logging.warning(
                "Did not find valid benchmark profiles. Skip profile merge.",
            )
            return None

        unmerged_version = _ParseBenchmarkProfileName(unmerged_name)

        def _GetOrderedMergeableProfiles(
            benchmark_listing: Iterable[gs.GSListResult],
        ) -> Iterable[gs.GSListResult]:
            """Returns a list of mergeable profiles ordered by increasing version."""
            # Exclude merged profiles, because merging merged profiles into merged
            # profiles is likely bad. _ValidBenchmarkProfileVersion takes care of it.
            profile_versions = [
                (self._ValidBenchmarkProfileVersion(x.url), x)
                for x in benchmark_listing
            ]
            # Filter in only necessary profiles.
            candidates = sorted(
                (version, x)
                for version, x in profile_versions
                if version and unmerged_version >= version
            )
            return [x for _, x in candidates]

        benchmark_profiles = _GetOrderedMergeableProfiles(benchmark_listing)
        if not benchmark_profiles:
            logging.warning(
                "Skipping merged profile creation: no merge candidates found"
            )
            return None

        # The input "unmerged_name" should never be in GS bucket, as recipe
        # builder executes only when the artifact not exists.
        if (
            os.path.splitext(os.path.basename(benchmark_profiles[-1].url))[0]
            == unmerged_name
        ):
            benchmark_profiles = benchmark_profiles[:-1]

        # assert os.path.splitext(os.path.basename(
        #    benchmark_profiles[-1].url))[0] != unmerged_name, unmerged_name

        base_time = datetime.datetime.fromtimestamp(
            os.path.getmtime(unmerged_profile)
        )
        time_cutoff = base_time - datetime.timedelta(days=max_age_days)
        merge_candidates = [
            p for p in benchmark_profiles if p.creation_time >= time_cutoff
        ]

        # Pick (recent_to_merge-1) from the GS URL, because we also need to pick
        # the current profile locally.
        merge_candidates = merge_candidates[-(recent_to_merge - 1) :]

        # This should never happen, but be sure we're not merging a profile into
        # itself anyway. It's really easy for that to silently slip through, and can
        # lead to overrepresentation of a single profile, which just causes more
        # noise.
        assert len(set(p.url for p in merge_candidates)) == len(
            merge_candidates
        )

        # Merging a profile into itself is pointless.
        if not merge_candidates:
            logging.warning(
                "Skipping merged profile creation: we only have a single "
                "merge candidate."
            )
            return None

        afdo_files = []
        for candidate in merge_candidates:
            # It would be slightly less complex to just name these off as
            # profile-1.afdo, profile-2.afdo, ... but the logs are more readable if we
            # keep the basename from gs://.
            candidate_name = os.path.basename(candidate.url)
            candidate_uncompressed = candidate_name[
                : -len(BZ2_COMPRESSION_SUFFIX)
            ]

            copy_from = candidate.url
            copy_to = os.path.join(output_dir, candidate_name)
            copy_to_uncompressed = os.path.join(
                output_dir, candidate_uncompressed
            )

            self.gs_context.Copy(copy_from, copy_to)
            cros_build_lib.UncompressFile(copy_to, copy_to_uncompressed)
            afdo_files.append(copy_to_uncompressed)

        afdo_files.append(unmerged_profile)
        afdo_basename = os.path.basename(afdo_files[-1])
        assert afdo_basename.endswith(AFDO_SUFFIX)
        afdo_basename = afdo_basename[: -len(AFDO_SUFFIX)]

        raw_merged_basename = (
            "raw-" + afdo_basename + merged_suffix + AFDO_SUFFIX
        )
        raw_merged_output_path = os.path.join(output_dir, raw_merged_basename)

        # Weight all profiles equally.
        self._MergeAFDOProfiles(
            [(profile, 1) for profile in afdo_files], raw_merged_output_path
        )

        profile_to_upload_basename = afdo_basename + merged_suffix + AFDO_SUFFIX
        profile_to_upload_path = os.path.join(
            output_dir, profile_to_upload_basename
        )

        # Remove indirect calls and remove cold functions
        # Since the benchmark precisions increased, the number of functions in
        # merged profiles also grow. To stabilize the impact on production
        # profiles for Android/Linux, reduce the number of functions to 70k,
        # which aligns with recent 3 merged benchmark profiles.
        # FIXME: see if a lower number (50K? 20K?) is equally as good.
        self._ProcessAFDOProfile(
            raw_merged_output_path,
            profile_to_upload_path,
            redact=False,
            remove=True,
            reduce_functions=70000,
            compbinary=False,
        )

        result_basename = os.path.basename(profile_to_upload_path)
        return result_basename

    def _CleanupArtifactDirectory(self, src_dir):
        """Cleanup a directory before build so we can safely use the artifacts.

        Args:
          src_dir: A temp path holding the possible artifacts. It needs to be an
          absolute path.
        """
        assert os.path.isabs(src_dir), (
            "%s needs to be an absolute path " % src_dir
        )
        check_dirs = [
            self.chroot.full_path(x)
            for x in [src_dir, os.path.join(self.sysroot_path, src_dir[1:])]
        ]
        for directory in check_dirs:
            if not os.path.exists(directory):
                continue

            logging.info(
                "toolchain-logs: Cleaning up %s before build", directory
            )
            osutils.RmDir(directory, sudo=True)


class PrepareForBuildHandler(_CommonPrepareBundle):
    """Methods for updating ebuilds for toolchain artifacts."""

    def __init__(
        self,
        artifact_name,
        chroot,
        sysroot_path,
        build_target,
        input_artifacts,
        profile_info,
    ):
        super().__init__(
            artifact_name,
            chroot,
            sysroot_path,
            build_target,
            input_artifacts=input_artifacts,
            profile_info=profile_info,
        )
        self._prepare_func = getattr(self, "_Prepare" + artifact_name)

    def Prepare(self):
        return self._prepare_func()

    def _CommonPrepareBasedOnGsPathExists(self, name, url, key):
        """Helper function to determine if an artifact in the GS path or not."""
        gs_url = self.input_artifacts.get(key, [url])[0]
        path = os.path.join(gs_url, name)
        if self.gs_context.Exists(path):
            # Artifact already created.
            logging.info("Pointless build: Found %s on %s", name, path)
            return PrepareForBuildReturn.POINTLESS
        logging.info("Build needed: No %s found. %s does not exist", key, path)
        return PrepareForBuildReturn.NEEDED

    def _PrepareUnverifiedChromeLlvmOrderfile(self):
        """Prepare to build an unverified ordering file."""
        return self._CommonPrepareBasedOnGsPathExists(
            name=self._GetOrderfileName() + XZ_COMPRESSION_SUFFIX,
            url=ORDERFILE_GS_URL_UNVETTED,
            key="UnverifiedChromeLlvmOrderfile",
        )

    def _PrepareVerifiedChromeLlvmOrderfile(self):
        """Prepare to verify an unvetted ordering file."""
        ret = PrepareForBuildReturn.NEEDED
        # We will look for the input artifact in the given path, but we only check
        # for the vetted artifact in the first location given.
        locations = self.input_artifacts.get(
            "UnverifiedChromeLlvmOrderfile", [ORDERFILE_GS_URL_UNVETTED]
        )
        path = self._FindLatestOrderfileArtifact(locations)
        loc, name = os.path.split(path)

        # If not given as an input_artifact, the vetted location is determined from
        # the first location given for the unvetted artifact.
        vetted_loc = self.input_artifacts.get(
            "VerifiedChromeLlvmOrderfile", [None]
        )[0]
        if not vetted_loc:
            vetted_loc = os.path.join(os.path.dirname(locations[0]), "vetted")
        vetted_path = os.path.join(vetted_loc, name)
        if self.gs_context.Exists(vetted_path):
            # The latest unverified ordering file has already been verified.
            logging.info('Pointless build: "%s" exists.', vetted_path)
            ret = PrepareForBuildReturn.POINTLESS

        # If we don't have an SDK, then we cannot update the manifest.
        if self.chroot:
            self._PatchEbuild(
                self._GetEbuildInfo(constants.CHROME_PN),
                {
                    "UNVETTED_ORDERFILE": os.path.splitext(name)[0],
                    "UNVETTED_ORDERFILE_LOCATION": loc,
                },
                uprev=True,
            )
        else:
            logging.info("No chroot: not patching ebuild.")
        return ret

    def _PrepareChromeClangWarningsFile(self):
        # We always build this artifact.
        return PrepareForBuildReturn.NEEDED

    def _PrepareUnverifiedLlvmPgoFile(self):
        # If we have a chroot, make sure that the toolchain is set up to generate
        # the artifact.  Raise an error if we know it will fail.
        if self.chroot:
            llvm_pkg = "sys-devel/llvm"
            use_flags = portage_util.GetInstalledPackageUseFlags(llvm_pkg)[
                llvm_pkg
            ]
            if "llvm_pgo_generate" not in use_flags:
                raise PrepareForBuildHandlerError(
                    "sys-devel/llvm lacks llvm_pgo_generate: %s"
                    % sorted(use_flags)
                )

        # Always build this artifact.
        return PrepareForBuildReturn.NEEDED

    def _UnverifiedAfdoFileExists(self):
        """Check if the unverified AFDO benchmark file exists.

        This is used by both the UnverifiedChromeBenchmark Perf and Afdo file prep
        methods.

          PrepareForBuildReturn.
        """
        # We do not check for the existence of the (intermediate) perf.data file
        # since that is tied to the build, and the orchestrator decided that we
        # should run (no build to recycle).
        #
        # Check if there is already a published AFDO artifact for this version of
        # Chrome.
        return self._CommonPrepareBasedOnGsPathExists(
            name=self._GetBenchmarkAFDOName() + BZ2_COMPRESSION_SUFFIX,
            url=BENCHMARK_AFDO_GS_URL,
            key="UnverifiedChromeBenchmarkAfdoFile",
        )

    def _PrepareUnverifiedChromeBenchmarkPerfFile(self):
        """Prepare to build the Chrome benchmark perf.data file."""
        return self._UnverifiedAfdoFileExists()

    def _PrepareUnverifiedChromeBenchmarkAfdoFile(self):
        """Prepare to build an Unverified Chrome benchmark AFDO file."""
        ret = self._UnverifiedAfdoFileExists()
        if self.chroot:
            # Fetch the CHROME_DEBUG_BINARY and UNVERIFIED_CHROME_BENCHMARK_PERF_FILE
            # artifacts and unpack them for the Bundle call.
            workdir_full = self.chroot.full_path(self._AfdoTmpPath())
            # Clean out the workdir.
            osutils.RmDir(workdir_full, ignore_missing=True, sudo=True)
            osutils.SafeMakedirs(workdir_full)

            # We don't need a strict version from ebuild because it can change in the
            # timeframe between afdo-generate and afdo-process (right, it happens!).
            # Another edge case is revbump of chrome with patches in 9999.
            bin_name = (
                self._GetBenchmarkAFDOName(
                    CHROME_DEBUG_BINARY_NAME, wildcard_version=True
                )
                + BZ2_COMPRESSION_SUFFIX
            )
            gs_loc = self.input_artifacts.get("ChromeDebugBinary", [])
            # url contains a concrete chrome version.
            bin_url = self._FindArtifact(bin_name, gs_loc)
            if not bin_url:
                raise PrepareForBuildHandlerError(
                    "Could not find an artifact matching the pattern "
                    f'"{bin_name}" in {gs_loc}.'
                )
            # Extract the name with a concrete version of chrome.
            bin_name = os.path.basename(bin_url)
            bin_compressed = self._AfdoTmpPath(bin_name)
            cros_build_lib.run(
                [
                    "gsutil",
                    "-o",
                    "Boto:num_retries=10",
                    "cp",
                    "-v",
                    "--",
                    bin_url,
                    bin_compressed,
                ],
                enter_chroot=True,
                print_cmd=True,
            )
            cros_build_lib.run(
                ["bzip2", "-d", bin_compressed],
                enter_chroot=True,
                print_cmd=True,
            )

            perf_name = (
                self._GetBenchmarkAFDOName(template=CHROME_PERF_AFDO_FILE)
                + BZ2_COMPRESSION_SUFFIX
            )
            perf_compressed = self._AfdoTmpPath(perf_name)
            gs_loc = self.input_artifacts.get(
                "UnverifiedChromeBenchmarkPerfFile", []
            )
            perf_url = self._FindArtifact(perf_name, gs_loc)
            if not perf_url:
                raise PrepareForBuildHandlerError(
                    f'Could not find "{perf_name}" in {gs_loc}.'
                )
            self.gs_context.Copy(
                perf_url, self.chroot.full_path(perf_compressed)
            )
            cros_build_lib.run(
                ["bzip2", "-d", perf_compressed],
                enter_chroot=True,
                print_cmd=True,
            )
        return ret

    def _PrepareChromeAFDOProfileForAndroidLinux(self):
        """Prepare to build Chrome AFDO profile for Android/Linux."""
        if self._UnverifiedAfdoFileExists() == PrepareForBuildReturn.POINTLESS:
            # Only generate new Android/Linux profiles when there's a need to
            # generate new benchmark profiles
            return PrepareForBuildReturn.POINTLESS

        return self._CommonPrepareBasedOnGsPathExists(
            name=self._GetBenchmarkAFDOName()
            + "-merged"
            + BZ2_COMPRESSION_SUFFIX,
            url=BENCHMARK_AFDO_GS_URL,
            key="ChromeAFDOProfileForAndroidLinux",
        )

    def _PrepareVerifiedChromeBenchmarkAfdoFile(self):
        """Unused: see _PrepareVerifiedReleaseAfdoFile."""
        raise PrepareForBuildHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _PrepareChromeDebugBinary(self):
        """See _PrepareUnverifiedChromeBenchmarkPerfFile."""
        return PrepareForBuildReturn.POINTLESS

    def _PrepareUnverifiedKernelCwpAfdoFile(self):
        """Unused: CWP is from elsewhere."""
        raise PrepareForBuildHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _PrepareVerifiedKernelCwpAfdoFile(self):
        """Prepare to verify the kernel CWP AFDO artifact."""
        ret = PrepareForBuildReturn.NEEDED
        kernel_version = self.profile_info.get("kernel_version")
        if not kernel_version:
            raise PrepareForBuildHandlerError(
                "Could not find kernel version to verify."
            )
        # Temporary workaround for the kernel AFDO - extract arch
        # from the kernel version.
        # kernel_version for arm will look like "arm-5.15".
        # TODO(b/246457583): Pass arch via an expanded proto field.
        if kernel_version.startswith("arm-"):
            self.arch = "arm"
            kernel_version = kernel_version.split("-")[-1]
            profile_var_name = "ARM_AFDO_PROFILE_VERSION"
            profile_url = KERNEL_ARM_PROFILE_URL
            verified_profile_url = KERNEL_ARM_AFDO_GS_URL_VETTED
        else:
            profile_var_name = "AFDO_PROFILE_VERSION"
            profile_url = KERNEL_PROFILE_URL
            verified_profile_url = KERNEL_AFDO_GS_URL_VETTED

        cwp_locs = [
            x
            for x in self.input_artifacts.get(
                "UnverifiedKernelCwpAfdoFile",
                [os.path.join(profile_url, kernel_version)],
            )
        ]
        afdo_path = self._FindLatestAFDOArtifact(
            cwp_locs, _RankValidCWPProfiles
        )

        published_path = os.path.join(
            self.input_artifacts.get(
                "VerifiedKernelCwpAfdoFile",
                [os.path.join(verified_profile_url, kernel_version)],
            )[0],
            os.path.basename(afdo_path),
        )
        if self.gs_context.Exists(published_path):
            # The verified artifact is already present: we are done.
            logging.info('Pointless build: "%s" exists.', published_path)
            ret = PrepareForBuildReturn.POINTLESS

        afdo_dir, afdo_name = os.path.split(
            afdo_path.replace(KERNEL_AFDO_COMPRESSION_SUFFIX, "")
        )
        # The package name cannot have dots, so an underscore is used instead.
        # For example: chromeos-kernel-4_4-4.4.214-r2087.ebuild.
        kernel_version = kernel_version.replace(".", "_")

        # Check freshness.
        age = _GetProfileAge(afdo_name, "kernel_afdo")
        if age > KERNEL_ALLOWED_STALE_DAYS:
            logging.info(
                "Found an expired afdo for kernel %s: %s, skip.",
                kernel_version,
                afdo_name,
            )
            ret = PrepareForBuildReturn.POINTLESS

        if age > KERNEL_WARN_STALE_DAYS:
            _WarnDetectiveAboutKernelProfileExpiration(
                kernel_version, afdo_path
            )

        # If we don't have an SDK, then we cannot update the manifest.
        if self.chroot:
            self._PatchEbuild(
                self._GetEbuildInfo(
                    "chromeos-kernel-%s" % kernel_version, "sys-kernel"
                ),
                {profile_var_name: afdo_name, "AFDO_LOCATION": afdo_dir},
                uprev=True,
            )
        return ret

    def _PrepareUnverifiedChromeCwpAfdoFile(self):
        """Unused: CWP is from elsewhere."""
        raise PrepareForBuildHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _PrepareVerifiedChromeCwpAfdoFile(self):
        """Unused: see _PrepareVerifiedReleaseAfdoFile."""
        raise PrepareForBuildHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _PrepareVerifiedReleaseAfdoFile(self):
        """Prepare to verify the Chrome AFDO artifact and release it.

        See also "chrome_afdo" code elsewhere in this file.
        """
        ret = PrepareForBuildReturn.NEEDED
        if not self.uarch:
            raise PrepareForBuildHandlerError(
                "Uarch is not set. "
                "Is 'chrome_cwp_profile' missing in profile_info?"
            )
        bench_locs = self.input_artifacts.get(
            "UnverifiedChromeBenchmarkAfdoFile", [BENCHMARK_AFDO_GS_URL]
        )
        cwp_locs = self.input_artifacts.get(
            "UnverifiedChromeCwpAfdoFile", [CWP_AFDO_GS_URL]
        )

        # This will raise a NoProfilesInGsBucketError if no artifact is found.
        bench = self._FindLatestAFDOArtifact(
            bench_locs, self._ValidBenchmarkProfileVersion
        )
        try:
            cwp = self._FindLatestAFDOArtifact(cwp_locs, _RankValidCWPProfiles)
        except NoProfilesInGsBucketError:
            # Missing arm profiles will be handled below.
            if self.arch == "arm":
                cwp = None
            else:
                raise
        # If there are no new arm profiles use cwp profiles from atom.
        # TODO(b/243198050): Remove workaround when the issue with Arm CWP
        # profiles is fixed.
        if (
            not cwp
            or _GetProfileAge(
                os.path.split(cwp)[1].replace(".afdo.xz", ""), "cwp"
            )
            > CHROME_ARM_CWP_ALLOWED_STALE_DAYS
        ):
            cwp_atom_locs = [os.path.join(CWP_AFDO_GS_URL, "atom")]
            logging.warning(
                "No arm profiles found at %s or profiles are too old. "
                "Will use the latest profile from %s.",
                cwp_locs,
                cwp_atom_locs,
            )
            cwp = self._FindLatestAFDOArtifact(
                cwp_atom_locs, _RankValidCWPProfiles
            )
        bench_name = os.path.split(bench)[1]
        cwp_name = os.path.split(cwp)[1]

        # Check to see if we already have a verified AFDO profile.
        # We only look at the first path in the list of vetted locations, since that
        # is where we will publish the verified profile.
        published_loc = self.input_artifacts.get(
            "VerifiedReleaseAfdoFile", [RELEASE_AFDO_GS_URL_VETTED]
        )[0]
        merged_name = MERGED_AFDO_NAME.format(
            arch=self.arch,
            name=_GetCombinedAFDOName(
                _ParseCWPProfileName(os.path.splitext(cwp_name)[0]),
                self.uarch,
                _ParseBenchmarkProfileName(os.path.splitext(bench_name)[0]),
            ),
        )
        published_name = merged_name + "-redacted.afdo" + XZ_COMPRESSION_SUFFIX
        published_path = os.path.join(published_loc, published_name)

        if self.gs_context.Exists(published_path):
            # The verified artifact is already present: we are done.
            logging.info('Pointless build: "%s" exists.', published_path)
            ret = PrepareForBuildReturn.POINTLESS

        # If we don't have an SDK, then we cannot update the manifest.
        if self.chroot:
            # Generate the AFDO profile to verify in ${CHROOT}/tmp/.
            with self.chroot.tempdir() as tempdir:
                art = self._CreateReleaseChromeAFDO(
                    cwp, bench, tempdir, merged_name
                )
                afdo_profile = os.path.join(
                    self.chroot.tmp, os.path.basename(art)
                )
                os.rename(art, afdo_profile)
            self._PatchEbuild(
                self._GetEbuildInfo(constants.CHROME_PN),
                {"UNVETTED_AFDO_FILE": self.chroot.chroot_path(afdo_profile)},
                uprev=True,
            )
        return ret

    def _PrepareToolchainWarningLogs(self):
        # We always build this artifact.
        # Cleanup the temp directory that holds the artifacts
        self._CleanupArtifactDirectory("/tmp/fatal_clang_warnings")
        return PrepareForBuildReturn.NEEDED

    def _PrepareClangCrashDiagnoses(self):
        # We always build this artifact.
        # Cleanup the temp directory that holds the artifacts
        self._CleanupArtifactDirectory("/tmp/clang_crash_diagnostics")
        return PrepareForBuildReturn.UNKNOWN

    def _PrepareCompilerRusageLogs(self):
        # We always build this artifact.
        # Cleanup the temp directory that holds the artifacts
        self._CleanupArtifactDirectory("/tmp/compiler_rusage")
        return PrepareForBuildReturn.UNKNOWN


class BundleArtifactHandler(_CommonPrepareBundle):
    """Methods for updating ebuilds for toolchain artifacts."""

    def __init__(
        self,
        artifact_name,
        chroot,
        sysroot_path,
        build_target,
        output_dir,
        profile_info,
    ):
        super().__init__(
            artifact_name,
            chroot,
            sysroot_path,
            build_target,
            profile_info=profile_info,
        )
        self._bundle_func = getattr(self, "_Bundle" + artifact_name)
        self.output_dir = output_dir

    def Bundle(self):
        return self._bundle_func()

    def _BundleUnverifiedChromeLlvmOrderfile(self):
        """Bundle to build an unverified ordering file."""
        with self.chroot.tempdir() as tempdir:
            GenerateChromeOrderfile(
                board=self.build_target,
                output_dir=tempdir,
                chrome_root=self.chroot.chrome_root,
                chroot_path=self.chroot.path,
                chroot_args=self.chroot.get_enter_args(),
            ).Bundle()

            files = []
            for path in osutils.DirectoryIterator(tempdir):
                if os.path.isfile(path):
                    rel_path = os.path.relpath(path, tempdir)
                    files.append(os.path.join(self.output_dir, rel_path))
            osutils.CopyDirContents(
                tempdir, self.output_dir, allow_nonempty=True
            )

        return files

    def _BundleVerifiedChromeLlvmOrderfile(self):
        """Bundle vetted ordering file."""
        orderfile_name = self._GetArtifactVersionInEbuild(
            constants.CHROME_PN, "UNVETTED_ORDERFILE"
        )
        if not orderfile_name:
            raise BundleArtifactsHandlerError(
                f"Could not find UNVETTED_ORDERFILE version in {constants.CHROME_PN}"
            )
        orderfile_name += XZ_COMPRESSION_SUFFIX

        # Strip the leading / from sysroot_path.
        orderfile_path = self.chroot.full_path(
            self.sysroot_path, "opt/google/chrome", orderfile_name
        )
        verified_orderfile = os.path.join(self.output_dir, orderfile_name)
        shutil.copy2(orderfile_path, verified_orderfile)
        return [verified_orderfile]

    def _BundleChromeClangWarningsFile(self):
        """Bundle clang-tidy warnings file."""
        with self.chroot.tempdir() as tempdir:
            in_chroot_tempdir = self.chroot.chroot_path(tempdir)
            now = datetime.datetime.strftime(datetime.datetime.now(), "%Y%m%d")
            clang_tidy_tarball = (
                f"{self.build_target}.{now}" ".clang_tidy_warnings.tar.xz"
            )
            cmd = [
                "cros_generate_tidy_warnings",
                "--out-file",
                clang_tidy_tarball,
                "--out-dir",
                in_chroot_tempdir,
                "--board",
                self.build_target,
                "--logs-dir",
                os.path.join("/tmp/clang-tidy-logs", self.build_target),
            ]
            cros_build_lib.run(cmd, cwd=self.chroot.path, enter_chroot=True)
            artifact_path = os.path.join(self.output_dir, clang_tidy_tarball)
            shutil.copy2(
                os.path.join(tempdir, clang_tidy_tarball), artifact_path
            )
        return [artifact_path]

    def _GetProfileNames(self, datadir):
        """Return list of profiles.

        This function is for ease in test writing.

        Args:
          datadir: Absolute path to build/coverage_data in the sysroot.

        Returns:
          list of chroot-relative paths to profiles found.
        """
        return [
            self.chroot.chroot_path(os.path.join(dir_name, file_name))
            for dir_name, _, files in os.walk(datadir)
            for file_name in files
            if os.path.basename(dir_name) == "raw_profiles"
        ]

    def _BundleUnverifiedLlvmPgoFile(self):
        """Bundle the unverified PGO profile for llvm."""
        # What is the PackageInfo for the compiler?
        llvm_pkg = portage_util.FindPackageNameMatches("sys-devel/llvm")[0]

        files = []
        # Find all of the raw profile data.
        datadir = self.chroot.full_path(
            self.sysroot_path, "build", "coverage_data"
        )
        profiles = self._GetProfileNames(datadir)
        if not profiles:
            raise BundleArtifactsHandlerError(
                "No raw profiles found in %s" % datadir
            )

        # Capture the clang version.
        clang_version_str = (
            cros_build_lib.sudo_run(
                ["clang", "--version"],
                enter_chroot=True,
                stdout=True,
                encoding="utf-8",
            )
            .stdout.splitlines()[0]
            .strip()
        )
        # TODO(crbug.com/1132918): There's a git-r3 bug that caused the LLVM build
        # failed to find the upstream URL, so use the string contains the local
        # path to clang source instead.
        match = re.search(
            r"(?:llvm-project|clang) ([A-Fa-f0-9]{40})\)$", clang_version_str
        )
        if not match:
            raise BundleArtifactsHandlerError(
                "Can't recognize the version string %s" % clang_version_str
            )
        head_sha = match.group(1)
        profdata_base = "%s-%s" % (llvm_pkg.pvr, head_sha)
        metadata_path = os.path.join(
            self.output_dir, profdata_base + ".llvm_metadata.json"
        )
        pformat.json({"head_sha": head_sha}, fp=metadata_path, compact=True)
        files.append(metadata_path)
        metadata_path = os.path.join(self.output_dir, "llvm_metadata.json")
        pformat.json({"head_sha": head_sha}, fp=metadata_path, compact=True)
        files.append(metadata_path)

        # Create a tarball with the merged profile data.  The name will be of the
        # form '{llvm-package-pv}-{clang-head_sha}.llvm_profdata.tar.zx.
        with self.chroot.tempdir() as tempdir:
            raw_list = os.path.join(tempdir, "profraw_list")
            with open(raw_list, "w") as f:
                f.write("\n".join(profiles))
            basename = "%s.llvm.profdata" % profdata_base
            merged_path = os.path.join(tempdir, basename)
            cros_build_lib.sudo_run(
                [
                    "llvm-profdata",
                    "merge",
                    "-f",
                    self.chroot.chroot_path(raw_list),
                    "-output",
                    self.chroot.chroot_path(merged_path),
                ],
                cwd=tempdir,
                enter_chroot=True,
            )
            artifact = os.path.join(self.output_dir, "%s.tar.xz" % basename)
            cros_build_lib.CreateTarball(
                artifact, cwd=tempdir, inputs=[basename]
            )
            files.append(artifact)
        return files

    def _BundleUnverifiedChromeBenchmarkPerfFile(self):
        """Bundle the unverified Chrome benchmark perf.data file.

        The perf.data file is created in the HW Test, and afdo_process needs the
        matching unstripped Chrome binary in order to generate the profile.
        """
        return []

    def _BundleChromeDebugBinary(self):
        """Bundle the unstripped Chrome binary."""
        debug_bin_inside = _CHROME_DEBUG_BIN % {
            "root": "",
            "sysroot": self.sysroot_path,
        }
        binary_name = self._GetBenchmarkAFDOName(CHROME_DEBUG_BINARY_NAME)
        bin_path = os.path.join(
            self.output_dir, binary_name + BZ2_COMPRESSION_SUFFIX
        )
        with open(bin_path, "w") as f:
            cros_build_lib.run(
                ["bzip2", "-c", debug_bin_inside],
                stdout=f,
                enter_chroot=True,
                print_cmd=True,
            )
        return [bin_path]

    def _BundleUnverifiedChromeBenchmarkAfdoFile(self):
        """Bundle a benchmark Chrome AFDO profile.

        Raises:
          BundleArtifactsHandlerError: If the output profile is empty.
        """
        files = []
        # If the name of the provided binary is not 'chrome.unstripped', then
        # create_llvm_prof demands it exactly matches the name of the unstripped
        # binary.  Create a symbolic link named 'chrome.unstripped'.
        CHROME_UNSTRIPPED_NAME = "chrome.unstripped"
        bin_path_in = self._AfdoTmpPath(CHROME_UNSTRIPPED_NAME)
        osutils.SafeSymlink(
            self._GetBenchmarkAFDOName(CHROME_DEBUG_BINARY_NAME),
            self.chroot.full_path(bin_path_in),
        )
        perf_path_inside = self._AfdoTmpPath(
            self._GetBenchmarkAFDOName(template=CHROME_PERF_AFDO_FILE)
        )
        afdo_name = self._GetBenchmarkAFDOName()
        afdo_path_inside = self._AfdoTmpPath(afdo_name)
        # Generate the afdo profile.
        cros_build_lib.run(
            [
                _AFDO_GENERATE_LLVM_PROF,
                "--binary=%s" % self._AfdoTmpPath(CHROME_UNSTRIPPED_NAME),
                "--profile=%s" % perf_path_inside,
                "--out=%s" % afdo_path_inside,
                # Do not set any sample threshold, so the AFDO profile can be as
                # precise as the raw profile.
                "--sample_threshold_frac=0",
            ],
            enter_chroot=True,
            print_cmd=True,
        )
        profile_size = os.path.getsize(self.chroot.full_path(afdo_path_inside))
        # Check if the profile is empty.
        # Empty profiles in a binary format can have a non-zero size
        # because of the header but they won't exceed the page size.
        # Normal profiles are usually >1MB.
        if profile_size < 4096:
            raise BundleArtifactsHandlerError(
                f"AFDO profile size has invalid size, {profile_size}"
            )
        logging.info(
            "Generated %s AFDO profile %s, size %.1fMB",
            self.arch,
            afdo_name,
            profile_size / (1024 * 1024),
        )

        # Compress and deliver the profile.
        afdo_path = os.path.join(
            self.output_dir, afdo_name + BZ2_COMPRESSION_SUFFIX
        )
        with open(afdo_path, "w") as f:
            cros_build_lib.run(
                ["bzip2", "-c", afdo_path_inside],
                stdout=f,
                enter_chroot=True,
                print_cmd=True,
            )
        files.append(afdo_path)
        return files

    def _BundleChromeAFDOProfileForAndroidLinux(self):
        """Bundle Android/Linux Chrome profiles."""
        afdo_name = self._GetBenchmarkAFDOName()
        output_dir_full = self.chroot.full_path(self._AfdoTmpPath())
        afdo_path = os.path.join(output_dir_full, afdo_name)
        # The _BundleUnverifiedChromeBenchmarkAfdoFile should always run
        # before this, so the AFDO profile should already be created.
        assert os.path.exists(
            afdo_path
        ), "No new AFDO profile created before creating Android/Linux profiles"

        files = []
        # Merge recent benchmark profiles for Android/Linux use
        merged_profile = self._CreateAndUploadMergedAFDOProfile(
            os.path.join(output_dir_full, afdo_name), output_dir_full
        )
        if not merged_profile:
            return []

        merged_profile_inside = self._AfdoTmpPath(
            os.path.basename(merged_profile)
        )
        merged_profile_compressed = os.path.join(
            self.output_dir,
            os.path.basename(merged_profile) + BZ2_COMPRESSION_SUFFIX,
        )

        with open(merged_profile_compressed, "wb") as f:
            cros_build_lib.run(
                ["bzip2", "-c", merged_profile_inside],
                stdout=f,
                enter_chroot=True,
                print_cmd=True,
            )
        files.append(merged_profile_compressed)
        return files

    def _BundleVerifiedChromeBenchmarkAfdoFile(self):
        """Unused: see _BundleVerifiedReleaseAfdoFile."""
        raise BundleArtifactsHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _BundleUnverifiedKernelCwpAfdoFile(self):
        """Unused: this artifact comes from CWP."""
        raise BundleArtifactsHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _BundleVerifiedKernelCwpAfdoFile(self):
        """Bundle the verified kernel CWP AFDO file."""
        kernel_version = self.profile_info.get("kernel_version")
        if not kernel_version:
            raise BundleArtifactsHandlerError("kernel_version not provided.")

        # Temporary workaround for the kernel AFDO - extract arch
        # from the kernel version.
        # kernel_version for arm will look like "arm-5.15".
        # TODO(b/246457583): Pass arch via an expanded proto field.
        if kernel_version.startswith("arm-"):
            self.arch = "arm"
            kernel_version = kernel_version.split("-")[-1]
            profile_var_name = "ARM_AFDO_PROFILE_VERSION"
        else:
            profile_var_name = "AFDO_PROFILE_VERSION"

        kernel_version = kernel_version.replace(".", "_")
        profile_name = self._GetArtifactVersionInEbuild(
            f"chromeos-kernel-{kernel_version}", profile_var_name
        )
        if not profile_name:
            raise BundleArtifactsHandlerError(
                "Could not find AFDO_PROFILE_VERSION in "
                f"chromeos-kernel-{kernel_version}."
            )
        profile_name += KERNEL_AFDO_COMPRESSION_SUFFIX
        # The verified profile is in the sysroot with a name similar to:
        # /usr/lib/debug/boot/chromeos-kernel-4_4-R82-12874.0-1581935639.gcov.xz
        profile_path = os.path.join(
            self.chroot.path,
            self.sysroot_path[1:],
            "usr",
            "lib",
            "debug",
            "boot",
            "chromeos-kernel-%s-%s" % (kernel_version, profile_name),
        )
        verified_profile = os.path.join(self.output_dir, profile_name)
        shutil.copy2(profile_path, verified_profile)
        return [verified_profile]

    def _BundleUnverifiedChromeCwpAfdoFile(self):
        """Unused: this artifact comes from CWP."""
        raise BundleArtifactsHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _BundleVerifiedChromeCwpAfdoFile(self):
        """Unused: see _BundleVerifiedReleaseAfdoFile."""
        raise BundleArtifactsHandlerError(
            "Unexpected artifact type %s." % self.artifact_name
        )

    def _BundleVerifiedReleaseAfdoFile(self):
        """Bundle the verified Release AFDO file for Chrome."""
        profile_path = self.chroot.full_path(
            self._GetArtifactVersionInEbuild(
                constants.CHROME_PN, "UNVETTED_AFDO_FILE"
            )
        )
        return _CompressAFDOFiles(
            [profile_path], None, self.output_dir, XZ_COMPRESSION_SUFFIX
        )

    @staticmethod
    def _ListTransitiveFiles(base_directory: str):
        for dir_path, _dir_names, file_names in os.walk(base_directory):
            for file_name in file_names:
                yield os.path.join(dir_path, file_name)

    def _CollectFiles(self, src_dir, dest_dir, include_file):
        """Collect the files with any of file_exts from path to working_dir.

        Args:
          src_dir: the path to the directory to copy files from.
          dest_dir: the path of the directory to copy files to (will be created if
                    it doesn't exist and files need to be copied).
          include_file: a callable that returns True if a file should be copied;
                        False otherwise.

        Returns:
          A list of all files that were copied, relative to `src_dir`.
        """
        check_dirs = [
            self.chroot.full_path(x)
            for x in [
                src_dir,
                os.path.join(
                    self.sysroot_path,
                    src_dir[1:] if os.path.isabs(src_dir) else src_dir,
                ),
            ]
        ]

        logging.info("toolchain-logs: checking %s", check_dirs)
        output = []
        for directory in check_dirs:
            if not os.path.isdir(directory):
                logging.info("toolchain-logs: %s doesn't exist", directory)
                continue

            for src_path in self._ListTransitiveFiles(directory):
                rel_path = os.path.relpath(src_path, start=directory)
                logging.info("toolchain-logs: checking %s", rel_path)
                if not include_file(rel_path):
                    logging.warning(
                        "toolchain-logs: skipped file: %s", rel_path
                    )
                    continue

                dest_path = os.path.join(dest_dir, rel_path)
                while os.path.exists(dest_path):
                    file_noext, file_ext = os.path.splitext(dest_path)
                    dest_path = f"{file_noext}0{file_ext}"

                osutils.SafeMakedirs(os.path.dirname(dest_path))
                rel_dest_path = os.path.relpath(dest_path, start=dest_dir)

                logging.info(
                    "toolchain-logs: adding path %s as %s", src_path, dest_path
                )
                shutil.copy(src_path, dest_path)
                output.append(rel_dest_path)

        logging.info("%d files collected", len(output))
        return output

    def _CreateBundle(self, src_dir, tarball, destination, extension=None):
        """Bundle the files from src_dir into a tar.xz file.

        Args:
          src_dir: the path to the directory to copy files from.
          tarball: name of the generated tarballfile (build target, time stamp,
            and .tar.xz extension will be added automatically)
          destination: path to create tarball in
          extension: type of file to search for in src_dir.
            If extension is None (default), all file types will be allowed.

        Returns:
          Path to the generated tar.xz file
        """

        def FilterFile(file_path):
            return extension is None or file_path.endswith(extension)

        files = self._CollectFiles(
            src_dir, destination, include_file=FilterFile
        )
        if not files:
            logging.info("No data found for %s, skip bundle artifact", tarball)
            raise NoArtifactsToBundleError(f"No {extension} files in {src_dir}")

        now = datetime.datetime.strftime(datetime.datetime.now(), "%Y%m%d")
        name = f"{self.build_target}.{now}.{tarball}.tar.xz"
        output_compressed = os.path.join(self.output_dir, name)
        cros_build_lib.CreateTarball(
            output_compressed, destination, inputs=files
        )

        return output_compressed

    def _BundleToolchainWarningLogs(self):
        """Bundle the compiler warnings for upload for werror checker."""
        with self.chroot.tempdir() as tempdir:
            try:
                return [
                    self._CreateBundle(
                        "/tmp/fatal_clang_warnings",
                        "fatal_clang_warnings",
                        tempdir,
                        ".json",
                    )
                ]
            except NoArtifactsToBundleError:
                return []

    def _BundleClangCrashDiagnoses(self):
        """Bundle all clang crash diagnoses in chroot for uploading.

        See bugs.chromium.org/p/chromium/issues/detail?id=1056904 for context.
        """
        with osutils.TempDir(prefix="clang_crash_diagnoses_tarball") as tempdir:
            try:
                return [
                    self._CreateBundle(
                        "/tmp/clang_crash_diagnostics",
                        "clang_crash_diagnoses",
                        tempdir,
                    )
                ]
            except NoArtifactsToBundleError:
                return []

    def _BundleCompilerRusageLogs(self):
        """Bundle the rusage files created by compiler invocations.

        This is useful for monitoring changes in compiler performance.
        These files are created when the TOOLCHAIN_RUSAGE_OUTPUT variable
        is set in the environment for monitoring compiler performance.
        """
        with self.chroot.tempdir() as tempdir:
            try:
                return [
                    self._CreateBundle(
                        "/tmp/compiler_rusage",
                        "compiler_rusage_logs",
                        tempdir,
                        ".json",
                    )
                ]
            except NoArtifactsToBundleError:
                return []


def PrepareForBuild(
    artifact_name,
    chroot,
    sysroot_path,
    build_target,
    input_artifacts,
    profile_info,
):
    """Prepare for building artifacts.

    This code is called OUTSIDE the chroot, before it is set up.

    Args:
      artifact_name: artifact name
      chroot: chroot_lib.Chroot instance for chroot.
      sysroot_path: path to sysroot, relative to chroot path, or None.
      build_target: name of build target, or None.
      input_artifacts: List(InputArtifactInfo) of available artifact locations.
      profile_info: dict(key=value)  See ArtifactProfileInfo.

    Returns:
      PrepareForBuildReturn
    """

    return PrepareForBuildHandler(
        artifact_name,
        chroot,
        sysroot_path,
        build_target,
        input_artifacts=input_artifacts,
        profile_info=profile_info,
    ).Prepare()


def BundleArtifacts(
    name, chroot, sysroot_path, build_target, output_dir, profile_info
):
    """Prepare for building artifacts.

    This code is called OUTSIDE the chroot, after it is set up.

    Args:
      name: artifact name
      chroot: chroot_lib.Chroot instance for chroot.
      sysroot_path: path to sysroot, relative to chroot path.
      chrome_root: path to chrome root.
      build_target: name of build target
      output_dir: path in which to place the artifacts.
      profile_info: dict(key=value)  See ArtifactProfileInfo.

    Returns:
      list of artifacts, relative to output_dir.
    """
    return BundleArtifactHandler(
        name,
        chroot,
        sysroot_path,
        build_target,
        output_dir,
        profile_info=profile_info,
    ).Bundle()


class GetUpdatedFilesHandler(object):
    """Find all changed files in the checkout and create a commit message."""

    @staticmethod
    def _UpdateKernelMetadata(kernel_version: str, profile_version: str):
        """Update afdo_metadata json file"""
        kernel_version = kernel_version.replace(".", "_")
        json_file = os.path.join(
            TOOLCHAIN_UTILS_PATH,
            "afdo_metadata",
            f"kernel_afdo_{kernel_version}.json",
        )
        assert os.path.exists(
            json_file
        ), f"Metadata for {kernel_version} does not exist"
        afdo_versions = json.loads(osutils.ReadFile(json_file))
        kernel_name = f"chromeos-kernel-{kernel_version}"
        assert (
            kernel_name in afdo_versions
        ), f"To update {kernel_name}, the entry should be in kernel_afdo.json"
        old_value = afdo_versions[kernel_name]["name"]
        update_to_newer_profile = _RankValidCWPProfiles(
            old_value
        ) < _RankValidCWPProfiles(profile_version)
        # This function is called after Bundle, so normally the profile is newer
        # is guaranteed because Bundle function only runs when a new profile is
        # needed to verify at the beginning of the builder. This check is to
        # make sure there's no other updates happen between the start of the
        # builder and the time of this function call.
        assert update_to_newer_profile, (
            f"Failed to update JSON file because {profile_version} is not "
            f"newer than {old_value}"
        )
        afdo_versions[kernel_name]["name"] = profile_version
        pformat.json(afdo_versions, fp=json_file)
        return [json_file]

    def __init__(self, artifact_type, artifact_path, profile_info):
        self.artifact_path = artifact_path
        self.profile_info = profile_info
        if artifact_type == "VerifiedKernelCwpAfdoFile":
            self._update_func = self.UpdateKernelProfileMetadata
        else:
            raise GetUpdatedFilesForCommitError(
                f"{artifact_type} has no handler in GetUpdatedFiles"
            )

    def UpdateKernelProfileMetadata(self):
        kernel_version = self.profile_info.get("kernel_version")
        if not kernel_version:
            raise GetUpdatedFilesForCommitError("kernel_version not provided")
        # The path obtained from artifact_path is the full path, containing
        # extension, so we need to remove it here.
        profile_version = os.path.basename(self.artifact_path).replace(
            KERNEL_AFDO_COMPRESSION_SUFFIX, ""
        )
        files = self._UpdateKernelMetadata(kernel_version, profile_version)
        commit_message = (
            f"afdo_metadata: Publish new kernel profiles for {kernel_version}\n\n"
            f"Update {kernel_version} to {profile_version}\n\n"
            "Automatically generated in kernel verifier.\n\n"
            "BUG=None\n"
            "TEST=Verified in kernel-release-afdo-verify-orchestrator\n"
        )
        return files, commit_message

    def Update(self):
        return self._update_func()


def GetUpdatedFiles(artifact_type, artifact_path, profile_info):
    return GetUpdatedFilesHandler(
        artifact_type, artifact_path, profile_info
    ).Update()
