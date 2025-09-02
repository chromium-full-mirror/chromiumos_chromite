# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Satlab Monitor Controller.

Handles the endpoint for scheduling the update and restart of satlabs
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
    """Mock success output for the SatlabMonitor endpoint."""

    # Successful response is the default protobuf, so no need to fill it out.


@faux.success(_MockSuccess)
@faux.empty_error
@validate.validation_complete
def RunSatlabMonitor(request, response, _config):
    """Run Satlab Monitor. Translate the input protobuf to CLI args."""

    cmd = [
        constants.SOURCE_ROOT / "infra/satlab_monitor/monitor.py",
        "--log-level",
        "INFO",
    ]
    if request.host_id:
        cmd.extend(
            [
                "--host",
                request.host_id,
            ]
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        json_output_path = Path(temp_dir) / "satlab_monitor_output.json"
        cmd.extend(
            [
                "--json-out",
                json_output_path,
            ]
        )
        try:
            cros_build_lib.run(cmd)
        except cros_build_lib.RunCommandError:
            # In case of failure, load details about the error from Satlab
            # Monitor's JSON output into the output protobuf. (If Satlab Monitor
            # ran successfully, the default values are simply used). Satlab
            # Monitor's output matches the JSON representation of the
            # RunSatlabMonitorResponse protobuf.

            if not json_output_path.exists():
                return controller.RETURN_CODE_UNRECOVERABLE

            json_format.Parse(json_output_path.read_text(), response)
            return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE
