# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Automatically type "dunder" (short for double-underscore) methods.

Many dunder methods (e.g., __init__, __len__, __str__, ...) have predictable
type signatures.  Automatically apply those.
"""

from typing import Callable, Dict, Optional

import libcst as cst
from libcst import codemod


_Transformer = Callable[
    [codemod.CodemodContext, cst.FunctionDef], cst.FunctionDef
]


def _progn(*args: _Transformer) -> _Transformer:
    """Combine multiple transformers."""

    def _transformer(
        context: codemod.CodemodContext, func: cst.FunctionDef
    ) -> cst.FunctionDef:
        for transformer in args:
            func = transformer(context, func)
        return func

    return _transformer


def _returns(annotation: cst.BaseExpression) -> _Transformer:
    """Transformer to annotate return value.

    Args:
        annotation: The annotation to apply.

    Returns:
        Transformer function.
    """
    return lambda _context, func: func.with_changes(
        returns=cst.Annotation(annotation=annotation)
    )


def _argn(pos: int, annotation: cst.BaseExpression) -> _Transformer:
    """Transformer to annotate return value.

    Args:
        pos: The 0-indexed argument number to annotate.  Note: special arguments
            (self, cls) are skipped.
        annotation: The annotation to apply.

    Returns:
        Transformer function.
    """

    def _transformer(
        _context: codemod.CodemodContext, func: cst.FunctionDef
    ) -> cst.FunctionDef:
        param_idx = pos
        if func.params.params[0].name.value in ("self", "cls"):
            param_idx += 1
        new_param = func.params.params[param_idx].with_changes(
            annotation=cst.Annotation(annotation=annotation)
        )
        new_params = list(func.params.params)
        new_params[param_idx] = new_param
        return func.with_changes(
            params=func.params.with_changes(
                params=new_params,
            ),
        )

    return _transformer


def _add_import(module: str, obj: Optional[str] = None) -> _Transformer:
    """Transformer to add an import to the module.

    Args:
        module: The module to import.
        obj: The optional object to import from that module.

    Returns:
        Transformer function.
    """

    def _transformer(
        context: codemod.CodemodContext, func: cst.FunctionDef
    ) -> cst.FunctionDef:
        codemod.visitors.AddImportsVisitor.add_needed_import(
            context, module, obj
        )
        return func

    return _transformer


_TRANSFORMERS: Dict[str, _Transformer] = {
    "__init__": _returns(cst.Name(value="None")),
    "__repr__": _returns(cst.Name(value="str")),
    "__str__": _returns(cst.Name(value="str")),
    "__bytes__": _returns(cst.Name(value="bytes")),
    "__format__": _progn(
        _argn(0, cst.Name(value="str")),
        _returns(cst.Name(value="str")),
    ),
    "__lt__": _returns(cst.Name(value="bool")),
    "__le__": _returns(cst.Name(value="bool")),
    "__gt__": _returns(cst.Name(value="bool")),
    "__ge__": _returns(cst.Name(value="bool")),
    "__ne__": _progn(
        _add_import("typing", "Any"),
        _argn(0, cst.Name(value="Any")),
        _returns(cst.Name(value="bool")),
    ),
    "__eq__": _progn(
        _add_import("typing", "Any"),
        _argn(0, cst.Name(value="Any")),
        _returns(cst.Name(value="bool")),
    ),
    "__hash__": _returns(cst.Name(value="int")),
    "__bool__": _returns(cst.Name(value="bool")),
    "__len__": _returns(cst.Name(value="int")),
    "__contains__": _returns(cst.Name(value="bool")),
    "__int__": _returns(cst.Name(value="int")),
    "__float__": _returns(cst.Name(value="float")),
    "__index__": _returns(cst.Name(value="int")),
    "__getattr__": _argn(0, cst.Name(value="str")),
    "__getattribute__": _argn(0, cst.Name(value="str")),
    "__setattr__": _argn(0, cst.Name(value="str")),
    "__delattr__": _argn(0, cst.Name(value="str")),
}


class AutoTypeDunders(codemod.VisitorBasedCodemodCommand):
    """Codemod implementation."""

    DESCRIPTION: str = __doc__

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Update FunctionDef AST nodes."""
        transformer = _TRANSFORMERS.get(original_node.name.value)
        if not transformer:
            return updated_node
        return transformer(self.context, updated_node)
