# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""File interaction utilities."""

import contextlib
import os
from typing import Any, IO, Iterator, Union


@contextlib.contextmanager
def Open(
    obj: Union[str, "os.PathLike[str]", IO[Any]], mode: str = "r", **kwargs: Any
) -> Iterator[IO[Any]]:
    """Convenience ctx that accepts a file path or an opened file object."""
    if isinstance(obj, (str, os.PathLike)):
        # TODO(b/236161656): Fix.
        # pylint: disable-next=unspecified-encoding
        with open(obj, mode=mode, **kwargs) as f:
            yield f
    else:
        yield obj
