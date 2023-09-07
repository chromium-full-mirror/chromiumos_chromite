# Copyright 2014 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for the namespaces.py module."""

import errno
import os
import unittest

from chromite.lib import commandline
from chromite.lib import cros_test_lib
from chromite.lib import namespaces
from chromite.lib import process_util


class SetNSTests(cros_test_lib.TestCase):
    """Tests for SetNS()"""

    def testBasic(self):
        """Simple functionality test."""
        NS_PATH = "/proc/self/ns/mnt"
        if not os.path.exists(NS_PATH):
            raise unittest.SkipTest("kernel too old (missing %s)" % NS_PATH)

        with open(NS_PATH, encoding="utf-8") as f:
            try:
                namespaces.SetNS(f.fileno(), 0)
            except OSError as e:
                if e.errno != errno.EPERM:
                    # Running as non-root will fail, so ignore it.  We ran most
                    # of the code in the process which is all we really wanted.
                    raise


class UnshareTests(cros_test_lib.TestCase):
    """Tests for Unshare()"""

    def testBasic(self):
        """Simple functionality test."""
        try:
            namespaces.Unshare(namespaces.CLONE_NEWNS)
        except OSError as e:
            if e.errno != errno.EPERM:
                # Running as non-root will fail, so ignore it.  We ran most
                # of the code in the process which is all we really wanted.
                raise


class UnshareCGroupsTests(cros_test_lib.TestCase):
    """Tests for Unshare() of CGroups"""

    def testBasic(self):
        """Simple functionality test."""
        try:
            namespaces.Unshare(namespaces.CLONE_NEWCGROUP)
            # After we have unshared cgroups, every cgroups entry in
            # /proc/self/cgroups should have a path that's root (ie "/").
            with open("/proc/self/cgroup", encoding="utf-8") as cgroups:
                for cgroup in cgroups:
                    self.assertRegex(cgroup, ":/\n$")
        except OSError as e:
            if e.errno != errno.EPERM:
                # Running as non-root will fail, so ignore it.  We ran most
                # of the code in the process which is all we really wanted.
                raise


class SimpleUnshareCgroupsTests(cros_test_lib.MockTestCase):
    """Tests for SimpleUnshare with cgroups."""

    def testSimpleUnshare(self):
        """Simple functionality test."""
        unshare_mock = self.PatchObject(namespaces, "Unshare")
        namespaces.SimpleUnshare(
            mount=False,
            uts=False,
            ipc=False,
            net=False,
            pid=False,
            cgroup=True,
        )
        unshare_mock.assert_called_once_with(namespaces.CLONE_NEWCGROUP)


class CreateUserNsTests(cros_test_lib.TestCase):
    """Tests for CreateUserNs()"""

    def testBasic(self):
        """Simple functionality test."""
        # Since entering namespaces will modify the state of the current
        # process, fork in advance.
        pid = os.fork()
        if pid == 0:
            # Below we call os._exit() to exit the process directly. It is one
            # of the officially justified usage of the function.
            # pylint: disable=protected-access
            try:
                # Enter a new user namespace. The current process will gain
                # capabilities within the namespace.
                namespaces.CreateUserNs()
            except Exception:
                os._exit(10)
            try:
                # Enter a new mount namespace. This operation requires
                # privileges, but we have one thanks to the user namespace.
                namespaces.Unshare(namespaces.CLONE_NEWNS)
            except Exception:
                os._exit(20)
            os._exit(0)

        status = os.waitpid(pid, 0)[1]
        self.assertEqual(process_util.GetExitStatus(status), 0)


class ReExecuteWithNamespaceTests(cros_test_lib.MockTestCase):
    """Tests for ReExecuteWithNamespace()."""

    def setUp(self):
        self.PatchDict(
            os.environ,
            {
                "SUDO_GID": "123",
                "SUDO_UID": "456",
                "SUDO_USER": "testuser",
            },
        )

    def testReExecuteWithNamespace(self):
        """Verify SimpleUnshare is called and the non-root user is restored."""
        run_as_root_user_mock = self.PatchObject(commandline, "RunAsRootUser")
        simple_unshare_mock = self.PatchObject(namespaces, "SimpleUnshare")
        os_initgroups_mock = self.PatchObject(os, "initgroups")
        os_setresgid_mock = self.PatchObject(os, "setresgid")
        os_setresuid_mock = self.PatchObject(os, "setresuid")

        namespaces.ReExecuteWithNamespace([], preserve_env=True)

        run_as_root_user_mock.assert_called_once_with([], preserve_env=True)
        simple_unshare_mock.assert_called_once_with(net=True, pid=True)
        os_initgroups_mock.assert_called_once_with("testuser", 123)
        os_setresgid_mock.assert_called_once_with(123, 123, -1)
        os_setresuid_mock.assert_called_once_with(456, 456, -1)
        self.assertEqual("testuser", os.environ["USER"])

    def testClearSavedId(self):
        """Verify clear_saved_id works."""
        run_as_root_user_mock = self.PatchObject(commandline, "RunAsRootUser")
        simple_unshare_mock = self.PatchObject(namespaces, "SimpleUnshare")
        os_initgroups_mock = self.PatchObject(os, "initgroups")
        os_setresgid_mock = self.PatchObject(os, "setresgid")
        os_setresuid_mock = self.PatchObject(os, "setresuid")

        namespaces.ReExecuteWithNamespace(
            [], preserve_env=True, clear_saved_id=True
        )

        run_as_root_user_mock.assert_called_once_with([], preserve_env=True)
        simple_unshare_mock.assert_called_once_with(net=True, pid=True)
        os_initgroups_mock.assert_called_once_with("testuser", 123)
        os_setresgid_mock.assert_called_once_with(123, 123, 123)
        os_setresuid_mock.assert_called_once_with(456, 456, 456)
        self.assertEqual("testuser", os.environ["USER"])
