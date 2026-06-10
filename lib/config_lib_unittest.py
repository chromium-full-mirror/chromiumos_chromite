# Copyright 2015 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for config."""

from chromite.lib import config_lib
from chromite.lib import cros_test_lib


class GetSiteParamsTest(cros_test_lib.TestCase):
    """Tests for the return value from config_lib.GetSiteParams()."""

    def testAttributeAccess(self) -> None:
        """Test that dot-accessor works correctly."""
        site_params = config_lib.GetSiteParams()

        # Ensure our test key is not in site_params.
        self.assertNotIn("foo", site_params)

        # Test that we raise when accessing a non-existent value.
        # pylint: disable=pointless-statement
        with self.assertRaises(AttributeError):
            site_params.foo

        # Test the dot-accessor.
        site_params.update({"foo": "bar"})
        self.assertEqual("bar", site_params.foo)
