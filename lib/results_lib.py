# Copyright 2011 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Classes for collecting results of our BuildStages as they run."""

import collections
import datetime
import math

from chromite.lib import cros_build_lib
from chromite.lib import failures_lib


class RecordedTraceback:
    """This class represents a traceback recorded in the list of results."""

    def __init__(
        self, failed_stage, failed_prefix, exception, traceback
    ) -> None:
        """Construct a RecordedTraceback object.

        Args:
            failed_stage: The stage that failed during the build.
                E.g., HWTest [bvt]
            failed_prefix: The prefix of the stage that failed. E.g., HWTest
            exception: The raw exception object.
            traceback: The full stack trace for the failure, as a string.
        """
        self.failed_stage = failed_stage
        self.failed_prefix = failed_prefix
        self.exception = exception
        self.traceback = traceback


_result_fields = ["name", "result", "description", "prefix", "board", "time"]
Result = collections.namedtuple("Result", _result_fields)


class _Results:
    """Static class that collects the results of our BuildStages as they run."""

    SUCCESS = "Stage was successful"
    FORGIVEN = "Stage failed but was optional"
    SKIPPED = "Stage was skipped"
    NON_FAILURE_TYPES = (SUCCESS, FORGIVEN, SKIPPED)

    SPLIT_TOKEN = r"\_O_/"

    def __init__(self) -> None:
        # List of results for all stages that's built up as we run. Members are
        # of the form:
        #   ('name', SUCCESS | FORGIVEN | Exception, None | description)
        self._results_log = []

        # A list of instances of failure_message_lib.StageFailureMessage to
        # present the exceptions threw by failed stages.
        self._failure_message_results = []

        # Stages run in a previous run and restored. Stored as a dictionary of
        # names to previous records.
        self._previous = {}

        self.start_time = datetime.datetime.now()

    def Clear(self) -> None:
        """Clear existing stage results."""
        self.__init__()

    def _RecordStageFailureMessage(
        self, name, exception, prefix=None, build_stage_id=None
    ) -> None:
        self._failure_message_results.append(
            failures_lib.GetStageFailureMessageFromException(
                name, build_stage_id, exception, stage_prefix_name=prefix
            )
        )

    def Record(
        self,
        name,
        result,
        description=None,
        prefix=None,
        board="",
        time=0,
        build_stage_id=None,
    ) -> None:
        """Store off an additional stage result.

        Args:
            name: The name of the stage (e.g. HWTest [bvt])
            result:
                Result should be one of:
                    Results.SUCCESS if the stage was successful.
                    Results.SKIPPED if the stage was skipped.
                    Results.FORGIVEN if the stage had warnings.
                    Otherwise, it should be the exception stage errored with.
            description: The textual backtrace of the exception, or None
            prefix: The prefix of the stage (e.g. HWTest). Defaults to
                the value of name.
            board: The board associated with the stage, if any. Defaults to ''.
            time: How long the result took to complete.
            build_stage_id: The id of the failed build stage to record, default
                None.
        """
        if prefix is None:
            prefix = name

        # Convert exception to stage_failure_message and record it.
        if isinstance(result, BaseException):
            self._RecordStageFailureMessage(
                name, result, prefix=prefix, build_stage_id=build_stage_id
            )

        result = Result(name, result, description, prefix, board, time)
        self._results_log.append(result)

    def GetStageFailureMessage(self):
        return self._failure_message_results

    def Get(self):
        """Fetch stage results.

        Returns:
            A list with one entry per stage run with a result.
        """
        return self._results_log

    def GetTracebacks(self):
        """Get a list of the exceptions that failed the build.

        Returns:
            A list of RecordedTraceback objects.
        """
        tracebacks = []
        for entry in self._results_log:
            # If entry.result is not in NON_FAILURE_TYPES, then the stage
            # failed, and entry.result is the exception object and
            # entry.description is a string containing the full traceback.
            if entry.result not in self.NON_FAILURE_TYPES:
                traceback = RecordedTraceback(
                    entry.name, entry.prefix, entry.result, entry.description
                )
                tracebacks.append(traceback)
        return tracebacks

    def Report(self, out, current_version=None) -> None:
        """Generate a user-friendly text display of the result data.

        Args:
            out: Output stream to write to (e.g. sys.stdout).
            current_version: Chrome OS version associated with this report.
        """
        results = self._results_log

        line = "*" * 60 + "\n"
        edge = "*" * 2

        if current_version:
            out.write(line)
            out.write(edge + " RELEASE VERSION: " + current_version + "\n")

        out.write(line)
        out.write(edge + " Stage Results\n")

        for entry in results:
            name, result, run_time = (entry.name, entry.result, entry.time)
            timestr = datetime.timedelta(seconds=math.ceil(run_time))

            # Don't print data on skipped stages.
            if result == self.SKIPPED:
                continue

            out.write(line)
            details = ""
            if result == self.SUCCESS:
                status = "PASS"
            elif result == self.FORGIVEN:
                status = "FAILED BUT FORGIVEN"
            else:
                status = "FAIL"
                if isinstance(result, cros_build_lib.RunCommandError):
                    # If there was a run error, give just the command that
                    # failed, not its full argument list, since those are
                    # usually too long.
                    details = " in %s" % result.cmd[0]
                elif isinstance(result, failures_lib.BuildScriptFailure):
                    # BuildScriptFailure errors publish a 'short' name of the
                    # command that failed.
                    details = " in %s" % result.shortname
                else:
                    # There was a normal error. Give the type of exception.
                    details = " with %s" % type(result).__name__

            out.write(
                "%s %s %s (%s)%s\n" % (edge, status, name, timestr, details)
            )

        out.write(line)

        for x in self.GetTracebacks():
            if x.failed_stage and x.traceback:
                out.write("\nFailed in stage %s:\n\n" % x.failed_stage)
                out.write(x.traceback)
                out.write("\n")


Results = _Results()
