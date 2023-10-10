# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for os_util.py."""

import os
from unittest import mock

import pytest

from chromite.utils import os_util


@pytest.fixture(name="as_root_user")
def _as_root_user(monkeypatch):
    """Monkeypatch the euid as 0."""
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    yield


@pytest.fixture(name="as_non_root_user")
def _as_non_root_user(monkeypatch):
    """Monkeypatch the euid as non-0."""
    monkeypatch.setattr(os, "geteuid", lambda: 1)
    yield


# pylint: disable=unused-argument
def test_root_user_checks_as_root_user(as_root_user):
    """Test is_[non_]root_user as the root user."""
    assert os_util.is_root_user()
    os_util.assert_root_user()

    assert not os_util.is_non_root_user()
    with pytest.raises(AssertionError):
        os_util.assert_non_root_user()


def test_root_user_checks_as_non_root_user(as_non_root_user):
    """Test is_[non_]root_user as a non-root user."""
    assert os_util.is_non_root_user()
    os_util.assert_non_root_user()

    assert not os_util.is_root_user()
    with pytest.raises(AssertionError):
        os_util.assert_root_user()


def test_root_user_decorator_as_root(as_root_user):
    """Success case for require root user decorator."""

    @os_util.require_root_user("Passes")
    def passes():
        pass

    passes()


@pytest.mark.xfail(raises=AssertionError)
def test_root_user_decorator_as_non_root(as_non_root_user):
    """Failure case for require root user decorator."""

    @os_util.require_root_user("Fails")
    def fails():
        pytest.fail("Allowed to execute as wrong user.")

    fails()


@pytest.mark.xfail(raises=AssertionError)
def test_non_root_user_decorator_as_root(as_root_user):
    """Failure case for require non-root user decorator."""

    @os_util.require_non_root_user("Fails")
    def fails():
        pytest.fail("Allowed to execute as wrong user.")

    fails()


def test_non_root_user_decorator_as_non_root(as_non_root_user):
    """Success case for require non-root user decorator."""

    @os_util.require_non_root_user("Passes")
    def passes():
        pass

    passes()


@pytest.fixture(name="switch_to_sudo_user_mock")
def _switch_to_sudo_user_mock():
    """Mock out privileged APIs."""
    with mock.patch.multiple(
        os,
        initgroups=mock.DEFAULT,
        setresgid=mock.DEFAULT,
        setresuid=mock.DEFAULT,
    ):
        yield


def test_switch_to_sudo_user_saved(as_root_user, switch_to_sudo_user_mock):
    """Verify we switch state properly."""
    os.environ.update(
        {
            "SUDO_GID": "123",
            "SUDO_UID": "456",
            "SUDO_USER": "testuser",
            "USER": "root",
        }
    )
    os_util.switch_to_sudo_user()
    assert "SUDO_GID" not in os.environ
    assert "SUDO_UID" not in os.environ
    assert "SUDO_USER" not in os.environ
    assert os.environ["USER"] == "testuser"
    os.initgroups.assert_called_once_with("testuser", 123)
    os.setresgid.assert_called_once_with(123, 123, -1)
    os.setresuid.assert_called_once_with(456, 456, -1)


def test_switch_to_sudo_user_cleared(as_root_user, switch_to_sudo_user_mock):
    """Verify we switch state properly."""
    os.environ.update(
        {
            "SUDO_GID": "123",
            "SUDO_UID": "456",
            "SUDO_USER": "testuser",
            "USER": "root",
        }
    )
    os_util.switch_to_sudo_user(clear_saved_id=True)
    assert "SUDO_GID" not in os.environ
    assert "SUDO_UID" not in os.environ
    assert "SUDO_USER" not in os.environ
    assert os.environ["USER"] == "testuser"
    os.initgroups.assert_called_once_with("testuser", 123)
    os.setresgid.assert_called_once_with(123, 123, 123)
    os.setresuid.assert_called_once_with(456, 456, 456)


# pylint: enable=unused-argument
