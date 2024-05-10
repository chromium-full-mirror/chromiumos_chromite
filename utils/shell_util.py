# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Shell code utility functions."""

import pathlib
from pathlib import Path
from typing import Any, List, Tuple, Union


# For use by quote.  Match all characters that the shell might treat specially.
# This means a number of things:
#  - Reserved characters.
#  - Characters used in expansions (brace, variable, path, globs, etc...).
#  - Characters that an interactive shell might use (like !).
#  - Whitespace so that one arg turns into multiple.
# See the bash man page as well as the POSIX shell documentation for more info:
#   http://www.gnu.org/software/bash/manual/bashref.html
#   http://pubs.opengroup.org/onlinepubs/9699919799/utilities/V3_chap02.html
_SHELL_QUOTABLE_CHARS = frozenset("[|&;()<> \t\n!{}[]=*?~$\"'\\#^")
# The chars that, when used inside of double quotes, need escaping.
# Order here matters as we need to escape backslashes first.
_SHELL_ESCAPE_CHARS = r"\"`$"


def quote(s: Union[str, bytes, Path]) -> str:
    """Quote |s| in a way that is safe for use in a shell.

    We aim to be safe, but also to produce "nice" output.  That means we don't
    use quotes when we don't need to, and we prefer to use less quotes (like
    putting it all in single quotes) than more (using double quotes and escaping
    a bunch of stuff, or mixing the quotes).

    While python does provide a number of alternatives like:
     - pipes.quote
     - shlex.quote
    They suffer from various problems like:
     - Not widely available in different python versions.
     - Do not produce pretty output in many cases.
     - Are in modules that rarely otherwise get used.

    Note: We don't handle reserved shell words like "for" or "case".  This is
    because those only matter when they're the first element in a command, and
    there is no use case for that.  When we want to run commands, we tend to
    run real programs and not shell ones.

    Args:
        s: The string to quote.

    Returns:
        A safely (possibly quoted) string.
    """
    # If callers pass down bad types, don't blow up.
    if isinstance(s, bytes):
        s = s.decode("utf-8", "backslashreplace")
    elif isinstance(s, pathlib.PurePath):
        return str(s)
    elif not isinstance(s, str):
        return repr(s)

    # See if no quoting is needed so we can return the string as-is.
    for c in s:
        if c in _SHELL_QUOTABLE_CHARS:
            break
    else:
        if not s:
            return "''"
        else:
            return s  # type: ignore

    # See if we can use single quotes first.  Output is nicer.
    if "'" not in s:
        return "'%s'" % s

    # Have to use double quotes.  Escape the few chars that still expand when
    # used inside double quotes.
    for c in _SHELL_ESCAPE_CHARS:
        if c in s:
            s = s.replace(c, r"\%s" % c)
    return '"%s"' % s


def unquote(s: str) -> str:
    """Do the opposite of quote.

    This function assumes that the input is a valid, escaped string. The
    behaviour is undefined on malformed strings.

    Args:
        s: An escaped string.

    Returns:
        The unescaped version of the string.
    """
    if not s:
        return ""

    if s[0] == "'":
        return s[1:-1]

    if s[0] != '"':
        return s

    s = s[1:-1]
    output = ""
    i = 0
    while i < len(s) - 1:
        # Skip the backslash when it makes sense.
        if s[i] == "\\" and s[i + 1] in _SHELL_ESCAPE_CHARS:
            i += 1
        output += s[i]
        i += 1
    return output + s[i] if i < len(s) else output


def cmd_to_str(cmd: Union[List[Any], Tuple[Any]]) -> str:
    """Translate a command list into a space-separated string.

    The resulting string should be suitable for logging messages and for
    pasting into a terminal to run.  Command arguments are surrounded by
    quotes to keep them grouped, even if an argument has spaces in it.

    Examples:
        ['a', 'b'] ==> "'a' 'b'"
        ['a b', 'c'] ==> "'a b' 'c'"
        ['a', 'b\'c'] ==> '\'a\' "b\'c"'
        [u'a', "/'$b"] ==> '\'a\' "/\'$b"'
        [] ==> ''
        See unittest for additional (tested) examples.

    Args:
        cmd: List of command arguments.

    Returns:
        String representing full command.
    """
    # If callers pass down bad types, triage it a bit.
    if isinstance(cmd, (list, tuple)):
        return " ".join(quote(arg) for arg in cmd)
    else:
        raise ValueError(
            "cmd must be list or tuple, not %s: %r" % (type(cmd), repr(cmd))
        )
