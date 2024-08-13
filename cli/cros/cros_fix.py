# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Attempt automated fixes on the specified files."""

import logging

from chromite.cli import analyzers
from chromite.cli import command
from chromite.cli.cros import cros_format
from chromite.lib import cros_build_lib


@command.command_decorator("fix")
class FixCommand(analyzers.AnalyzerCommand):
    """Automatically fix format/lint/etc... issues."""

    # AnalyzerCommand overrides.
    can_modify_files = True
    use_dryrun_options = True

    def Run(self):
        if cros_build_lib.IsInsideChroot():
            logging.warning(
                "It's recommended to run `cros fix` outside the SDK."
            )

        files = self.options.files
        if not files:
            # Running with no arguments is allowed to make the repo upload hook
            # simple, but print a warning so that if someone runs this manually
            # they are aware that nothing was changed.
            logging.warning("No files provided.  Doing nothing.")
            return 0

        # TODO(build): Integrate linters that have a --fix option.
        cmd = cros_format.FormatCommand(self.options)
        return cmd.Run()
