# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utility classes and functions."""

import getpass
import platform
import re
from typing import Optional, Pattern, Sequence, Tuple


ALLOWED_HOSTNAME_SUFFIX = (".google.com", ".googler.com", ".googlers.com")


def is_google_host():
    """Checks if the code is running on google host."""

    hostname = platform.node()
    return hostname.endswith(ALLOWED_HOSTNAME_SUFFIX)


class Anonymizer:
    """Redact the personally indentifiable information."""

    def __init__(
        self, replacements: Optional[Sequence[Tuple[Pattern[str], str]]] = None
    ):
        self._replacements = replacements or []
        self._replacements.append((re.escape(getpass.getuser()), "<user>"))

    def apply(self, data: str) -> str:
        """Applies the replacement rules to data text."""
        if not data:
            return data

        for repl_from, repl_to in self._replacements:
            data, _ = re.subn(repl_from, repl_to, data)

        return data
