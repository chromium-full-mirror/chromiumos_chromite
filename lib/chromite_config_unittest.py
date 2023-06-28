# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test creation of ~/.config/chromite and dir permissions."""

import os

from chromite.lib import chromite_config
from chromite.lib import osutils


def test_chromite_config_created(monkeypatch, tmp_path):
    d = tmp_path / ".config" / "chromite"
    monkeypatch.setattr(chromite_config, "DIR", d)

    chromite_config.initialize()
    assert os.path.exists(d)


def test_chromite_config_chowns_to_non_root(monkeypatch, tmp_path):
    d = tmp_path / ".config" / "chromite"
    monkeypatch.setattr(chromite_config, "DIR", d)
    osutils.SafeMakedirs(d, sudo=True, user="root")
    assert d.owner() == "root"

    chromite_config.initialize()
    assert d.owner() != "root"
