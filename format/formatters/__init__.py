# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provide a namespace for our helpers."""

import importlib


__all__ = [
    "cpp",
    "gn",
    "go",
    "json",
    "mojom",
    "portage_layout_conf",
    "proto",
    "python",
    "repo_manifest",
    "rust",
    "star",
    "textproto",
    "whitespace",
    "xml",
]


def __getattr__(name):
    """Lazy load modules."""
    if name in __all__:
        return importlib.import_module("." + name, __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


class Error(Exception):
    """General formatting error."""


class ParseError(Error):
    """Parsing error in the format input."""
