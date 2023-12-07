# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite extensions on top of the collections module."""

from typing import Dict, Iterable, List, NamedTuple, Optional


def GroupNamedtuplesByKey(
    input_iter: Iterable[NamedTuple], key: str
) -> Dict[Optional[str], List[NamedTuple]]:
    """Split an iterable of namedtuples, based on value of a key.

    Args:
        input_iter: An iterable of namedtuples.
        key: A string specifying the key name to split by.

    Returns:
        A dictionary, mapping from each unique value for |key| that
        was encountered in |input_iter| to a list of entries that had
        that value.
    """
    split_dict: Dict[Optional[str], List[NamedTuple]] = {}
    for entry in input_iter:
        split_dict.setdefault(getattr(entry, key, None), []).append(entry)
    return split_dict
