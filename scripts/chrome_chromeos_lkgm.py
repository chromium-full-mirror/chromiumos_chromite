# Copyright 2017 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Update the CHROMEOS_LKGM file in a chromium repository.

This script will upload an LKGM CL and potentially submit it to the CQ.
"""

import logging
from typing import Optional, Tuple

from chromite.lib import chromeos_version
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import gerrit
from chromite.lib import gob_util
from chromite.utils import hostname_util


# Gerrit hashtag for the LKGM Uprev CLs.
HASHTAG = "chrome-lkgm"

# Keys for git footers
GIT_FOOTER_EXTERNAL_MANIFEST_POS = "CrOS-External-Manifest-Position"
GIT_FOOTER_INTERNAL_MANIFEST_POS = "CrOS-Internal-Manifest-Position"
GIT_FOOTER_LKGM = "CrOS-LKGM"


class LKGMNotValid(Exception):
    """The LKGM version is unset or not newer than the current value."""


class LKGMFileNotFound(Exception):
    """Raised if the LKGM file is not found."""


class ChromeLKGMCleaner:
    """Responsible for cleaning up the existing LKGM CLs if necessary.

    In Particular, this class does:
        - abandoning the obsolete CLs
        - rebasing the merge-conflicted CLs
    """

    def __init__(
        self,
        branch: str,
        current_lkgm: chromeos_version.VersionInfo,
        user_email: str,
        dryrun: bool = False,
        buildbucket_id: Optional[str] = None,
    ) -> None:
        self._dryrun = dryrun
        self._branch = branch
        self._gerrit_helper = gerrit.GetCrosExternal()
        self._buildbucket_id = buildbucket_id

        self._user_email = user_email

        # Strip any chrome branch from the lkgm version.
        self._current_lkgm = current_lkgm

    def ProcessObsoleteLKGMRolls(self) -> None:
        """Clean up all obsolete LKGM roll CLs by abandoning or rebasing.

        This method finds the LKGM roll CLs that were trying changing to an
        older version than the current LKGM version, and abandons them.
        """
        query_params = {
            "project": constants.CHROMIUM_SRC_PROJECT,
            "branch": self._branch,
            "file": constants.PATH_TO_CHROME_LKGM,
            "status": "open",
            "hashtag": HASHTAG,
            # Use 'owner' rather than 'uploader' or 'author' since those last
            # two can be overwritten when the gardener resolves a merge-conflict
            # and uploads a new patchset.
            "owner": self._user_email,
        }
        open_changes = self._gerrit_helper.Query(**query_params)
        if not open_changes:
            logging.info("No old LKGM rolls detected.")
            return

        logging.info(
            "Retrieved the current LKGM version: %s",
            self._current_lkgm.VersionString(),
        )

        build_link = ""
        if self._buildbucket_id:
            build_link = (
                "\nUpdated by"
                f" https://ci.chromium.org/b/{self._buildbucket_id}\n"
            )

        for change in open_changes:
            logging.info(
                "Found a open LKGM roll CL: %s (crrev.com/c/%s).",
                change.subject,
                change.gerrit_number,
            )

            # Retrieve the version that this CL tries to roll to.
            roll_to_string = change.GetFileContents(
                constants.PATH_TO_CHROME_LKGM
            )
            if roll_to_string is None:
                logging.info("=> No LKGM change found in this CL.")
                continue

            roll_to = chromeos_version.VersionInfo(roll_to_string)
            if roll_to <= self._current_lkgm:
                # The target version that the CL is changing to is older than
                # the current. The roll CL is useless so that it'd be abandoned.
                logging.info(
                    "=> This CL is an older LKGM roll than current: Abandoning"
                )
                if not self._dryrun:
                    abandon_message = (
                        "The newer LKGM"
                        f" ({self._current_lkgm.VersionString()}) roll than"
                        f" this CL has been landed.{build_link}"
                    )
                    self._gerrit_helper.AbandonChange(
                        change,
                        msg=abandon_message,
                    )
                continue

            mergeable = change.IsMergeable()
            if mergeable is None:
                logging.info("=> Failed to get the mergeable state of the CL.")
                continue

            # This CL may be in "merge conflict" state. Resolve.
            if not mergeable:
                # Retrieve the version that this CL tries to roll from.
                roll_from_string = change.GetOriginalFileContents(
                    constants.PATH_TO_CHROME_LKGM
                )
                roll_from = chromeos_version.VersionInfo(
                    roll_from_string.strip()
                )

                if roll_from == self._current_lkgm:
                    # The CL should not be in the merge-conflict state.
                    # mergeable=False might come from other reason.
                    logging.info(
                        "=> This CL tries to roll from the same LKGM. "
                        "Doing nothing."
                    )
                    continue
                elif roll_from >= self._current_lkgm:
                    # This should not happen.
                    logging.info(
                        "=> This CL tries to roll from a newer LKGM. Maybe"
                        "LKGM in Chromium code has been rolled back. Anyway, "
                        "rebasing forcibly."
                    )

                else:
                    logging.info(
                        "=> This CL tries to roll from the older LKGM. "
                        "Rebasing."
                    )

                # Resolve the conflict by rebasing.
                if not self._dryrun:
                    change.Rebase(allow_conflicts=True)
                    self._gerrit_helper.ChangeEdit(
                        change.gerrit_number,
                        "chromeos/CHROMEOS_LKGM",
                        roll_to_string,
                    )
                continue

            logging.info("=> This CL is not in the merge-conflict state.")

    def Run(self) -> None:
        self.ProcessObsoleteLKGMRolls()


class ChromeLKGMCommitter:
    """Committer object responsible for obtaining and committing a new LKGM."""

    # The list of trybots we require LKGM updates to run and pass on before
    # landing. Since they're internal trybots, the CQ won't automatically
    # trigger them, so we have to explicitly tell it to. If you add a new
    # internal builder here, make sure it's also listed in
    # https://source.chromium.org/chromium/chromium/src/+/main:infra/config/subprojects/chrome/try.star.
    _PRESUBMIT_BOTS = {
        "luci.chrome.try": (
            "chromeos-betty-chrome",
            "chromeos-brya-chrome",
            "chromeos-jacuzzi-chrome",
            "chromeos-reven-chrome",
            "chromeos-volteer-chrome-skylab",
        ),
        "luci.chromium.try": (
            "chromeos-octopus-rel",
            "chromeos-jacuzzi-rel",
        ),
    }
    # Files needed in a local checkout to successfully update the LKGM. The
    # OWNERS file allows the --tbr-owners mechanism to select an appropriate
    # OWNER to TBR. TRANSLATION_OWNERS is necessary to parse CHROMEOS_OWNERS
    # file since it has the reference.
    _NEEDED_FILES = (
        constants.PATH_TO_CHROME_CHROMEOS_OWNERS,
        constants.PATH_TO_CHROME_LKGM,
        "tools/translation/TRANSLATION_OWNERS",
    )
    # First line of the commit message for all LKGM CLs.
    _COMMIT_MSG_HEADER = "Automated Commit: LKGM %(lkgm)s for chromeos."

    def __init__(
        self,
        lkgm: str,
        branch: str,
        current_lkgm: chromeos_version.VersionInfo,
        dryrun: bool = False,
        buildbucket_id: Optional[str] = None,
        message: Optional[str] = None,
        external_manifest_position: Optional[int] = None,
        internal_manifest_position: Optional[int] = None,
    ) -> None:
        self._dryrun = dryrun
        self._branch = branch
        self._buildbucket_id = buildbucket_id
        self._gerrit_helper = gerrit.GetCrosExternal()

        # Next LKGM, which is going to be updated to by an uprev CL.
        # Strip any chrome branch from the lkgm version.
        self._lkgm = chromeos_version.VersionInfo(lkgm).VersionString()

        # Current LKGM, which is going to be updated from.
        self._current_lkgm = current_lkgm

        self._commit_msg_header = self._COMMIT_MSG_HEADER % {"lkgm": self._lkgm}
        self._message = message
        self._external_manifest_position = external_manifest_position
        self._internal_manifest_position = internal_manifest_position

        # Storing metadata in the git footer for automated processing.
        self._footers = {GIT_FOOTER_LKGM: self._lkgm}
        if buildbucket_id:
            self._footers["Cr-Build-Id"] = str(buildbucket_id)
        if external_manifest_position:
            self._footers[
                GIT_FOOTER_EXTERNAL_MANIFEST_POS
            ] = external_manifest_position
        if internal_manifest_position:
            self._footers[
                GIT_FOOTER_INTERNAL_MANIFEST_POS
            ] = internal_manifest_position

        if not self._lkgm:
            if self._dryrun:
                self._lkgm = "9999999.99.99"
                logging.info("dry run, using version %s", self._lkgm)
            else:
                raise LKGMNotValid("LKGM not provided.")
        logging.info("lkgm=%s", lkgm)

    def Run(self) -> None:
        self.UpdateLKGM()

    @property
    def lkgm_file(self):
        return self._committer.FullPath(constants.PATH_TO_CHROME_LKGM)

    def UpdateLKGM(self) -> None:
        """Updates the LKGM file with the new version."""
        if chromeos_version.VersionInfo(self._lkgm) <= self._current_lkgm:
            raise LKGMNotValid(
                f"LKGM version ({self._lkgm}) is not newer than current version"
                f" ({self._current_lkgm.VersionString()})."
            )

        logging.info(
            "Updating LKGM version: %s (was %s),",
            self._lkgm,
            self._current_lkgm.VersionString(),
        )
        change = self._gerrit_helper.CreateChange(
            "chromium/src", self._branch, self.ComposeCommitMsg(), False
        )
        self._gerrit_helper.ChangeEdit(
            change.gerrit_number, "chromeos/CHROMEOS_LKGM", self._lkgm
        )

        if self._dryrun:
            logging.info(
                "Would have applied CQ+2 to crrev.com/c/%s",
                change.gerrit_number,
            )
            self._gerrit_helper.AbandonChange(
                change,
                msg="Dry run",
            )
            return

        labels = {
            "Bot-Commit": 1,
            "Commit-Queue": 2,
        }
        logging.info(
            "Applying %s to crrev.com/c/%s", labels, change.gerrit_number
        )
        self._gerrit_helper.SetReview(
            change.gerrit_number,
            labels=labels,
            notify="NONE",
            ready=True,
            reviewers=[constants.CHROME_GARDENER_REVIEW_EMAIL],
        )
        self._gerrit_helper.SetHashtags(change.gerrit_number, [HASHTAG], [])

    def ComposeCommitMsg(self):
        """Constructs and returns the commit message for the LKGM update."""
        message = ""
        if self._message:
            message += self._message
            message += "\n\n"

        changelog = ""
        if self._external_manifest_position or self._internal_manifest_position:
            (external_pos, internal_pos) = self.GetCurrentManifestPosition()
            if self._external_manifest_position and external_pos:
                changelog += (
                    "- External: http://go/cros-changes/"
                    + f"{external_pos}..{self._external_manifest_position}"
                    + "?ext=true\n"
                )
            if self._internal_manifest_position and internal_pos:
                changelog += (
                    "- Internal: http://go/cros-changes/"
                    + f"{internal_pos}..{self._internal_manifest_position}\n"
                )
        if changelog:
            changelog = (
                "CrOS Changes "
                + f"({self._current_lkgm.VersionString()} -> {self._lkgm}):\n"
                + changelog
                + "\n"
            )

        build_link = ""
        if self._buildbucket_id:
            build_link = "Uploaded by https://ci.chromium.org/b/%s\n\n" % (
                self._buildbucket_id
            )

        cq_includes = ""
        if self._branch == "main":
            for group, bots in self._PRESUBMIT_BOTS.items():
                for bot in bots:
                    cq_includes += "CQ_INCLUDE_TRYBOTS=%s:%s\n" % (group, bot)
            cq_includes += "\n"

        dry_run_message = ""
        if self._dryrun:
            dry_run_message = (
                "This CL was created during a dry run and is not "
                "intended to be committed.\n\n"
            )

        footers = ""
        for key, value in self._footers.items():
            footers += f"{key}: {value}\n"

        commit_msg_template = (
            "%(header)s\n\n"
            "%(message)s"
            "%(changelog)s"
            "%(dry_run_message)s"
            "%(build_link)s"
            "%(cq_includes)s"
            "%(footers)s"
        )
        return commit_msg_template % dict(
            header=self._commit_msg_header,
            message=message,
            changelog=changelog,
            cq_includes=cq_includes,
            build_link=build_link,
            dry_run_message=dry_run_message,
            footers=footers,
        )

    def GetCurrentManifestPosition(self) -> Tuple[Optional[str], Optional[str]]:
        """Retrieves the positions of the current manifests.

        This retrieves the pair of positions of external and internal manifests
        by reading the previous uprev CL.

        Returns:
            Tuple of following two values:
            - Git position of external manifest of the current LKGM. None if
                number does not exists.
            - Git position of internal manifest of the current LKGM. None if
                number does not exists.
        """
        current_lkgm = self._current_lkgm.VersionString()
        cls = self._gerrit_helper.Query(
            hashtag="chrome-lkgm",
            branch="main",
            status="merged",
            footer=f"{GIT_FOOTER_LKGM}={current_lkgm}",
        )

        logging.info("found %d CLs", len(cls))

        # Making the ebavior deterministic.
        cls.sort(key=lambda patch: patch.gerrit_number, reverse=True)

        # There should be only 1 CL, unless someone has manually created a
        # duplicated uprev CL. But supporting multiple CLs just in case.
        for cl in cls:
            external_manifest_pos = None
            internal_manifest_pos = None
            for key, value in cl.footers:
                if key == GIT_FOOTER_EXTERNAL_MANIFEST_POS:
                    external_manifest_pos = value
                elif key == GIT_FOOTER_INTERNAL_MANIFEST_POS:
                    internal_manifest_pos = value
            if external_manifest_pos or internal_manifest_pos:
                return (
                    external_manifest_pos,
                    internal_manifest_pos,
                )
        return (None, None)


def GetCurrentLKGM(branch: str) -> chromeos_version.VersionInfo:
    """Returns the current LKGM version on the branch.

    On the first call, this method retrieves the LKGM version from Gitiles
    server and returns it. On subsequent calls, this method returns the
    cached LKGM version.

    Raises:
        LKGMNotValid: if the retrieved LKGM version from the repository is
        invalid.
    """
    current_lkgm = gob_util.GetFileContents(
        constants.CHROMIUM_GOB_URL,
        constants.PATH_TO_CHROME_LKGM,
        ref=branch,
    )
    if current_lkgm is None:
        raise LKGMNotValid(
            "The retrieved LKGM version from the repository is invalid:"
            f" {current_lkgm}."
        )

    return chromeos_version.VersionInfo(current_lkgm.strip())


def GetOpts(argv):
    """Returns a dictionary of parsed options.

    Args:
        argv: raw command line.

    Returns:
        Dictionary of parsed options.
    """
    parser = commandline.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument(
        "--dryrun",
        action="store_true",
        default=False,
        help="Don't commit changes or send out emails.",
    )
    parser.add_argument(
        "--message",
        action="store",
        help="Extra message to add to the description of the generated CL.",
    )
    parser.add_argument(
        "--force-overriding-user",
        help="[For debugging] Forcibly overrides the user to manipulate "
        "Gerrit, instead of determining it from the hostname.",
    )
    parser.add_argument("--lkgm", help="LKGM version to update to.")
    parser.add_argument(
        "--buildbucket-id",
        help="Buildbucket ID of the build that ran this script. "
        "Will be linked in the commit message if specified.",
    )
    parser.add_argument(
        "--branch",
        default="main",
        help="Branch to upload change to, e.g. "
        "refs/branch-heads/5112. Defaults to main.",
    )
    parser.add_argument(
        "--internal-manifest-position",
        type=int,
        help="Annealing commit position of the internal manifest.",
    )
    parser.add_argument(
        "--external-manifest-position",
        type=int,
        help="Annealing commit position of the external manifest.",
    )
    return parser.parse_args(argv)


def main(argv):
    opts = GetOpts(argv)
    current_lkgm = GetCurrentLKGM(opts.branch)

    if opts.lkgm is not None:
        committer = ChromeLKGMCommitter(
            opts.lkgm,
            opts.branch,
            current_lkgm,
            opts.dryrun,
            opts.buildbucket_id,
            message=opts.message,
            internal_manifest_position=opts.internal_manifest_position,
            external_manifest_position=opts.external_manifest_position,
        )
        committer.Run()

    # We need to know the account used by the builder to upload git CLs when
    # listing up CLs.
    user_email = ""
    if opts.force_overriding_user:
        user_email = opts.force_overriding_user
    elif hostname_util.host_is_ci_builder(golo_only=True):
        user_email = "chromeos-commit-bot@chromium.org"
    elif hostname_util.host_is_ci_builder(gce_only=True):
        user_email = "3su6n15k.default@developer.gserviceaccount.com"
    else:
        raise LKGMFileNotFound("Failed to determine an appropriate user email.")

    cleaner = ChromeLKGMCleaner(
        opts.branch,
        current_lkgm,
        user_email,
        opts.dryrun,
        opts.buildbucket_id,
    )
    cleaner.Run()

    return 0
