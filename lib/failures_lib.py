# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Classes of failure types."""

import collections
from typing import List

from chromite.lib import cros_build_lib


class StepFailure(Exception):
    """StepFailure exceptions indicate that a cbuildbot step failed.

    Exceptions that derive from StepFailure should meet the following
    criteria:
        1) The failure indicates that a cbuildbot step failed.
        2) The necessary information to debug the problem has already been
            printed in the logs for the stage that failed.
        3) __str__() should be brief enough to include in a Commit Queue
            failure message.
    """


# A namedtuple to hold information of an exception.
ExceptInfo = collections.namedtuple("ExceptInfo", ["type", "str", "traceback"])


def CreateExceptInfo(exception, tb):
    """Creates a list of ExceptInfo objects from |exception| and |tb|.

    Creates an ExceptInfo object from |exception| and |tb|. If
    |exception| is a CompoundFailure with non-empty list of exc_infos,
    simply returns exception.exc_infos. Note that we do not preserve type
    of |exception| in this case.

    Args:
        exception: The exception.
        tb: The textual traceback.

    Returns:
        A list of ExceptInfo objects.
    """
    if isinstance(exception, CompoundFailure) and exception.exc_infos:
        return exception.exc_infos

    return [ExceptInfo(exception.__class__, str(exception), tb)]


class CompoundFailure(StepFailure):
    """An exception that contains a list of ExceptInfo objects."""

    def __init__(self, message="", exc_infos=None) -> None:
        """Initializes an CompoundFailure instance.

        Args:
            message: A string describing the failure.
            exc_infos: A list of ExceptInfo objects.
        """
        self.exc_infos = exc_infos if exc_infos else []
        if not message:
            # By default, print all stored ExceptInfo objects. This is the
            # preferred behavior because we'd always have the full
            # tracebacks to debug the failure.
            message = "\n".join(
                f"{ex.type}: {ex.str}\n{ex.traceback}" for ex in self.exc_infos
            )
        self.msg = message

        super().__init__(message)


class BuildScriptFailure(StepFailure):
    """This exception is thrown when a build command failed.

    It is intended to provide a shorter summary of what command failed,
    for usage in failure messages from the Commit Queue, so as to ensure
    that developers aren't spammed with giant error messages when common
    commands (e.g. cros build-packages) fail.
    """

    def __init__(self, exception, shortname) -> None:
        """Construct a BuildScriptFailure object.

        Args:
            exception: A RunCommandError object.
            shortname: Short name for the command we're running.
        """
        StepFailure.__init__(self)
        assert isinstance(exception, cros_build_lib.RunCommandError)
        self.exception = exception
        self.shortname = shortname
        self.args = (exception, shortname)

    def __str__(self) -> str:
        """Summarize a build command failure briefly."""
        result = self.exception.result
        if result.returncode:
            return "%s failed (code=%s)" % (self.shortname, result.returncode)
        else:
            return self.exception.msg


# TODO(nxia): Everytime the class name is changed, add the new class name to
# PACKAGE_BUILD_FAILURE_TYPES
class PackageBuildFailure(BuildScriptFailure):
    """This exception is thrown when packages fail to build."""

    def __init__(
        self,
        exception: cros_build_lib.RunCommandError,
        shortname: str,
        failed_packages: List[str],
    ) -> None:
        """Construct a PackageBuildFailure object.

        Args:
            exception: The underlying exception.
            shortname: Short name for the command we're running.
            failed_packages: List of packages that failed to build.
        """
        BuildScriptFailure.__init__(self, exception, shortname)
        self.failed_packages = set(failed_packages)
        self.args = (exception, shortname, failed_packages)

    def __str__(self) -> str:
        return "Packages failed in %s: %s" % (
            self.shortname,
            " ".join(sorted(self.failed_packages)),
        )
