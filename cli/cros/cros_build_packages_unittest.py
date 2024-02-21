# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros build-packages tests."""

import pytest

from chromite.cli.cros import cros_build_packages
from chromite.lib import commandline
from chromite.lib import cros_build_lib


@pytest.fixture(name="parser")
def _parser():
    parser = commandline.ArgumentParser()
    cros_build_packages.BuildPackagesCommand.AddParser(parser)
    yield parser


@pytest.fixture(name="required_args")
def _required_args():
    yield ["--board=board"]


@pytest.fixture(autouse=True)
def no_default_board(monkeypatch):
    """Clear any locally set default board."""
    monkeypatch.setattr(cros_build_lib, "GetDefaultBoard", lambda: None)


def test_chrome(parser, required_args) -> None:
    opts = parser.parse_args(["--chrome", *required_args])
    cros_build_packages.BuildPackagesCommand.ProcessOptions(parser, opts)
    cmd = cros_build_packages.BuildPackagesCommand(opts)

    assert cmd.options.internal
    assert cmd.options.build_run_config.internal_chrome
    assert not cmd.options.use_any_chrome
    assert not cmd.options.build_run_config.use_any_chrome


def test_chromium(parser, required_args) -> None:
    opts = parser.parse_args(["--chromium", *required_args])
    cros_build_packages.BuildPackagesCommand.ProcessOptions(parser, opts)
    cmd = cros_build_packages.BuildPackagesCommand(opts)

    assert not cmd.options.internal
    assert not cmd.options.build_run_config.internal_chrome
    assert not cmd.options.use_any_chrome
    assert not cmd.options.build_run_config.use_any_chrome


def test_no_chrome_option(parser, required_args) -> None:
    opts = parser.parse_args(required_args)
    cros_build_packages.BuildPackagesCommand.ProcessOptions(parser, opts)
    cmd = cros_build_packages.BuildPackagesCommand(opts)

    assert not cmd.options.internal
    assert not cmd.options.build_run_config.internal_chrome
    assert cmd.options.use_any_chrome
    assert cmd.options.build_run_config.use_any_chrome
