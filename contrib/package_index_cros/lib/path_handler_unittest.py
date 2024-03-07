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
        ("just/a/path", "", "just/a/path/fixed", None),
        ("-Ifoobar", "-I", "foobar/fixed", None),
        (":/usr/lib", ":", "/usr/lib/fixed", None),
        (":/trailing/slash/", ":", "/trailing/slash//fixed", None),
        ("--two-dashes=/usr/lib", "--two-dashes=", "/usr/lib/fixed", None),
        ("-one-dash=/usr/lib", "-one-dash=", "/usr/lib/fixed", None),
        ("no-dashes=/usr/lib", "no-dashes=", "/usr/lib/fixed", None),
        ("wEiRd_-...=/usr/lib", "wEiRd_-...=", "/usr/lib/fixed", None),
        ("--chain=link=/usr/lib", "--chain=link=", "/usr/lib/fixed", None),
        ("Mhello.proto=/usr/lib", "Mhello.proto=", "/usr/lib/fixed", None),
        ('--arg="quoted/path"', "--arg=", "quoted/path/fixed", None),
        ('--arg=\\"escaped/path\\"', "--arg=", "escaped/path/fixed", None),
        ("//gn_target", "//gn_target", "", None),
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
