# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Automatically add return type None where it's obvious."""

from typing import Sequence, Union

import libcst as cst
from libcst import codemod


_NONE_NAME = cst.Name(value="None")
_NONE_ANNOTATION = cst.Annotation(annotation=_NONE_NAME)


def _return_is_none(statement: cst.Return) -> bool:
    """True if a return statement clearly returns None."""
    if not statement.value:
        return True
    if isinstance(statement.value, cst.Name):
        return statement.value.value == "None"
    return False


def _only_returns_none(
    body: Sequence[Union[cst.SimpleStatementLine, cst.BaseCompoundStatement]]
) -> bool:
    """Does a function body only return None?"""
    for statement in body:
        if isinstance(statement, cst.FunctionDef):
            continue
        if isinstance(statement, cst.Try):
            if not _only_returns_none(statement.body.body):
                return False
            for handler in statement.handlers:
                if not _only_returns_none(handler.body.body):
                    return False
            if statement.orelse:
                if not _only_returns_none(statement.orelse.body.body):
                    return False
            if statement.finalbody:
                if not _only_returns_none(statement.finalbody.body.body):
                    return False
        if isinstance(statement, cst.BaseCompoundStatement):
            if not _only_returns_none(statement.body.body):
                return False
            continue
        for small_statement in statement.body:
            if isinstance(small_statement, cst.Expr):
                if isinstance(small_statement.value, cst.Yield):
                    # This is a generator function!
                    return False
            if isinstance(small_statement, cst.Return):
                if not _return_is_none(small_statement):
                    return False
    return True


class AutoTypeNone(codemod.VisitorBasedCodemodCommand):
    """Codemod implementation."""

    DESCRIPTION: str = __doc__

    def leave_FunctionDef(
        self, original_node: cst.FunctionDef, updated_node: cst.FunctionDef
    ) -> cst.FunctionDef:
        """Update FunctionDef AST nodes."""
        if original_node.returns:
            return updated_node
        if original_node.name.value == "__init__":
            return updated_node
        if _only_returns_none(original_node.body.body):
            return updated_node.with_changes(returns=_NONE_ANNOTATION)
        return updated_node
