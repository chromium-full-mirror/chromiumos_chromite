# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Shell code utility functions."""

import logging
import pathlib
from pathlib import Path
import sys
from typing import Any, Iterable, List, Optional, Tuple, Union


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
            s = s.replace(c, rf"\{c}")
    return f'"{s}"'


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
            f"cmd must be list or tuple, not {type(cmd)}: {repr(cmd)!r}"
        )


def get_choice(title: str, options: Iterable[str], group_size: int = 0) -> int:
    """Ask user to choose an option from the list.

    When |group_size| is 0, then all items in |options| will be extracted and
    shown at the same time.  Otherwise, the items will be extracted |group_size|
    at a time, and then shown to the user.  This makes it easier to support
    generators that are slow, extremely large, or people usually want to pick
    from the first few choices.

    Args:
        title: The text to display before listing options.
        options: Iterable which provides options to display.
        group_size: How many options to show before asking the user to choose.

    Returns:
        An integer of the index in |options| the user picked.
    """

    def prompt_for_choice(max_choice: int, more: bool) -> Optional[int]:
        prompt = f"Please choose an option [0-{max_choice:d}]"
        if more:
            prompt += " (Enter for more options)"
        prompt += ": "

        while True:
            choice = input(prompt)
            if more and not choice.strip():
                return None
            try:
                choice_val = int(choice)
            except ValueError:
                print("Input is not an integer")
                continue
            if choice_val < 0 or choice_val > max_choice:
                print(f"Choice {choice_val:d} out of range (0-{max_choice:d})")
                continue
            return choice_val

    print(title)
    max_choice = 0
    for i, opt in enumerate(options):
        if i and group_size and not i % group_size:
            choice = prompt_for_choice(i - 1, True)
            if choice is not None:
                return choice
        print(f"  [{i:d}]: {opt}")
        max_choice = i

    return prompt_for_choice(max_choice, False)


def boolean_prompt(
    prompt: str = "Do you want to continue?",
    default: bool = True,
    true_value: str = "yes",
    false_value: str = "no",
    prolog: Optional[str] = None,
) -> bool:
    """Helper function for processing boolean choice prompts.

    Args:
        prompt: The question to present to the user.
        default: Boolean to return if the user just presses enter.
        true_value: The text to display that represents a True returned.
        false_value: The text to display that represents a False returned.
        prolog: The text to display before prompt.

    Returns:
        True or False.
    """
    true_value, false_value = true_value.lower(), false_value.lower()
    true_text, false_text = true_value, false_value
    if true_value == false_value:
        raise ValueError(
            f"true_value and false_value must differ: got {true_value!r}"
        )

    if default:
        true_text = true_text[0].upper() + true_text[1:]
    else:
        false_text = false_text[0].upper() + false_text[1:]

    prompt = f"\n{prompt} ({true_text}/{false_text})? "

    if prolog:
        prompt = f"\n{prolog}\n{prompt}"

    while True:
        try:
            response = input(prompt).lower()
        except EOFError:
            # If the user hits CTRL+D, or stdin is disabled, use the default.
            print()
            response = None
        except KeyboardInterrupt:
            # If the user hits CTRL+C, just exit the process.
            print()
            logging.notice("CTRL+C detected; exiting")
            sys.exit(1)

        if not response:
            return default
        if true_value.startswith(response):
            if not false_value.startswith(response):
                return True
            # common prefix between the two...
        elif false_value.startswith(response):
            return False


def boolean_value(sval: str, default: bool, msg: Optional[str] = None) -> bool:
    """See if the string value is a value users typically consider as boolean

    Often times people set shell variables to different values to mean "true"
    or "false".  For example, they can do:
        export FOO=yes
        export BLAH=1
        export MOO=true
    Handle all that user ugliness here.

    If the user picks an invalid value, you can use |msg| to display a non-fatal
    warning rather than raising an exception.

    Args:
        sval: The string value we got from the user.
        default: If we can't figure out if the value is true or false, use this.
        msg: If |sval| is an unknown value, use |msg| to warn the user that we
           could not decode the input.  Otherwise, raise ValueError().

    Returns:
        The interpreted boolean value of |sval|.

    Raises:
        ValueError() if |sval| is an unknown value and |msg| is not set.
    """
    if sval is None:
        return default

    if isinstance(sval, str):
        s = sval.lower()
        if s in ("yes", "y", "1", "true"):
            return True
        elif s in ("no", "n", "0", "false"):
            return False

    if msg is not None:
        logging.warning("%s: %r", msg, sval)
        return default
    else:
        raise ValueError(f"Could not decode as a boolean value: {sval!r}")
