#!/usr/bin/env python3
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""CR and CQ +2 copybot project commits for downstreaming.

See go/copybot

For Zephyr Downstreaming Rotation: go/zephyr-downstreaming-guide
For coreboot Downstreaming Rotation: go/coreboot:downstreaming
"""

from collections import defaultdict
import logging
import re
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from chromite.contrib.copybot_downstream_config import downstream_argparser
from chromite.lib import config_lib
from chromite.lib import gerrit


# Gerrit will merge a max of 240 dependencies. Leave some room
# for dependencies from the platform/ec repo.
MAX_GERRIT_CHANGES = 225
REVIEWER_KEY_TEXT = "Original-Reviewed-by"


class PathDomains(NamedTuple):
    """A filepath and the domains that must review it."""

    path: str
    domains: List[str]


class CopybotDownstream:
    """Defines the functionality of the downstreaming review process."""

    def __init__(
        self,
        project: str,
        dry_run: bool = False,
        cq_dry_run: bool = False,
        limit: Optional[int] = None,
        stop_at: Optional[str] = None,
        ignore_warnings: bool = False,
    ):
        """Initialize the CopybotDownstream Object.

        Args:
            project: Name of the project to be acted on.
            dry_run: If True dry-run this pass without acting on gerrit
            cq_dry_run: If True, use CQ+1 instead of CQ+2
            limit: Limit the number of CL's to be downstreamed
            stop_at: Stop at the specified change(CL Number)
            ignore_warnings: Ignore warnings and submit changes
        """
        self.gerrit_helper = gerrit.GetGerritHelper(
            config_lib.GetSiteParams().EXTERNAL_REMOTE
        )
        # Map of functions to be called when the project in the key is
        # encountered.
        #
        # List of tuples(function, list of arguments) where the format of the
        # list can vary across functions.
        #
        # Functions should take a CL and perform any additional checks required
        # by the project prior to downstreaming.
        #
        #    Args:
        #        gerrit CL dict for use in parsing
        #        dynamic args for use in parsing
        #    Returns:
        #        List of warning strings to be printed for this CL
        self.project = project
        self.dry_run = dry_run
        self.cq_dry_run = cq_dry_run
        self.stop_at = stop_at
        self.ignore_warnings = ignore_warnings
        # dict of dicts containing CL info returned by gerrit.
        #   Key - CL Number
        #   Value - Gerrit dictionary data
        self.cl_info = {}
        if not limit or limit > MAX_GERRIT_CHANGES:
            logging.info(
                "Limiting to maximum Gerrit changes (%d)", MAX_GERRIT_CHANGES
            )
            limit = MAX_GERRIT_CHANGES
        self.limit = limit
        default_check_funcs = [
            [self.check_commit_message, ["\nC[Qq]-Depend:.*"]],
            [self.check_hashtags, ["copybot-skip"]],
        ]
        self.check_funcs = default_check_funcs + self._project_check_funcs()

    def _project_check_funcs(self) -> List[List[Tuple[Callable, List]]]:
        """Return a list of checkers specific to this project config.

        Since this is the general-case class, there are no project-specific
        checkers. Subclasses should override this function to define their
        specific needs.
        """
        return []

    @staticmethod
    def project_passed_downstreamer_review_paths_check(
        cl: Dict, paths: List[str]
    ) -> List[str]:
        """Check paths that require further downstreamer review.

        * Require additional review from any paths specified by paths.

        Args:
            cl: gerrit CL dict for use in parsing.
            paths: paths to check for this project.

        Returns:
            warning_strings a list of strings to be printed for this CL.
            * This must match the expected prototype used in check_funcs.
        """
        warning_strings = []
        revision = cl["revisions"][cl["current_revision"]]
        for path in paths:
            if any(path in s for s in revision["files"]):
                warning_strings.append(
                    f"Found filepath({path}) which requires downstreamer review"
                )
        return warning_strings

    @staticmethod
    def project_passed_domain_restricted_paths_check(
        cl: Dict, paths_domains: List[PathDomains]
    ) -> List[str]:
        """Check paths that require further downstreamer review.

        * Require additional review if changes to paths specified by paths
            are not reviewed by anyone in the domain list specified by paths.

        Args:
            cl: gerrit CL dict for use in parsing.
            paths_domains: list of tuples(path, restricted_domains), where path
                is the path to be restricted, and restricted_domains is a list
                of domains that should have been a part of the review.

        Returns:
            warning_strings a list of strings to be printed for this CL.
            * This must match the expected prototype used in check_funcs.
        """
        warning_strings = []
        revision = cl["revisions"][cl["current_revision"]]
        reviewers = []
        for line in revision["commit"]["message"].splitlines():
            if line.startswith(REVIEWER_KEY_TEXT):
                reviewers.append(line[(len(REVIEWER_KEY_TEXT) + 1) :])
        for path, domains in paths_domains:
            if any(path in s for s in revision["files"]):
                reviewer_found = False
                for domain in domains:
                    if any(domain in s for s in reviewers):
                        reviewer_found = True
                if not reviewer_found:
                    warning_strings.append(
                        f"Found filepath({path}) which requires"
                        f" downstreamer review fromdomain(s) {str(domains)}"
                    )
        return warning_strings

    @staticmethod
    def check_commit_message(cl: Dict, args: List[str]) -> List[str]:
        """Check commit message for keywords.

        * Throw warning if keywords found in commit message.
            This can be useful for banned words as well as logistical issues
                such as CL's with CQ-Depend.

        Args:
            cl: gerrit CL dict for use in parsing.
            args: list of keywords to flag.

        Returns:
            warning_strings a list of strings to be printed for this CL.
            * This must match the expected prototype used in check_funcs.
        """
        warning_strings = []
        for banned_term in args:
            if re.search(
                banned_term,
                cl["revisions"][cl["current_revision"]]["commit"]["message"],
            ):
                printable_term = "".join(banned_term.splitlines())
                warning_strings.append(f"Found {printable_term} in change!")
        return warning_strings

    @staticmethod
    def check_hashtags(cl: Dict, args: List[str]) -> List[str]:
        """Check hashtags for keywords.

        * Throw warning if keywords found in hashtags..

        Args:
            cl: gerrit CL dict for use in parsing.
            args: list of keywords to flag.

        Returns:
            warning_strings a list of strings to be printed for this CL.
            * This must match the expected prototype used in checks.
        """
        warning_strings = []
        for banned_hashtag in args:
            if banned_hashtag in cl["hashtags"]:
                warning_strings.append(
                    f"Change marked with hashtag {banned_hashtag}"
                )
        return warning_strings

    def _find_cls_to_downstream(self) -> List[Dict]:
        """Find all CLs to downstream for the given project.

        Returns:
            A list of Gerrit CL dicts to downstream, including those which
            have the {project}-downstream topic and the CLs to which they
            are related.
        """
        copybot_downstream_cls = self.gerrit_helper.Query(
            topic=f"{self.project}-downstream",
            status="open",
            raw=True,
            verbose=True,
            convert_results=False,
        )
        return copybot_downstream_cls

    def _check_cl(
        self,
        downstream_candidate_cl: Dict,
    ) -> List[str]:
        """Check whether the given CL is OK to downstream.

        Args:
            downstream_candidate_cl: dict representing the CL that we want to
                downstream.

        Returns:
            warnings: A list of warning strings stating problems with the CL.
            If empty, that means there are no problems.
        """
        warnings = []
        logging.info("Processing %s", downstream_candidate_cl["_number"])
        logging.debug(
            "change info:\n\t%s",
            "\n\t".join(f"{k}:{v}" for k, v in downstream_candidate_cl.items()),
        )
        for func, extra_args in self.check_funcs:
            tmp_warnings = func(downstream_candidate_cl, extra_args)
            if tmp_warnings:
                warnings.extend(tmp_warnings)

        return warnings

    def _filter_cls(self, cls_to_downstream: List[str]) -> List[Dict]:
        """Filter full CL list based on:

            The limit.
            CL the chain should stop at.
            copybot-skip hashtag.

        Args:
            cls_to_downstream: Ordered list of all candidate CL numbers to be
                downstreamed.

        Returns:
            cls_to_downstream: Ordered list of filtered CL numbers to be
            downstreamed.
        """
        filtered_cls = []
        for change_num in cls_to_downstream:
            if self.stop_at and self.stop_at == change_num:
                logging.info(
                    "Matched change: %s, stop processing other changes",
                    change_num,
                )
                break
            if self.check_hashtags(self.cl_info[change_num], ["copybot-skip"]):
                continue
            filtered_cls.append(change_num)
        return filtered_cls[: self.limit]

    def _get_related_cls(self, change_number: str) -> List[str]:
        """Get the list of related CLs for the passed in CL number.

        Args:
            change_number: CL to find relationships of.

        Returns:
            List of strings containing related CL numbers.
        """
        return [
            x["_change_number"]
            for x in self.gerrit_helper.GetRelatedChangesInfo(change_number)[
                "changes"
            ]
            if x["status"] == "NEW"
        ]

    def _act_on_cls(self, cls_to_downstream: List[str]) -> None:
        """Perform Gerrit updates on the CLs to downstream.

        Args:
            cls_to_downstream: Ordered list of all CL candidates to be
                downstreamed.
        """
        # TODO(b/278748163): Investigate bulk changes instead.
        for i, change_num in enumerate(cls_to_downstream):
            logging.info(
                "Downstreaming %s: %d/%d",
                change_num,
                i + 1,
                len(cls_to_downstream),
            )

            self.gerrit_helper.SetReviewers(
                change=change_num, dryrun=self.dry_run, notify="NONE"
            )
            self.gerrit_helper.SetReview(
                change=change_num,
                dryrun=self.dry_run,
                # Add Verified label because client POST removes it.
                labels={
                    "Verified": "1",
                    "Code-Review": "2",
                    "Commit-Queue": "1" if self.cq_dry_run else "2",
                },
            )

    def _handle_checks_results(self, all_warnings: List[str]) -> int:
        """Perform Gerrit updates on the CLs to downstream.

        Args:
            all_warnings: A dictionary of lists of warning strings stating
                problems with these CLs.
                Key: CL number with warnings
                Value: List of warnings (str) found in the CL associated with
                    the key. If empty, that means there are no problems.

        Returns:
            0 if warnings are acceptable/ignored.
            1 if the script should exit due to warnings.
        """
        if all_warnings:
            for cl_num, warnings in all_warnings.items():
                logging.warning(
                    "http://crrev/c/%s Found warnings in change:\n\t%s",
                    cl_num,
                    "\n\t".join(warning for warning in warnings),
                )
            if not self.ignore_warnings:
                logging.error(
                    "Warnings detected in this run.  Please address"
                    " them.\n\t\tTo ignore the listed warnings, rerun with"
                    " --ignore-warnings"
                )
                return 1
        return 0

    def cmd_downstream(self):
        """Downstream copybot project CLs."""

        copybot_downstream_cls = self._find_cls_to_downstream()

        if not copybot_downstream_cls:
            logging.info("No %s CLs to downstream!", self.project)
            return 0

        all_warnings = defaultdict(list)
        cls_to_downstream = []

        for change in copybot_downstream_cls:
            logging.debug("Top level Change: %s", change["_number"])
            if change["_number"] not in cls_to_downstream:
                cls_to_downstream.append(change["_number"])
                self.cl_info[change["_number"]] = change
                logging.debug("\tAdded to list")
            for related_change_number in self._get_related_cls(
                change["_number"]
            ):
                logging.debug("\trelated Change: %s", related_change_number)
                if related_change_number in cls_to_downstream:
                    logging.debug(
                        "\t\tSkipping this one since it already exists"
                    )
                    continue
                self.cl_info[
                    related_change_number
                ] = self.gerrit_helper.GetChangeDetail(
                    related_change_number, verbose=True
                )
                cls_to_downstream.append(related_change_number)

        for change_num, change in self.cl_info.items():
            warnings = self._check_cl(change)
            if warnings:
                all_warnings[change_num] = warnings

        # CL dependencies come in with newest first, so do reverse.
        cls_to_downstream.reverse()
        result = self._handle_checks_results(all_warnings)
        if result != 0:
            return result
        cls_to_downstream = self._filter_cls(cls_to_downstream)
        logging.info(
            "Downstreaming the following CLs:\n%s",
            "\n".join(str(change_num) for change_num in cls_to_downstream),
        )

        self._act_on_cls(cls_to_downstream)

        logging.info("All finished! Remember to monitor the CQ!")
        return 0

    def cmd_clear_attention(self):
        """Remove user from attention set on merged CLs."""

        cls_to_modify = self.gerrit_helper.Query(
            topic=f"{self.project}-downstream",
            status="merged",
            attention="me",
            raw=True,
        )
        cls_to_modify.sort(key=lambda patch: patch["number"])

        if self.limit:
            cls_to_modify = cls_to_modify[: self.limit]

        counter = 0
        for cl in cls_to_modify:
            logging.info(
                "Updating attention set on CL %s (%d/%d)",
                cl["number"],
                counter + 1,
                len(cls_to_modify),
            )

            self.gerrit_helper.SetAttentionSet(
                change=cl["number"],
                remove=("me",),
                dryrun=self.dry_run,
                notify="NONE",
            )
            counter += 1

            if self.stop_at and self.stop_at == cl["number"]:
                break

        logging.info("Total CLs affected: %d", counter)
        return 0

    def run(self, cmd):
        if cmd is None:
            return self.cmd_downstream()
        if cmd == "clear_attention":
            return self.cmd_clear_attention()

        logging.error("Unknown subcommand %s", cmd)
        return 1


def main(args):
    """Main entry point for CLI."""
    parser = downstream_argparser.generate_copybot_arg_parser()
    opts = parser.parse_args(args)
    CopybotDownstream(
        opts.project,
        opts.dry_run,
        opts.cq_dry_run,
        opts.limit,
        opts.stop_at,
        opts.ignore_warnings,
    ).run(opts.cmd)
