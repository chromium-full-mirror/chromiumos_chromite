# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for utils/attrs_freezer.py."""

from typing import Any, Type

import pytest

from chromite.utils import attrs_freezer


class _FreezableStub(attrs_freezer.Freezable):
    """Minimal class that does not override __setattr__."""

    def expected_set_value(self, passed_in_value: int) -> int:
        """Return the int value that should be set to after calling setattr."""
        return passed_in_value

    def __init__(self) -> None:
        """Initialize some attributes so we can set them later."""
        self.a = 0
        self.b = 0
        super().__init__()


class _FreezableWithSetattr(_FreezableStub):
    """Class that overrides __setattr__."""

    SETATTR_OFFSET = 10

    def __setattr__(self, attr: str, value: Any) -> None:
        """Adjust the assigned value so we can confirm that this code ran."""
        object.__setattr__(self, attr, self.SETATTR_OFFSET + value)

    def expected_set_value(self, passed_in_value: int) -> int:
        """Return the int value that should be set to after calling setattr."""
        return passed_in_value + self.SETATTR_OFFSET


parametrize_by_freezable_classes = pytest.mark.parametrize(
    "freezable_class",
    (_FreezableStub, _FreezableWithSetattr),
)


@parametrize_by_freezable_classes
def test_setattr_before_freezing(
    freezable_class: Type[_FreezableStub],
) -> None:
    """Make sure we can set attributes before freezing the instance."""
    obj = freezable_class()
    obj.a = 1
    obj.b = 2
    assert obj.a == obj.expected_set_value(1)
    assert obj.b == obj.expected_set_value(2)


@parametrize_by_freezable_classes
def test_set_existing_attr_after_freezing(
    freezable_class: Type[_FreezableStub],
) -> None:
    """Make sure setattr does nothing to an existing attr after freezing."""
    obj = freezable_class()
    obj.a = 1
    assert obj.a == obj.expected_set_value(1)
    obj.Freeze()
    with pytest.raises(attrs_freezer.CannotModifyFrozenAttribute):
        obj.a = 3
    assert obj.a == obj.expected_set_value(1)


@parametrize_by_freezable_classes
def test_set_new_attr_after_freezing(
    freezable_class: Type[_FreezableStub],
) -> None:
    """Make sure setattr does nothing to a new attr after freezing."""
    obj = freezable_class()
    obj.Freeze()
    assert not hasattr(obj, "c"), "obj.c unexpectedly present before setting"
    with pytest.raises(attrs_freezer.CannotModifyFrozenAttribute):
        obj.c = 3  # type: ignore[attr-defined]
    assert not hasattr(obj, "c"), "obj.c unexpectedly present despite failure"


@parametrize_by_freezable_classes
def test_freezing_one_doesnt_affect_another(
    freezable_class: Type[_FreezableStub],
) -> None:
    """Make sure freezing one instance doesn't cause the other to freeze."""
    obj1 = freezable_class()
    obj2 = freezable_class()
    obj1.Freeze()
    obj2.a = 1


def test_cannot_override_freeze_method() -> None:
    """Make sure Freezable subclasses can't override Freeze()."""
    with pytest.raises(attrs_freezer.CannotCreateFreezableClass):

        class _FreezableStub(attrs_freezer.Freezable):
            def Freeze(self) -> None:
                pass


class _FreezableStubWithCustomErrorMessage(
    attrs_freezer.Freezable,
    frozen_err_msg="Cannot rejigger frozen attribute %s!",
):
    """Simple freezable class with a custom error message."""

    def __init__(self) -> None:
        """Initialize an attribute so we can try to modify it after freezing."""
        super().__init__()
        self.my_int = 1


def test_custom_error_message() -> None:
    """Make sure we can set a custom error message, and it gets used."""
    obj = _FreezableStubWithCustomErrorMessage()
    obj.Freeze()
    with pytest.raises(
        attrs_freezer.CannotModifyFrozenAttribute,
        match=r"^Cannot rejigger frozen attribute my_int!$",
    ):
        obj.my_int = 2


def test_custom_error_message_with_zero_interpolations() -> None:
    """Make sure we can't set a custom error message with <1 use of '%s'."""
    with pytest.raises(attrs_freezer.CannotCreateFreezableClass):

        class _FreezableStubWithZeroInterps(
            attrs_freezer.Freezable,
            frozen_err_msg="Cannot rejigger frozen attribute!",
        ):
            pass


def test_custom_error_message_with_two_interpolations() -> None:
    """Make sure we can't set a custom error message with >1 use of '%s'."""
    with pytest.raises(attrs_freezer.CannotCreateFreezableClass):

        class _FreezableStubWithTwoInterps(
            attrs_freezer.Freezable,
            frozen_err_msg="Cannot rejigger frozen attribute %s to %s!",
        ):
            pass


class _FreezableStubWithUnfreeze(attrs_freezer.Freezable):
    """Simple freezable class with a custom Unfreeze() method.

    In general, subclasses shouldn't try to modify _frozen. This is a guardrail
    to prevent subclasses (or other parent classes of subclasses) incidentally
    using _frozen for unrelated purposes. Unfreeze() tries to break that rule.
    Hopefully it will fail.
    """

    def Unfreeze(self) -> None:
        """Make instance attributes settable again."""
        self._frozen = False


def test_cant_set_frozen_directly() -> None:
    """Make sure Freezable subclasses can't set self._frozen."""
    obj = _FreezableStubWithUnfreeze()
    with pytest.raises(attrs_freezer.CannotSetFrozen):
        obj.Unfreeze()
