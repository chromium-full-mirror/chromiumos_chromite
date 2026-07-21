# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Mypy plugin to support chromite extensions."""

import mypy.nodes  # pylint: disable=import-error
import mypy.plugin  # pylint: disable=import-error
import mypy.types  # pylint: disable=import-error


class ChromiteLoggerPlugin(mypy.plugin.Plugin):
    """Plugin that adds ChromiteLogger extensions."""

    def get_additional_deps(
        self, file: mypy.nodes.MypyFile
    ) -> list[tuple[int, str, int]]:
        if file.fullname != "logging":
            return []

        # Define logging.notice.  Copy the typing from logging.info.
        has_notice = any(
            isinstance(d, mypy.nodes.FuncDef) and d.name == "notice"
            for d in file.defs
        )
        if not has_notice:
            for d in file.defs:
                if isinstance(d, mypy.nodes.FuncDef) and d.name == "info":
                    new_args = [
                        mypy.nodes.Argument(
                            variable=mypy.nodes.Var(
                                arg.variable.name, arg.variable.type
                            ),
                            type_annotation=arg.type_annotation,
                            initializer=arg.initializer,
                            kind=arg.kind,
                            pos_only=arg.pos_only,
                        )
                        for arg in d.arguments
                    ]
                    # Should never happen, but make mypy happy.
                    assert d.type is None or isinstance(
                        d.type, mypy.types.FunctionLike
                    )
                    file.defs.append(
                        mypy.nodes.FuncDef(
                            name="notice",
                            arguments=new_args,
                            body=d.body,
                            typ=d.type,
                        )
                    )
                    break

        # Define logging.NOTICE.
        has_NOTICE = any(
            isinstance(d, mypy.nodes.AssignmentStmt)
            and any(
                isinstance(l, mypy.nodes.NameExpr) and l.name == "NOTICE"
                for l in d.lvalues
            )
            for d in file.defs
        )
        if not has_NOTICE:
            file.defs.append(
                mypy.nodes.AssignmentStmt(
                    lvalues=[mypy.nodes.NameExpr("NOTICE")],
                    rvalue=mypy.nodes.IntExpr(25),
                    type=mypy.types.UnboundType("Final"),
                    new_syntax=True,
                )
            )

        return []


def plugin(version: str) -> type[mypy.plugin.Plugin]:
    """Register our plugins."""
    del version  # Unused.
    return ChromiteLoggerPlugin
