# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the attrs_freezer module."""

from chromite.lib import cros_test_lib
from chromite.utils import attrs_freezer


class FrozenAttributesTest(cros_test_lib.TestCase):
    """Test FrozenAttributes functionality."""

    class StubClass:
        """Any class that does not override __setattr__."""

    class SetattrClass:
        """Class that does override __setattr__."""

        SETATTR_OFFSET = 10

        def __setattr__(self, attr, value) -> None:
            """Adjust value here to later confirm that this code ran."""
            object.__setattr__(self, attr, self.SETATTR_OFFSET + value)

    def _TestBasics(self, cls) -> None:
        # pylint: disable=attribute-defined-outside-init
        def _Expected(val):
            return getattr(cls, "SETATTR_OFFSET", 0) + val

        obj = cls()
        obj.a = 1
        obj.b = 2
        self.assertEqual(_Expected(1), obj.a)
        self.assertEqual(_Expected(2), obj.b)

        obj.Freeze()
        self.assertRaises(attrs_freezer.Error, setattr, obj, "a", 3)
        self.assertEqual(_Expected(1), obj.a)

        self.assertRaises(attrs_freezer.Error, setattr, obj, "c", 3)
        self.assertFalse(hasattr(obj, "c"))

    def testFrozenByMetaclass(self) -> None:
        """Test attribute freezing with FrozenAttributesClass."""

        class StubByMeta(self.StubClass, metaclass=attrs_freezer.Class):
            """Class that freezes StubClass using metaclass construct."""

        self._TestBasics(StubByMeta)

        class SetattrByMeta(self.SetattrClass, metaclass=attrs_freezer.Class):
            """Class that freezes SetattrClass using metaclass construct."""

        self._TestBasics(SetattrByMeta)
