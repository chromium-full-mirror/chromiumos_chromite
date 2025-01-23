# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing factory builders."""

from chromite.cbuildbot.builders import generic_builders
from chromite.cbuildbot.stages import workspace_stages


class BuildSpecBuilder(generic_builders.Builder):
    """Builder that generates new buildspecs.

    This build does four things.
      1) Uprev and commit ebuilds based on TOT.
      2) Increatement the ChromeOS version number.
      3) Generate a buildspec based on that version number.
      4) Launch child builds based on the buildspec.
    """

    def GetSyncInstance(self):
        """Returns an instance of a SyncStage that should be run."""
        return self._GetStageInstance(
            workspace_stages.WorkspaceSyncStage,
            build_root=self._run.options.workspace,
        )

    def RunStages(self) -> None:
        """Run the stages."""

        if not self._run.options.force_version:
            # If we were not given a specific buildspec to build, create one.
            self._RunStage(
                workspace_stages.WorkspaceUprevStage,
                build_root=self._run.options.workspace,
            )

            if not self._run.options.debug:
                # If this is not a tryjob, push uprevs and the buildspec.
                self._RunStage(
                    workspace_stages.WorkspacePublishStage,
                    build_root=self._run.options.workspace,
                )

                self._RunStage(
                    workspace_stages.WorkspacePublishBuildspecStage,
                    build_root=self._run.options.workspace,
                )

        if self._run.config.slave_configs:
            # If there are child builds to schedule, schedule them.
            self._RunStage(
                workspace_stages.WorkspaceScheduleChildrenStage,
                build_root=self._run.options.workspace,
            )
