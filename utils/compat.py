# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Backports of Python features.

This module serves as a clearing house location for backporting stdlib
functionality to the minimum Python version supported by chromite.

Please use the _available_in decorator on all functions, which will cause
the function to start generating warnings once Chromite's minimum Python
version advances.
"""

import functools
from pathlib import Path
from typing import Any, Callable, Tuple
import warnings

import chromite


def _available_in(
    python_version: Tuple[int, int], stdlib_equivalent: str
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Annotate a function as available in a certain Python version.

    Args:
        python_version: The first version the functionality is available.
        stdlib_equivalent: The name of the standard library equivalent.

    Returns:
        A function to wrap your function.
    """

    def _decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(f)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            if python_version <= chromite.MIN_PYTHON_VERSION:
                warnings.warn(
                    f"{f.__name__} is now available in the Python standard "
                    f"library.  Please use {stdlib_equivalent} instead.",
                    DeprecationWarning,
                )
            return f(*args, **kwargs)

        return _wrapper

    return _decorator


@_available_in((3, 9), "pathlib.Path.is_relative_to")
def path_is_relative_to(inner: Path, outer: Path) -> bool:
    """Backport of Path.is_relative_to() (available in Python 3.9+).

    Args:
        inner: The inner path.
        outer: The outer path.

    Returns:
        True if inner is inside the parents of outer, false otherwise.
    """
    return outer == inner or outer in inner.parents
