# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for path_handler.py."""

from typing import Optional

import pytest

from chromite.contrib.package_index_cros.lib import path_handler


@pytest.mark.parametrize(
    (
        "input_arg",
        "expected_prefix",
        "expected_fixed_path",
        "expected_exception",
    ),
    (
        ('--arg=\\"escaped/path\\"', "--arg=", "escaped/path/fixed", None),
        ("just/a/path", "", "just/a/path/fixed", None),
        ("-Ifoobar", "-I", "foobar/fixed", None),
        ("//gn_target:subtarget", "//gn_target:subtarget", "", None),
        ("-Q/usr/lib", "", "", ValueError),
        ("--arg=$HOME/path", "--arg=$HOME/path", "", None),
        ("--arg=not-a-path", "--arg=not-a-path", "", None),
    ),
)
def test_fix_path_in_argument(
    input_arg: str,
    expected_prefix: str,
    expected_fixed_path: str,
    expected_exception: Optional[Exception],
) -> None:
    """Test cases for path_handler.fix_path_in_argument()."""
    fixer_callback = lambda path: f"{path}/fixed"
    if expected_exception:
        with pytest.raises(expected_exception):
            path_handler.fix_path_in_argument(input_arg, fixer_callback)
    else:
        prefix, fixed_path = path_handler.fix_path_in_argument(
            input_arg, fixer_callback
        )
        assert prefix == expected_prefix
        assert fixed_path == expected_fixed_path


@pytest.mark.parametrize(
    ("test_string", "expect_match", "expected_prefix", "expected_path"),
    (
        ("just/a/path", True, "", "just/a/path"),
        (":/usr/lib", True, ":", "/usr/lib"),
        ("--two-dashes=/usr/lib", True, "--two-dashes=", "/usr/lib"),
        ("-one-dash=/usr/lib", True, "-one-dash=", "/usr/lib"),
        ("no-dashes=/usr/lib", True, "no-dashes=", "/usr/lib"),
        ("wEiRd_-...=/usr/lib", True, "wEiRd_-...=", "/usr/lib"),
        ("--chain=link=/usr/lib", True, "--chain=link=", "/usr/lib"),
        ("--chain=-L/usr/lib", True, "--chain=-L", "/usr/lib"),
        ("Mhello.proto=/usr/lib", True, "Mhello.proto=", "/usr/lib"),
        ('--arg="quoted/path"', True, "--arg=", "quoted/path"),
        ('--arg=\\"escaped/path\\"', True, "--arg=", "escaped/path"),
        ("--arg=$HOME/path", True, "--arg=", "$HOME/path"),
        ("--arg=${HOME}/path", True, "--arg=", "${HOME}/path"),
        ("--arg=/usr/{{lib}}/home", True, "--arg=", "/usr/{{lib}}/home"),
        ("--arg=usr/.././lib", True, "--arg=", "usr/.././lib"),
        ("--arg=not-a-path", False, None, None),
        ("some random string", False, None, None),
        ("-Q/usr/lib", False, None, None),
    ),
)
def test_argument_regex(
    test_string: str,
    expect_match: bool,
    expected_prefix: Optional[str],
    expected_path: Optional[str],
) -> None:
    """Test cases for _get_argument_regex()."""
    # pylint: disable-next=protected-access
    argument_regex = path_handler._get_argument_regex()
    match = argument_regex.match(test_string)
    assert bool(match) == expect_match
    if expect_match:
        assert match.group("prefix") == expected_prefix
        assert match.group("path") == expected_path


def test_gn_target_regex() -> None:
    """Test cases for _get_gn_target_regex()."""
    # pylint: disable-next=protected-access
    gn_target_regex = path_handler._get_gn_target_regex()
    for positive_test in ("//gn_target", "//gn_target:subtarget"):
        assert gn_target_regex.match(positive_test)
    for negative_test in ("hello", "//with spaces", "//gn_target/path"):
        assert not gn_target_regex.match(negative_test)
