# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Common python commands used by various build scripts."""

import contextlib
import errno
import io
import logging
import os
from pathlib import Path
import re
from typing import cast, Dict, Generator, Iterable, List, Optional, Tuple, Union

from chromite.lib import osutils


# Simple quote chars we'll use often, to avoid confusion like "'" vs. '"'.
SINGLE_QUOTE = "'"
DOUBLE_QUOTE = '"'
QUOTE_CHARS = [SINGLE_QUOTE, DOUBLE_QUOTE]


@contextlib.contextmanager
def _Open(
    obj: Union[str, "os.PathLike[str]", io.TextIOWrapper],
    mode: str = "r",
    encoding: str = "utf-8",
) -> Generator[io.TextIOWrapper, None, None]:
    """Convenience ctx that accepts a file path or an open file object."""
    if isinstance(obj, (str, os.PathLike)):
        with open(obj, mode=mode, encoding=encoding) as f:
            yield cast(io.TextIOWrapper, f)
    else:
        yield obj


def LoadData(
    data: str, multiline: bool = False, source: str = "<data>"
) -> Dict[str, str]:
    """Turn key=value content into a dict.

    Note: If you're designing a new data store, please use json rather than
    this format.  This func is designed to work with legacy/external files
    where json isn't an option.

    Only UTF-8 content is supported currently.

    Args:
        data: The data to parse.
        multiline: Allow a value enclosed by quotes to span multiple lines.
        source: Helpful string for users to diagnose source of errors.

    Returns:
        a dict of all the key=value pairs found in the file.
    """
    d = {}

    key = None
    in_quotes = None
    for raw_line in data.splitlines(True):
        line = raw_line.split("#")[0]
        if not line.strip():
            continue

        # Continue processing a multiline value.
        if multiline and in_quotes and key:
            if line.rstrip()[-1] == in_quotes:
                # Wrap up the multiline value if the line ends with a quote.
                d[key] += line.rstrip()[:-1]
                in_quotes = None
            else:
                d[key] += line
            continue

        chunks = line.split("=", 1)
        if len(chunks) != 2:
            raise ValueError(
                "Malformed key=value file %r; line %r" % (source, raw_line)
            )
        key = chunks[0].strip()
        val = chunks[1].strip()
        if len(val) >= 2 and val[0] in QUOTE_CHARS and val[0] == val[-1]:
            # Strip matching quotes on the same line.
            val = val[1:-1]
        elif val and multiline and val[0] in QUOTE_CHARS:
            # Unmatched quote here indicates a multiline value. Do not
            # strip the '\n' at the end of the line.
            in_quotes = val[0]
            val = chunks[1].lstrip()[1:]
        d[key] = val

    return d


def LoadFile(
    obj: Union[str, "os.PathLike[str]", io.TextIOWrapper],
    ignore_missing: bool = False,
    multiline: bool = False,
) -> Dict[str, str]:
    """Turn a key=value file into a dict.

    Note: If you're designing a new data store, please use json rather than
    this format.  This func is designed to work with legacy/external files
    where json isn't an option.

    Only UTF-8 content is supported currently.

    Args:
        obj: The file to read.  Can be a path or an open file object.
        ignore_missing: If the file does not exist, return an empty dict.
        multiline: Allow a value enclosed by quotes to span multiple lines.

    Returns:
        a dict of all the key=value pairs found in the file.
    """
    try:
        with _Open(obj) as f:
            if isinstance(obj, (str, os.PathLike)):
                source = str(obj)
            else:
                source = "<already-open file>"
            return LoadData(f.read(), multiline=multiline, source=source)
    except EnvironmentError as e:
        if not (ignore_missing and e.errno == errno.ENOENT):
            raise

    return {}


