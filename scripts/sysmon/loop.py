# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sleep loop."""

import logging
import time


logger = logging.getLogger(__name__)


class SleepLoop:
    """Sleep loop."""

    def __init__(self, callback, interval=60) -> None:
        """Initialize instance.

        Args:
            callback: Function to call on each loop.
            interval: Time between loops in seconds.
        """
        self._callback = callback
        self._interval = interval

    def loop_once(self) -> None:
        """Do actions for a single loop."""
        try:
            self._callback()
        except Exception:
            logger.exception("Error during loop.")

    def loop_forever(self) -> None:
        while True:
            self.loop_once()
            _force_sleep(self._interval)


def _force_sleep(secs) -> None:
    """Force sleep for at least the given number of seconds."""
    now = time.time()
    finished_time = now + secs
    while now < finished_time:
        remaining = finished_time - now
        logger.debug("Sleeping for %d, %d remaining", secs, remaining)
        time.sleep(remaining)
        now = time.time()
