# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parser for Upstart job .conf files."""

import dataclasses
import re
from typing import Iterator, List, Optional


class Error(Exception):
    """Base error class for the module."""


class UnknownTokenError(Error):
    """Unknown config token encountered."""


class JobSyntaxError(Error):
    """Unable to parse config."""


@dataclasses.dataclass()
class Job:
    """An Upstart job."""

    author: Optional[str] = None
    description: Optional[str] = None
    oom: Optional[str] = None
    main: Optional[str] = None
    prestart: Optional[str] = None
    poststart: Optional[str] = None
    prestop: Optional[str] = None
    poststop: Optional[str] = None

    def __eq__(self, other: "Job") -> bool:
        return (
            isinstance(other, Job)
            and self.author == other.author
            and self.description == other.description
            and self.oom == other.oom
            and self.main == other.main
            and self.prestart == other.prestart
            and self.poststart == other.poststart
            and self.prestop == other.prestop
            and self.poststop == other.poststop
        )

    def __ne__(self, other: "Job") -> bool:
        return not self == other


def parse(contents: str) -> Job:
    """Parse the contents of an Upstart job .conf file.

    Args:
        contents: The file contents of a job .conf file.

    Returns:
        The parsed job settings.
    """
    ret = Job()

    def _iter_lines(lines: List[str]) -> Iterator[str]:
        r"""Yield partially cooked lines.

        This will:
        * Delete line-level comments.
        * Skip blank lines.
        * Merge lines wrapped with \ at the end.
        """
        ilines = iter(lines)
        for line in ilines:
            sline = line.strip()
            if not sline or sline.startswith("#"):
                continue

            while line.endswith("\\"):
                try:
                    line = line[:-1] + next(ilines)
                except StopIteration:
                    raise JobSyntaxError("Premature EOL reached")

            yield line

    def _parse_exec(line: str) -> str:
        """Parse 'exec' lines."""
        m = re.match(r"^\s*exec\s+(.*)$", line)
        if not m:
            raise JobSyntaxError(f"Invalid exec line: {line}")
        return m.group(1)

    def _parse_script(ilines: Iterator[str]) -> str:
        """Parse 'script' stanzas."""
        stanza = ""
        for line in ilines:
            if line.strip() == "end script":
                return stanza
            stanza += line + "\n"
        raise JobSyntaxError("Missing 'end script'")

    ilines = _iter_lines(contents.splitlines())
    for line in ilines:
        tokens = line.split()
        if tokens[0] == "author":
            m = re.match(r'^\s*author\s+"(.*)"\s*$', line)
            if not m:
                raise JobSyntaxError(f"Invalid author line: {line}")
            ret.author = m.group(1)
        elif tokens[0] == "description":
            m = re.match(r'^\s*description\s+"(.*)"\s*$', line)
            if not m:
                raise JobSyntaxError(f"Invalid description line: {line}")
            ret.description = m.group(1)
        elif tokens[0] == "oom":
            if len(tokens) == 2 and tokens[1] == "never":
                ret.oom = tokens[1]
            elif len(tokens) < 3 or tokens[1] != "score":
                raise JobSyntaxError(f"Invalid oom line: {line}")
            else:
                ret.oom = tokens[2]
        elif tokens[0] == "exec":
            if ret.main is not None:
                raise JobSyntaxError(
                    "More than one main exec/script stanza found"
                )
            ret.main = _parse_exec(line)
        elif tokens[0] == "script":
            if ret.main is not None:
                raise JobSyntaxError(
                    "More than one main exec/script stanza found"
                )
            ret.main = _parse_script(ilines)
        elif tokens[0] in {"pre-start", "post-start", "pre-stop", "post-stop"}:
            token = tokens[0]
            next_token = tokens[1] if len(tokens) > 1 else None
            if next_token not in ("exec", "script"):
                raise JobSyntaxError(
                    f"Expected 'exec' or 'script' after '{token}'", line
                )

            if next_token == "exec":
                m = re.match(r"^\s*(?:pre|post)-(?:start|stop)\s*(.*)$", line)
                value = _parse_exec(m.group(1))
            else:
                value = _parse_script(ilines)
            attr = token.replace("-", "")
            if getattr(ret, attr) is not None:
                raise JobSyntaxError(
                    f"More than one '{token}' stanza found", line
                )
            setattr(ret, attr, value)
        elif tokens[0] in (
            "cgroup",
            "chdir",
            "chroot",
            "console",
            "debug",
            "emits",
            "env",
            "expect",
            "export",
            "import",
            "instance",
            "kill",
            "limit",
            "manual",
            "nice",
            "normal",
            "reload",
            "respawn",
            "start",
            "stop",
            "setgid",
            "setuid",
            "task",
            "tmpfiles",
            "umask",
            "usage",
            "version",
        ):
            # Ignore for now.
            pass
        else:
            raise UnknownTokenError(f"Unknown token '{tokens[0]}'", line)

    return ret
