# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parser for ebuild Manifest files.

https://wiki.gentoo.org/wiki/Repository_format/package/Manifest
"""

import dataclasses


@dataclasses.dataclass()
class Dist:
    """A DIST entry."""

    name: str
    size: int
    hashes: dict[str, str]

    def to_string(self) -> str:
        """Return a Manifest file."""
        hashes = " ".join(f"{k} {v}" for k, v in sorted(self.hashes.items()))
        return f"DIST {self.name} {self.size} {hashes}"


@dataclasses.dataclass()
class Manifest:
    """A Manifest file.

    We only support DIST entries at this point as everything else is unused when
    ebuilds are stored in git repos with "thin-manifests" enabled (which we use
    everywhere in CrOS).
    """

    dist: dict[str, Dist]

    def to_string(self) -> str:
        """Return a Manifest file."""
        return "".join(
            f"{v.to_string()}\n" for k, v in sorted(self.dist.items())
        )


def parse(data: str) -> Manifest:
    """Parse a Manifest."""
    entries = {}
    for line in data.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue

        # <type> <filename> <size> <hash-type> <hash> [<hash-type> <hash> ...]
        fields = line.split()
        diter = iter(fields)
        if next(diter) != "DIST":
            raise ValueError(f"Unknown manifest line: {line}")
        if len(fields) < 5 or (len(fields) - 3) % 2:
            raise ValueError(
                f"DIST line has incorrect number of fields: {line}"
            )

        name = next(diter)
        size = int(next(diter))
        entry = Dist(
            name,
            size,
            dict((hn, hv) for hn, hv in zip(diter, diter)),
        )
        if name in entries:
            raise ValueError(f"DIST entries duplicated for {name}")
        entries[name] = entry

    return Manifest(entries)