def UpdateKeyInContents(
    old_lines: Iterable[str], key: str, value: str
) -> List[str]:
    """Update a key in the contents of a key-value store.

    Key-value pairs are represented as:
        key="value"

    If the key-value store does not already contain |key|, it will be appended.

    Args:
        old_lines: The existing contents of the key-value store.
        key: The variable key to update.
        value: The value to write for that key. Quotes will be added
            automatically.

    Returns:
        A new list of lines for an updated key-value store.

    Raises:
        ValueError: If the key already exists in the file with a multiline
            value. This is valid in some key-value stores, but so far it hasn't
            been necessary to make this function compatible with that.
            If you hit this error in production, consider adding that feature!
        ValueError: If the new value is multiline. Again, if you hit this error
            in production, consider adding this feature!
        ValueError: If the new value has a single quote on one side and a double
            quote on the other side, and thus cannot be wrapped.
    """
    if "\n" in value:
        raise ValueError(
            f"Cannot update multi-line value in key-value store: {value}"
        )

    # Pre-construct the new key=value string.
    # Start by figuring out whether to wrap it in single or double quotes.
    quote_char: str
    if not value:  # Avoid IndexError with value[0]
        quote_char = DOUBLE_QUOTE
    elif (
        value[0] in QUOTE_CHARS
        and value[-1] in QUOTE_CHARS
        and value[0] != value[-1]
    ):
        raise ValueError(
            f"Cannot wrap string with mismatched quotes on the ends: {value}"
        )
    elif DOUBLE_QUOTE in (value[0], value[-1]):
        quote_char = SINGLE_QUOTE
    else:
        quote_char = DOUBLE_QUOTE
    new_keyval_line = f"{key}={quote_char}{value}{quote_char}"

    # re_any_key_value should match any key="value" line.
    # The value can be wrapped in either single-quotes or double-quotes.
    # Either the key or the quoted value can be padded by whitespace.
    re_any_key_value = re.compile(
        r"^\s*(?P<key>[A-Za-z-_.]+)\s*="
        r"\s*(?P<quote>['\"])(?P<value>.*)(?P=quote)\s*$",
    )

    def _extract_key_value(line: str) -> Optional[Tuple[str, str]]:
        """If the line looks like key="value", return the key and value.

        Returns None if the line does not have the expected format.
        """
        m = re_any_key_value.match(line)
        if not m:
            return None
        return (m.group("key"), m.group("value"))

    # new_lines is the content to be used to overwrite/create the config file
    # at the end of this function.
    new_lines = []

    # Scan current lines, copy all vars to new_lines, change the line with
    # |key|.
    found = False
    for line in old_lines:
        # Strip newlines from end of line. We already add newlines below.
        line = line.rstrip("\n")
        file_keyval = _extract_key_value(line)
        # Skip any line that doesn't look like a key=value line.
        if file_keyval is None:
            new_lines.append(line)
            continue
        # Skip any keyval line that has a different key.
        file_key, file_value = file_keyval
        if file_key != key:
            new_lines.append(line)
            continue
        # Replace the line with our new line.
        found = True
        logging.info(
            "Updating %s=%s to %s=%s", file_key, file_value, key, value
        )
        new_lines.append(new_keyval_line)
    if not found:
        logging.info("Adding new variable %s=%s", key, value)
        new_lines.append(new_keyval_line)

    # End the file with a single newline, but don't add one if one exists.
    if new_lines[-1]:
        new_lines.append("")

    return new_lines


def UpdateKeyInLocalFile(
    filepath: Union[Path, str], key: str, value: str
) -> bool:
    """Update a key in a local key-value store file with the value passed.

    If `filepath` does not already exist, it will be created.

    Args:
        filepath: Name of file to modify.
        key: The variable key to update.
        value: The value to write for that key. Quotes will be added
            automatically.

    Returns:
        True if changes were made to the file.
    """
    return UpdateKeysInLocalFile(filepath, {key: value})


def UpdateKeysInLocalFile(
    filepath: Union[Path, str],
    keys_values: Dict[str, str],
) -> bool:
    """Update any number of key-value pairs in a local key-value store file.

    Args:
        filepath: The local path to the key-value store file.
        keys_values: Dict of {key: value} for all new values.

    Returns:
        True if any key-value pairs were changed in the file.
    """
    original_lines: List[str] = []
    try:
        original_lines = osutils.ReadText(filepath).splitlines()
    except FileNotFoundError:
        logging.info("Creating new file %s", filepath)

    # Make sure original_lines ends in a blank line. That way, if
    # UpdateKeyInContents will do nothing but append a blank line, we won't
    # report that a change was made.
    if original_lines and original_lines[-1]:
        original_lines.append("")

    # Copy `original_lines`. We'll modify `lines`, and later compare it against
    # the original.
    lines = list(original_lines)
    for key, value in keys_values.items():
        lines = UpdateKeyInContents(lines, key, value)

    if changed := lines != original_lines:
        osutils.WriteFile(filepath, "\n".join(lines))
    return changed
