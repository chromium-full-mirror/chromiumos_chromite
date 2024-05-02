# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Provides utility classes and functions."""

import getpass
import re
from typing import Optional, Pattern, Sequence, Tuple


class Anonymizer:
    """Redact the personally identifiable information."""

    def __init__(
        self, replacements: Optional[Sequence[Tuple[Pattern[str], str]]] = None
    ) -> None:
        self._replacements = list(replacements or [])
        if getpass.getuser() != "root":
            # Substituting the root user doesn't actually anonymize anything.
            self._replacements.append(
                (re.compile(re.escape(getpass.getuser())), "<user>")
            )

    def __call__(self, *args, **kwargs):
        return self.apply(*args, **kwargs)

    def apply(self, data: str) -> str:
        """Applies the replacement rules to data text."""
        if not data:
            return data

        for repl_from, repl_to in self._replacements:
            data = re.sub(repl_from, repl_to, data)

        return data
