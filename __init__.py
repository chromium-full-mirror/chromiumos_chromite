# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite base module.

Keep this to a minimum as every chromite import will automatically load it.
"""

import functools
import logging
import sys
from typing import Any, Dict, Optional, Tuple


MIN_PYTHON_VERSION = (3, 8)
assert sys.version_info >= MIN_PYTHON_VERSION, (
    "Chromite requires Python %s.%s+" % MIN_PYTHON_VERSION
)

# Set a custom logging class inside this module that provides the NOTICE level.
NOTICE = 25


class ChromiteLogger(logging.getLoggerClass()):  # type: ignore
    """Logger subclass that provides the additional `notice` level."""

    @staticmethod
    def getLogger(name: Optional[str] = None) -> "ChromiteLogger":
        logger = logging.getLogger(name)
        if not isinstance(logger, ChromiteLogger):
            raise TypeError(
                f"Logger({logging.root.__class__.__name__}) not ChromiteLogger"
            )
        return logger

    def __init__(self, name: str, level: int = logging.NOTSET) -> None:
        super().__init__(name, level=level)
        logging.addLevelName(NOTICE, "NOTICE")

    def notice(
        self, msg: str, *args: Tuple[Any, ...], **kwargs: Dict[str, Any]
    ) -> None:
        if self.isEnabledFor(NOTICE):
            self._log(NOTICE, msg, args, **kwargs)


logging.setLoggerClass(ChromiteLogger)

# Monkeypatching these attributes onto the logging module can be removed once
# all logging calls in chromite are done via methods on a Logger instance, e.g.
# `log = logging.getLogger(); log.notice(...)`, rather than the top-level helper
# functions such as `logging.notice(...)` directly.
logging.notice = functools.partial(logging.log, NOTICE)  # type: ignore
logging.NOTICE = NOTICE  # type: ignore
logging.addLevelName(NOTICE, "NOTICE")
