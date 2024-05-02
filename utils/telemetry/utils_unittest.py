# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the config and anonymizer utils."""

import getpass
import re

from chromite.utils.telemetry import utils


def test_default_anonymizer_to_remove_username_from_path(monkeypatch) -> None:
    """Test that default Anonymizer redacts username."""
    monkeypatch.setattr(getpass, "getuser", lambda: "user")

    a = utils.Anonymizer()
    output = a.apply("/home/user/docs")

    assert output == "/home/<user>/docs"


def test_anonymizer_to_apply_passed_replacements() -> None:
    """Test anonymizer to apply the requested replacements."""
    text = "/home/%s/docs" % getpass.getuser()

    replacements = [(re.escape(getpass.getuser()), "<user>")]
    a = utils.Anonymizer(replacements=replacements)
    output = a.apply(text)

    assert output == "/home/<user>/docs"


def test_anonymizer_to_apply_multiple_replacements() -> None:
    """Test anonymizer to apply the passed replacements in order."""
    replacements = [(re.escape("abc"), "x"), (re.escape("xyz"), "t")]
    text = "hello abcd. how is xyz. abcyz"

    a = utils.Anonymizer(replacements=replacements)
    output = a.apply(text)

    assert output == "hello xd. how is t. t"


def test_default_anonymizer_skip_root(monkeypatch) -> None:
    """Test the anonymizer skips the root user."""
    monkeypatch.setattr(getpass, "getuser", lambda: "root")

    text = "/root/home service.sysroot.SetupBoard"
    a = utils.Anonymizer()
    output = a.apply(text)

    assert output == text
