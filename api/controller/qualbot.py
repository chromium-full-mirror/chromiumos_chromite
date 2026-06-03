# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Qualbot Controller.

Handles the endpoint for running qualbot and generating the protobuf.
"""

from pathlib import Path
import tempfile

from chromite.third_party.google.protobuf import json_format

from chromite.api import controller
from chromite.api import faux
from chromite.api import validate
from chromite.lib import constants
from chromite.lib import cros_build_lib


def _MockSuccess(_request, _response, _config) -> None:
    """Mock success output for the RunQualbot endpoint."""

    # Successful response is the default protobuf, so no need to fill it out.


@faux.success(_MockSuccess)
@faux.empty_error
@validate.validation_complete
def RunQualbot(request, response, _config):
    """Run qualbot. Translate all fields in the input protobuf to CLI args."""

    cmd = [
        constants.SOURCE_ROOT / "infra/fw_qual_automation/auto_qual_main.py",
        "--log-level",
        "INFO",
    ]

    with tempfile.TemporaryDirectory() as temp_dir:
        json_output_path = Path(temp_dir) / "qualbot_output.json"
        extra_cmd_arg = []
        if request.is_staging:
            match request.task:
                case "analyze-test-efforts":
                    extra_cmd_arg.append("--test-tables")
                case "auto-schedule":
                    extra_cmd_arg.append("--dry-run")
        else:
            extra_cmd_arg.append("--upload")
        cmd.extend(
            [
                "--json-out",
                json_output_path,
                request.task,
                "--add-message",
                f"Cr-Build-Id: {request.build_id}\n"
                "Cr-Build-Url: "
                "https://cr-buildbucket.appspot.com/"
                f"build/{request.build_id}",
                "--bot",
            ]
        )
        cmd.extend(extra_cmd_arg)
        try:
            cros_build_lib.run(cmd)
        except cros_build_lib.RunCommandError:
            # In case of failure, load details about the error from QualBot's
            # JSON output into the output protobuf. (If QualBot ran
            # successfully, the default values are simply used). QualBot's
            # output matches the JSON representation of the RunQualbotResponse
            # protobuf.

            if not json_output_path.exists():
                return controller.RETURN_CODE_UNRECOVERABLE

            return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
        finally:
            if json_output_path.exists():
                json_format.Parse(json_output_path.read_text(), response)
