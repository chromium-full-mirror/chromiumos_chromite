# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for cros_update_metadata_cache."""

import io
from unittest import mock

import chromite as cr
from chromite.lib import portage_util
from chromite.scripts import cros_update_metadata_cache


def test_generate_repos_conf(tmp_path):
    """Test for generate_repos_conf."""

    overlay1 = cr.test.Overlay(f"{tmp_path}/src/overlays/foo", "foo")
    overlay2 = cr.test.Overlay(f"{tmp_path}/src/overlays/bar", "bar")
    overlay3 = cr.test.Overlay(f"{tmp_path}/src/overlays/baz", "baz")
    overlays = [overlay1.path, overlay2.path, overlay3.path]

    output = io.StringIO()
    with mock.patch.object(portage_util, "FindOverlays", return_value=overlays):
        cros_update_metadata_cache.generate_repos_conf(output)

    correct_output = (
        f"[foo]\nlocation = {tmp_path}/src/overlays/foo\n"
        f"[bar]\nlocation = {tmp_path}/src/overlays/bar\n"
        f"[baz]\nlocation = {tmp_path}/src/overlays/baz\n"
    )
    assert output.getvalue() == correct_output


def test_main(run_mock):
    """Test the entire script mocking all commands run."""
    del run_mock
    cros_update_metadata_cache.main()
