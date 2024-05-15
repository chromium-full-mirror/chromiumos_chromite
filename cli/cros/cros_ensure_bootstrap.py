# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Ensure tools have been bootstrapped from the network.

This allows bootstrapping tools that chromite utilizes before disabling network
access.
"""

import logging

from chromite.cli import command
from chromite.lib import ensure_bootstrap


@command.command_decorator("ensure-bootstrap")
class EnsureBootstrapCommand(command.CliCommand):
    """Ensure tools have been bootstrapped from the network."""

    def Run(self):
        logging.notice("Caching tools from network (cipd/vpython/etc...)")
        ensure_bootstrap.for_everything()
