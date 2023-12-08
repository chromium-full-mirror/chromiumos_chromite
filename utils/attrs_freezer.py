# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Helpers for constructing objects with frozen attributes."""

from typing import Any, ClassVar, NoReturn


class Error(Exception):
    """Base class for exceptions related to freezable classes."""


class CannotCreateFreezableClass(Error):
    """Raised when the subclass could not be created."""


class CannotModifyFrozenAttribute(Error):
    """Raised when attempting to modify a frozen attribute."""


class CannotSetFrozen(Error):
    """Raised when someone tries to set Freezable._frozen.

    This is a guardrail to make sure no subclasses coincidentally use
    self._frozen for unrelated purposes.
    """


class Freezable:
    """A class whose attributes can be frozen via the Freeze() method."""

    _frozen: bool = False
    _FROZEN_ERR_MSG: ClassVar[str]

    def __init_subclass__(
        cls,
        frozen_err_msg: str = "Attribute values are frozen, cannot alter %s.",
    ) -> None:
        """Set up a subclass of Freezable.

        Args:
            frozen_err_msg: The message to raise if anyone tries to set
                instance attributes after Freeze() has been called. Must contain
                the literal "%s" exactly once; the attribute name will be
                interpolated here.

        Raises:
            CannotCreateFreezableClass: If the subclass overrides any methods
                that are needed for freezing (self.Freeze(), self.frozen).
            CannotCreateFreezableClass: If the frozen_err_msg doesn't contain
                exactly one '%s'.
        """
        for method_name in ("Freeze", "frozen"):
            if getattr(cls, method_name) is not getattr(Freezable, method_name):
                raise CannotCreateFreezableClass(
                    f"Class {cls} has its own {method_name}() method."
                    " Cannot use with the attrs_freezer.Class metaclass."
                )

        if frozen_err_msg is not None:
            cls._FROZEN_ERR_MSG = frozen_err_msg
        if cls._FROZEN_ERR_MSG.count("%s") != 1:
            raise CannotCreateFreezableClass(
                f"Invalid frozen_err_msg '{frozen_err_msg}'. Must contain the"
                " string literal '%s' exactly once."
            )

        original_setattr = cls.__setattr__

        def new_setattr(obj: "Freezable", name: str, value: Any) -> None:
            """If the instance is frozen, refuse to set attributes.

            Raises:
                CannotModifyFrozenAttribute: If Freeze() has been called.
                CannotSetFrozen: If the caller is trying to set obj._frozen.
            """
            if obj.frozen:
                obj.raise_cannot_modify_error(name)
            elif name == "_frozen":
                raise CannotSetFrozen(
                    "Do not set Freezable()._frozen directly. Use .Freeze()."
                )
            else:
                original_setattr(obj, name, value)

        cls.__setattr__ = new_setattr  # type: ignore[method-assign, assignment]

    @property
    def frozen(self) -> bool:
        """Return whether the instance has been frozen."""
        return self._frozen

    def Freeze(self) -> None:
        """Prevent this instance's attributes from being modified."""
        # Invoke object.__setattr__ directly to avoid any strange behavior from
        # subclasses' custom overrides.
        object.__setattr__(self, "_frozen", True)

    def raise_cannot_modify_error(self, name: str) -> NoReturn:
        """Raise a CannotModifyFrozenAttribute error.

        Args:
            name: The name of the attribute that cannot be modified.
        """
        raise CannotModifyFrozenAttribute(self._FROZEN_ERR_MSG % name)
