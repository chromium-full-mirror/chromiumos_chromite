# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Copybot Controller.

Handles the endpoint for running copybot and generating the protobuf.
"""

from pathlib import Path
import tempfile

from chromite.third_party.google.protobuf import json_format

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.api.gen.chromite.api import copybot_pb2
from chromite.lib import constants
from chromite.lib import cros_build_lib


def _MockSuccess(_request, _response, _config) -> None:
    """Mock success output for the RunCopybot endpoint."""

    # Successful response is the default protobuf, so no need to fill it out.


@faux.success(_MockSuccess)
@faux.empty_error
@validate.validation_complete
def RunCopybot(request, response, _config):
    """Run copybot. Translate all fields in the input protobuf to CLI args."""

    cmd = [
        constants.SOURCE_ROOT / "src/platform/dev/contrib/copybot/copybot.py"
    ]

    if request.topic:
        cmd.extend(["--topic", request.topic])

    for label in request.labels:
        cmd.extend(["--label", label.label])

    for reviewer in request.reviewers:
        cmd.extend(["--re", reviewer.user])

    for cc in request.ccs:
        cmd.extend(["--cc", cc.user])

    if request.prepend_subject:
        cmd.extend(["--prepend-subject", request.prepend_subject])

    if (
        request.merge_conflict_behavior
        == copybot_pb2.RunCopybotRequest.MERGE_CONFLICT_BEHAVIOR_SKIP
    ):
        cmd.extend(["--merge-conflict-behavior", "SKIP"])

    if (
        request.merge_conflict_behavior
        == copybot_pb2.RunCopybotRequest.MERGE_CONFLICT_BEHAVIOR_FAIL
    ):
        cmd.extend(["--merge-conflict-behavior", "FAIL"])

    if (
        request.merge_conflict_behavior
        == copybot_pb2.RunCopybotRequest.MERGE_CONFLICT_BEHAVIOR_STOP
    ):
        cmd.extend(["--merge-conflict-behavior", "STOP"])

    if (
        request.merge_conflict_behavior
        == copybot_pb2.RunCopybotRequest.MERGE_CONFLICT_BEHAVIOR_ALLOW_CONFLICT
    ):
        cmd.extend(["--merge-conflict-behavior", "ALLOW_CONFLICT"])

    for exclude in request.exclude_file_patterns:
        cmd.extend(["--exclude-file-pattern", exclude.pattern])

    for ph in request.keep_pseudoheaders:
        cmd.extend(["--keep-pseudoheader", ph.name])

    if request.add_signed_off_by:
        cmd.append("--add-signed-off-by")

    if request.dry_run:
        cmd.append("--dry-run")

    for po in request.push_options:
        cmd.extend(["--push-option", po.opt])

    for hashtag in request.hashtags:
        cmd.extend(["--ht", hashtag.hashtag])

    if request.upstream_limit:
        cmd.extend(["--upstream-history-limit", str(request.upstream_limit)])

    if request.downstream_limit:
        cmd.extend(
            ["--downstream-history-limit", str(request.downstream_limit)]
        )

    for include_path in request.include_paths:
        cmd.extend(["--include-downstream", include_path.path])

    if request.build_id:
        cmd.extend(["--add-pseudoheader", f"Cr-Build-Id: {request.build_id}"])

    if request.build_url:
        cmd.extend(["--add-pseudoheader", f"Cr-Build-Url: {request.build_url}"])

    if request.job_name:
        cmd.extend(
            [
                "--add-pseudoheader",
                f"Copybot-Job-Name: {request.job_name.job_name}",
            ]
        )

    for skip_job_name in request.skip_job_names:
        cmd.extend(["--skip-job-name", skip_job_name.job_name])

    if request.upstream_hash:
        cmd.extend(["--upstream-history-starts-with", request.upstream_hash])

    if request.downstream_hash:
        cmd.extend(
            ["--downstream-history-starts-with", request.downstream_hash]
        )

    for skip_author in request.skip_authors:
        cmd.extend(["--skip-author-email", skip_author.user])

    for insert_into_msg in request.insert_msg:
        cmd.extend(
            [
                "--insert-into-msg",
                f"{insert_into_msg.line_number}:{insert_into_msg.insert_txt}",
            ]
        )

    cmd.append(
        f"{request.upstream.url}:"
        f"{request.upstream.branch}:"
        f"{request.upstream.subtree}"
    )
    cmd.append(
        f"{request.downstream.url}:"
        f"{request.downstream.branch}:"
        f"{request.downstream.subtree}"
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        json_output_path = Path(temp_dir) / "copybot_output.json"
        cmd.extend(["--json-out", json_output_path])

        try:
            cros_build_lib.run(cmd)
        except cros_build_lib.RunCommandError:
            # In case of failure, load details about the error from CopyBot's
            # JSON output into the output protobuf. (If CopyBot ran
            # successfully, the default values are simply used). CopyBot's
            # output matches the JSON representation of the RunCopybotResponse
            # protobuf.

            if not json_output_path.exists():
                return controller.RETURN_CODE_UNRECOVERABLE

            json_format.Parse(json_output_path.read_text(), response)
            return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
