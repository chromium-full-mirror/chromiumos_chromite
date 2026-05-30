# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module for printing specially formatted events for cbuildbot reporting."""

import sys

# Import as private to avoid polluting module namespace.
from chromite.lib import buildbot_annotations as _annotations


def _PrintForBuildbot(handle, annotation_class, *args) -> None:
    """Log a line for buildbot.

    This function dumps a line to log recognizable by buildbot if
    EnableBuildbotMarkers has been called. Otherwise, it dumps the same line in
    a human friendly way that buildbot ignores.

    Args:
        handle: The pipe to dump the log to. If None, log to sys.stderr.
        annotation_class: Annotation subclass for the type of buildbot log.
        buildbot_tag: A tag specifying the type of buildbot log.
        *args: The rest of the str arguments to be dumped to the log.
    """
    if handle is None:
        handle = sys.stderr
    # Cast each argument, because we end up getting all sorts of objects
    # from callers.
    str_args = [str(x) for x in args]
    annotation = annotation_class(*str_args)
    line = annotation.human_friendly
    handle.write("\n" + line + "\n")


def PrintBuildbotStepText(text, handle=None) -> None:
    """Prints out stage text to buildbot."""
    _PrintForBuildbot(handle, _annotations.StepText, text)


def PrintBuildbotStepWarnings(handle=None) -> None:
    """Marks a stage as having warnings."""
    PrintBuildbotStepText("[FAILED BUT FORGIVEN]", handle=handle)
    # Warnings not supported by LUCI, so working around until re-added.
    _PrintForBuildbot(handle, _annotations.StepWarnings)
