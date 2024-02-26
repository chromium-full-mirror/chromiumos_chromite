# Copyright 2016 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""CLI for running Chrome OS tests from lib/cros_test.py."""

from chromite.lib import cros_test
from chromite.lib import telemetry
from chromite.lib.telemetry import trace


tracer = trace.get_tracer(__name__)


def main(argv):
    opts = cros_test.ParseCommandLine(argv)
    opts.Freeze()

    telemetry.initialize(opts.log_telemetry)

    with tracer.start_as_current_span("chromite.scripts.cros_run_test") as span:
        returncode = cros_test.CrOSTest(opts).Run()
        span.set_attribute("returncode", returncode)
        return returncode
