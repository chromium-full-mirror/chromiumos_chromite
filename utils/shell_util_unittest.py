# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the shell_util module."""

from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pytest

from chromite.utils import shell_util


def _test_data(
    functor: Callable, tests: Tuple[Tuple[str]], check_type: bool = True
) -> None:
    """Process an iterable of test data."""
    for test_output, test_input in tests:
        result = functor(test_input)
        msg = (
            f"Expected shell_util.{functor.__name__} to translate "
            f"{test_input!r} to {test_output!r}, but got {result!r}"
        )
        assert test_output == result, msg

        if check_type:
            # Also make sure the result is a string, otherwise the %r output
            # will include a "u" prefix and that is not good for logging.
            assert isinstance(test_output, str), type(test_output)


def test_quote() -> None:
    """Basic quote tests."""
    # Tuples of (expected output string, input data).
    tests_quote = (
        ("''", ""),
        ("a", "a"),
        ("'a b c'", "a b c"),
        ("'a\tb'", "a\tb"),
        ("'a\nb'", "a\nb"),
        ("'/a$file'", "/a$file"),
        ("'/a#file'", "/a#file"),
        ("""'b"c'""", 'b"c'),
        ("'a@()b'", "a@()b"),
        ("j%k", "j%k"),
        (r'''"s'a\$va\\rs"''', r"s'a$va\rs"),
        (r'''"\\'\\\""''', r'''\'\"'''),
        (r'''"'\\\$"''', r"""'\$"""),
    )

    bytes_quote = (
        # Since we allow passing bytes down, quote them too.
        ("bytes", b"bytes"),
        ("'by tes'", b"by tes"),
        ("bytes", "bytes"),
        ("'by tes'", "by tes"),
    )

    # Expected input output specific to ShellUnquote. This string cannot be
    # produced by ShellQuote but is still a valid bash escaped string.
    tests_unquote = ((r"""\$""", r'''"\\$"'''),)

    def aux(s):
        return shell_util.unquote(shell_util.quote(s))

    # We can only go one way bytes->string.
    _test_data(shell_util.quote, bytes_quote)
    _test_data(aux, [(x, x) for x, _ in bytes_quote], False)

    _test_data(shell_util.quote, tests_quote)
    _test_data(shell_util.unquote, tests_unquote)

    # Test that the operations are reversible.
    _test_data(aux, [(x, x) for x, _ in tests_quote], False)
    _test_data(aux, [(x, x) for _, x in tests_quote], False)


def test_quote_objects() -> None:
    """Test objects passed to quote."""
    assert "/" == shell_util.quote(Path("/"))
    assert "None" == shell_util.quote(None)


@pytest.mark.parametrize(
    "exp, data",
    (
        (r"a b", ["a", "b"]),
        (r"'a b' c", ["a b", "c"]),
        (r'''a "b'c"''', ["a", "b'c"]),
        (r'''a "/'\$b" 'a b c' "xy'z"''', ["a", "/'$b", "a b c", "xy'z"]),
        ("", []),
        ("a b c", [b"a", "b", "c"]),
        ("bad None cmd", ["bad", None, "cmd"]),
    ),
)
def test_cmd_to_str(exp: str, data: List[Optional[str]]) -> None:
    """Verify cmd_to_str behavior."""
    assert shell_util.cmd_to_str(data) == exp
