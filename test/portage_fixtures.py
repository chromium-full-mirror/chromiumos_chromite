# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration and fixtures for pytest.

See the following doc link for an explanation of conftest.py and how it is used
by pytest:
https://docs.pytest.org/en/latest/fixture.html#conftest-py-sharing-fixture-functions
"""

from pathlib import Path
from unittest import mock

import pytest

import chromite as cr
from chromite.lib import build_query
from chromite.lib import constants
from chromite.lib import osutils
from chromite.lib import portage_util
from chromite.test import portage_testables


@pytest.fixture
def overlay_stack(tmp_path_factory):
    """Factory for stacked Portage overlays.

    The factory function takes an integer argument and returns an iterator of
    that many overlays, each of which has all prior overlays as parents.
    """

    def make_overlay_stack(height):
        if not height <= len(cr.test.Overlay.HIERARCHY_NAMES):
            raise ValueError(
                "Overlay stacks taller than %s are not supported. Received: %s"
                % (len(cr.test.Overlay.HIERARCHY_NAMES), height)
            )

        overlays = []

        for i in range(height):
            overlays.append(
                cr.test.Overlay(
                    root_path=tmp_path_factory.mktemp(
                        "overlay-" + cr.test.Overlay.HIERARCHY_NAMES[i]
                    ),
                    name=cr.test.Overlay.HIERARCHY_NAMES[i],
                    parent_overlays=overlays,
                )
            )
            yield overlays[i]

    return make_overlay_stack


# pylint: disable=redefined-outer-name
@pytest.fixture
def simple_sysroot(overlay_stack, tmp_path):
    """Create the simplest possible sysroot."""
    # pylint: disable=redefined-outer-name
    (overlay,) = overlay_stack(1)
    profile = overlay.create_profile()
    return cr.test.Sysroot(tmp_path, profile, [overlay])


@pytest.fixture
def fake_build_query_overlays(tmp_path):
    """Fake out the overlays for the build_query module."""
    portage_stable = portage_testables.Overlay(
        root_path=tmp_path / "src" / "third_party" / "portage-stable",
        name="portage-stable",
    )
    chromiumos_overlay = portage_testables.Overlay(
        root_path=tmp_path / "src" / "third_party" / "chromiumos-overlay",
        name="chromiumos",
    )
    eclass_overlay = portage_testables.Overlay(
        root_path=tmp_path / "src" / "third_party" / "eclass-overlay",
        name="eclass-overlay",
    )
    baseboard_fake = portage_testables.Overlay(
        root_path=tmp_path / "src" / "overlays" / "baseboard-fake",
        name="baseboard-fake",
    )
    baseboard_fake.create_profile(
        make_defaults={
            "ARCH": "amd64",
            "USE": "some another masked not_masked bootimage",
            "USE_EXPAND": "SOME_VAR",
            "SOME_VAR": "baseboard_val",
        },
        use_mask=["masked", "not_masked"],
        use_force=["amd64"],
    )

    overlay_fake = portage_testables.Overlay(
        root_path=tmp_path / "src" / "overlays" / "overlay-fake",
        name="fake",
        parent_overlays=[baseboard_fake],
    )
    overlay_fake.create_profile(
        make_defaults={
            "USE": "fake -another -baseboard_fake_private kernel-6_1",
            "SOME_VAR": "-* board_val",
            "ANOTHER_VAR": "one_val another_val",
            "USE_EXPAND": "ANOTHER_VAR",
        },
        profile_parents=[baseboard_fake.profiles[Path("base")]],
        use_mask=["-not_masked"],
    )
    overlay_fake.add_package(
        portage_testables.Package(
            category="chromeos-base",
            package="chromeos-bsp-fake",
            version="0.0.1-r256",
            IUSE="another internal +static",
            inherit=["cros-workon", "chromeos-bsp"],
            keywords="*",
        )
    )
    overlay_fake.add_package(
        portage_testables.Package(
            category="chromeos-base",
            package="chromeos-bsp-fake",
            version="9999",
            IUSE="another internal +static",
            inherit=["cros-workon", "chromeos-bsp"],
            keywords="~*",
        )
    )

    baseboard_fake_private = portage_testables.Overlay(
        root_path=tmp_path
        / "src"
        / "private-overlays"
        / "baseboard-fake-private",
        name="baseboard-fake-private",
        parent_overlays=[baseboard_fake],
    )
    baseboard_fake_private.create_profile(
        make_defaults={"USE": "baseboard_fake_private"},
        profile_parents=[baseboard_fake.profiles[Path("base")]],
    )

    overlay_fake_private = portage_testables.Overlay(
        root_path=tmp_path
        / "src"
        / "private-overlays"
        / "overlay-fake-private",
        name="fake-private",
        parent_overlays=[overlay_fake],
        make_conf={
            "CHOST": "x86_64-pc-linux-gnu",
            "USE": "internal",
        },
    )
    overlay_fake_private.create_profile(
        make_defaults={"SOME_VAR": "private_val"},
        profile_parents=[
            baseboard_fake_private.profiles[Path("base")],
            overlay_fake.profiles[Path("base")],
        ],
    )
    overlay_fake_private.create_profile(
        "alt-profile",
        make_defaults={"USE": "alt_profile"},
        profile_parents=[
            overlay_fake_private.profiles[Path("base")],
        ],
    )
    overlay_fake_private.add_package(
        portage_testables.Package(
            category="chromeos-base",
            package="chromeos-bsp-fake-private",
            version="0.0.1",
            IUSE="another internal +static",
            inherit=["cros-workon", "chromeos-bsp"],
            keywords="-* ~amd64",
        )
    )
    overlay_fake_private.add_package(
        portage_testables.Package(
            category="chromeos-base",
            package="chromeos-bsp-fake-private",
            version="9999",
            IUSE="another internal +static",
            inherit=["cros-workon", "chromeos-bsp"],
            keywords="~* amd64",
        )
    )

    overlay_faux_private = portage_testables.Overlay(
        root_path=tmp_path
        / "src"
        / "private-overlays"
        / "overlay-faux-private",
        name="faux-private",
        parent_overlays=[
            baseboard_fake,
            overlay_fake,
            baseboard_fake_private,
            overlay_fake_private,
        ],
    )
    overlay_faux_private.create_profile(
        path=Path("symlinked"),
        profile_parents=[
            overlay_fake_private.profiles[Path("base")],
        ],
    )
    osutils.SafeSymlink(
        "symlinked", overlay_faux_private.path / "profiles" / "base"
    )

    overlay_foo_private = portage_testables.Overlay(
        root_path=tmp_path / "src" / "private-overlays" / "overlay-foo-private",
        name="foo-private",
    )
    overlay_foo_private.create_profile(
        make_defaults={
            "USE": "kernel-5_15",
        },
    )

    overlays = [
        portage_stable,
        chromiumos_overlay,
        eclass_overlay,
        baseboard_fake,
        overlay_fake,
        baseboard_fake_private,
        overlay_fake_private,
        overlay_faux_private,
        overlay_foo_private,
    ]

    with mock.patch.object(constants, "SOURCE_ROOT", new=tmp_path):
        # We just changed the overlays with our mock, we need to clear the
        # cache.
        # pylint: disable=protected-access
        build_query._get_all_overlays_by_name.cache_clear()
        portage_util.FindOverlays.cache_clear()
        yield overlays
