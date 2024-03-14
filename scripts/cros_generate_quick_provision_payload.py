# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script to generate ChromiumOS provision payloads."""

import os

from chromite.lib import commandline
from chromite.lib import parallel
from chromite.lib.paygen import paygen_provision_payload
from chromite.lib.paygen import paygen_stateful_payload_lib


def ParseArguments(argv):
    """Returns a namespace for the CLI arguments."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image",
        type="str_path",
        required=True,
        help="The path to local image to build the quick "
        "provision payloads for.",
    )
    parser.add_argument(
        "--output",
        type="str_path",
        help="The output directory to generate quick "
        "provision payloads for.",
        default=".",
    )

    opts = parser.parse_args(argv)
    # Check if output is valid directory.
    if not os.path.isdir(opts.output):
        parser.error("Please pass in a valid output directory.")

    opts.Freeze()

    return opts


def main(argv) -> None:
    opts = ParseArguments(argv)

    parallel.RunParallelSteps(
        [
            # Stateful generation is usually the slowest.
            lambda: paygen_stateful_payload_lib.GenerateStatefulPayload(
                opts.image, opts.output
            ),
            lambda: paygen_stateful_payload_lib.GenerateZstdStatefulPayload(
                opts.image, opts.output
            ),
            lambda: paygen_provision_payload.GenerateProvisionPayloads(
                opts.image, opts.output
            ),
        ]
    )
