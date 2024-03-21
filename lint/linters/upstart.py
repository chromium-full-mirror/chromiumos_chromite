# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Run upstart-specific lint checks on the specified .conf files."""

import functools
import json
import logging
import os
from pathlib import Path
import re
from typing import Dict, Generator, List

from chromite.lint import linters
from chromite.utils.parser import upstart


_DOC_RESOURCE_URL = (
    "https://dev.chromium.org/chromium-os/chromiumos-design-docs/"
    "boot-design/#runtime-resource-limits"
)
_AUDITED_SHELL_COMMAND_REGEX = re.compile(
    # Match comment lines so they can be excluded.
    r"(?P<comment>^\s*#.*$)|"
    # Match common command delimiters.
    r"(?:^\s*|;|&&|[|][|]|(?P<prefix>(?:[$][(]|`)+)\s*)"
    # Match command name.
    r"\b(?P<command>chown|chgrp|chmod|mkdir|ln|rm|mv|cp|touch)\s+"
    # Match command args across line splits.
    r"(?P<args>(?:\\\n|[^\n;])*)",
    re.MULTILINE,
)
_SHELL_TOKEN_SPLIT_REGEX = re.compile(r"(?:\\\n|\s)+", re.MULTILINE)
_IGNORE_LINT_REGEX = re.compile(r"#\s+croslint:\s+disable")


# TODO(python3.9): Change to functools.cache.
@functools.lru_cache(maxsize=None)
def GetIgnoreLookup() -> Dict[str, List[str]]:
    """Returns the lookup table of upstart config lines to ignore.

    On first invocation this loads the list from upstart_exceptions.json.
    Otherwise the cached copy is used.

    This is intended to be removed once the call sites are either migrated to
    tmpfiles.d or have '# croslint: disable' added.
    """
    FILE = Path(__file__).resolve()
    exceptions_path = FILE.parent / "upstart_exceptions.json"
    with exceptions_path.open("rb") as fp:
        return json.load(fp)


def ExtractCommands(job: upstart.Job) -> Generator[List[str], None, None]:
    """Finds and normalizes audited commands."""
    text = "\n"
    for stanza in ("main", "pre-start", "post-start", "pre-stop", "post-stop"):
        data = getattr(job, stanza.replace("-", ""))
        if data is not None:
            text += data + "\n"

    for match in _AUDITED_SHELL_COMMAND_REGEX.finditer(text):
        # Skip comments.
        if match.group("comment"):
            continue

        cmd_prefix = match.group("prefix")
        cmd_name = match.group("command")
        cmd_args = match.group("args")

        # Skip if 'croslint: disable' is set.
        if _IGNORE_LINT_REGEX.search(cmd_args):
            continue

        if cmd_prefix:
            cmd = [_SHELL_TOKEN_SPLIT_REGEX.sub(cmd_prefix, " ") + cmd_name]
        else:
            cmd = [cmd_name]
        cmd.extend(x for x in _SHELL_TOKEN_SPLIT_REGEX.split(cmd_args) if x)
        yield cmd


def CheckForRequiredLines(job: upstart.Job, full_path: Path) -> bool:
    """Check the upstart config for required clause."""
    ret = True

    tokens_to_find = {
        "author",
        "description",
        "oom",
    }

    for token in tokens_to_find:
        if getattr(job, token) is None:
            ret = False
            logging.error(
                '%s: Missing "%s" clause\nPlease see:\n%s',
                full_path,
                token,
                _DOC_RESOURCE_URL,
            )

    if job.oom == "-1000":
        ret = False
        logging.error('Use "oom score never" instead of "oom score -1000".')

    return ret


def Data(
    data: str,
    path: Path,
    relaxed: bool,
) -> bool:
    """Check an upstart conf file for linter errors."""
    try:
        job = upstart.parse(data)
    except upstart.Error as e:
        logging.error("%s: unable to parse: %s", path, e)
        return False

    ret = True
    if not CheckForRequiredLines(job, path) and not relaxed:
        ret = False

    label = os.path.basename(path)
    ignore_set = set(GetIgnoreLookup().get(label, [])) if relaxed else ()

    found = []
    for cmd in ExtractCommands(job):
        norm_cmd = " ".join(cmd)
        if norm_cmd not in ignore_set:
            found.append(norm_cmd)

    if found:
        logging.error('Init script "%s" has unsafe commands:', path)
        for cmd in found:
            logging.error("    %s", cmd)
        logging.error(
            "Please use a tmpfiles.d config for the commands or have "
            'them reviewed by security and add "# croslint: disable:". '
            "A security consultation bug can be filed through:\n"
            "https://b.corp.google.com/issues/new?component=1030291"
        )
        ret = False

    if not linters.whitespace.Data(data, path) and not relaxed:
        ret = False

    return ret
