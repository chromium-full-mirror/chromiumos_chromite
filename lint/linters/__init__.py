# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provide a namespace for our helpers."""

import importlib


__all__ = [
    "gnlint",
    "make_defaults",
    "owners",
    "portage_layout_conf",
    "shell",
    "upstart",
    "whitespace",
]


def __getattr__(name):
    """Lazy load modules."""
    if name in __all__:
        return importlib.import_module("." + name, __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
