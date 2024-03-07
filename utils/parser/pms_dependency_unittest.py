# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unittests for pms_dependency parsing module."""

import pytest

from chromite.utils.parser import pms_dependency


def test_merge_root_nodes() -> None:
    """Check merging two RootNode's."""
    node1 = pms_dependency.parse("a || ( b c ) d")
    node2 = pms_dependency.parse("|| ( e f ) g")
    node = node1 + node2
    assert isinstance(node, pms_dependency.RootNode)
    assert str(node) == "a || ( b c ) d || ( e f ) g"
    # Make sure the addition didn't modify the sources.
    assert str(node1) == "a || ( b c ) d"
    assert str(node2) == "|| ( e f ) g"


def test_merge_allof_nodes() -> None:
    """Check merging two AllOfNode's."""
    node1 = pms_dependency.parse("( b c )").children[0]
    node2 = pms_dependency.parse("( e f )").children[0]
    node = node1 + node2
    assert isinstance(node, pms_dependency.AllOfNode)
    assert str(node) == "( b c e f )"
    # Make sure the addition didn't modify the sources.
    assert str(node1) == "( b c )"
    assert str(node2) == "( e f )"


def test_merge_anyof_nodes() -> None:
    """Check merging two AnyOfNode's."""
    node1 = pms_dependency.parse("|| ( b c )").children[0]
    node2 = pms_dependency.parse("|| ( e f )").children[0]
    node = node1 + node2
    assert isinstance(node, pms_dependency.AnyOfNode)
    assert str(node) == "|| ( b c e f )"
    # Make sure the addition didn't modify the sources.
    assert str(node1) == "|| ( b c )"
    assert str(node2) == "|| ( e f )"


def test_merge_use_nodes() -> None:
    """Check merging two UseNode's."""
    node1 = pms_dependency.parse("flag? ( b c )").children[0]
    node2 = pms_dependency.parse("flag? ( e f )").children[0]
    node = node1 + node2
    assert isinstance(node, pms_dependency.UseNode)
    assert str(node) == "flag? ( b c e f )"
    # Make sure the addition didn't modify the sources.
    assert str(node1) == "flag? ( b c )"
    assert str(node2) == "flag? ( e f )"


def test_merge_incompatible_nodes() -> None:
    """Do not let incompatible nodes merge."""
    root = pms_dependency.RootNode()
    allof = pms_dependency.AllOfNode()
    anyof = pms_dependency.AnyOfNode()
    use = pms_dependency.UseNode("flag")
    for lhs, rhs in (
        (root, allof),
        (root, anyof),
        (root, use),
        (allof, anyof),
        (allof, use),
        (anyof, use),
        (root, 1),
        (allof, 1),
        (anyof, 1),
        (use, 1),
        (root, None),
        (allof, None),
        (anyof, None),
        (use, None),
    ):
        with pytest.raises(TypeError):
            _ = lhs + rhs


def test_truthiness_nodes() -> None:
    """Check truthiness of nodes."""
    assert not pms_dependency.parse("")
    assert pms_dependency.parse("a")
