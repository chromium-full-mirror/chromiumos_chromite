# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parser for Upstart job .conf files."""

import dataclasses
import re
from typing import Dict, Iterator, List, Optional, Set

from chromite.utils import shell_util


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
    env: Dict[str, str] = dataclasses.field(default_factory=dict)
    exports: Set[str] = dataclasses.field(default_factory=set)
    imports: Set[str] = dataclasses.field(default_factory=set)
    oom: Optional[str] = None
    main: Optional[str] = None
    prestart: Optional[str] = None
    poststart: Optional[str] = None
    prestop: Optional[str] = None
    poststop: Optional[str] = None
    start: Optional[str] = None
    stop: Optional[str] = None

    def __eq__(self, other: "Job") -> bool:
        return (
            isinstance(other, Job)
            and self.author == other.author
            and self.description == other.description
            and self.env == other.env
            and self.exports == other.exports
            and self.imports == other.imports
            and self.oom == other.oom
            and self.main == other.main
            and self.prestart == other.prestart
            and self.poststart == other.poststart
            and self.prestop == other.prestop
            and self.poststop == other.poststop
            and self.start == other.start
            and self.stop == other.stop
        )

    def __ne__(self, other: "Job") -> bool:
        return not self == other


def _parse_exec(line: str) -> str:
    """Parse 'exec' lines."""
    m = re.match(r"^\s*exec\s+(.*)$", line)
    if not m:
        raise JobSyntaxError(f"Invalid exec line: {line}")
    return m.group(1)


def _parse_env(env: Dict[str, str], line: str) -> None:
    """Parse 'env' lines."""
    # Can take the form of:
    #   env FOO
    #   env FOO=
    #   env FOO=bar
    #   env FOO='bar'
    #   env FOO="bar"
    m = re.match(r"^\s*env\s+(?P<key>[^\s=]+)(=(?P<val>.*))?$", line)
    if not m:
        raise JobSyntaxError(f"Invalid env line: {line}")
    key = m.groupdict()["key"]
    val = m.groupdict()["val"]
    if val is None:
        val = ""
    else:
        val = shell_util.unquote(val)
    if key in env:
        raise JobSyntaxError(f"Duplicate env var declared: {line}")
    env[key] = val


def _parse_script(ilines: Iterator[str]) -> str:
    """Parse 'script' stanzas."""
    stanza = ""
    for line in ilines:
        if line.strip() == "end script":
            return stanza
        stanza += line + "\n"
    raise JobSyntaxError("Missing 'end script'")


def _parse_start_stop(line: str, ilines: Iterator[str]) -> str:
    """Parse 'start' and 'stop' stanzas."""
    tokens = line.split()
    if (
        len(tokens) < 3
        or tokens[0] not in {"start", "stop"}
        or tokens[1] != "on"
    ):
        raise JobSyntaxError(f"Expected 'on' after '{tokens[0]}'", line)

    m = re.match(r"^\s*(start|stop)\s+on\s+(.*)$", line)

    # This only checks () balance and consumes whole lines for it.
    def _parse(buf: str) -> str:
        i = 0
        # Number of open (unbalanced) parens.
        p = 0
        buf = buf.split("#", 1)[0].strip()
        while True:
            if i == len(buf):
                if p == 0:
                    break
                try:
                    buf += " " + next(ilines).split("#", 1)[0].strip()
                except StopIteration:
                    raise JobSyntaxError("Premature EOL reached")

            c = buf[i]
            if c == "(":
                p += 1
            elif c == ")":
                p -= 1
                if p < 0:
                    raise JobSyntaxError(
                        f"Unbalanced paren in '{tokens[0]}'", buf
                    )
            i += 1

        return buf

    return _parse(m.group(2))


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
        elif tokens[0] == "env":
            _parse_env(ret.env, line)
        elif tokens[0] == "exec":
            if ret.main is not None:
                raise JobSyntaxError(
                    "More than one main exec/script stanza found"
                )
            ret.main = _parse_exec(line)
        elif tokens[0] == "export":
            if len(tokens) != 2:
                raise JobSyntaxError(f"Invalid export line: {line}")
            ret.exports.add(tokens[1])
        elif tokens[0] == "import":
            if len(tokens) != 2:
                raise JobSyntaxError(f"Invalid import line: {line}")
            ret.imports.add(tokens[1])
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
        elif tokens[0] in {"start", "stop"}:
            setattr(ret, tokens[0], _parse_start_stop(line, ilines))
        elif tokens[0] in (
            "cgroup",
            "chdir",
            "chroot",
            "console",
            "debug",
            "emits",
            "expect",
            "instance",
            "kill",
            "limit",
            "manual",
            "nice",
            "normal",
            "reload",
            "respawn",
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
