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
        root_path=tmp_path / "portage-stable", name="portage-stable"
    )
    chromiumos_overlay = portage_testables.Overlay(
        root_path=tmp_path / "chromiumos-overlay", name="chromiumos"
    )
    eclass_overlay = portage_testables.Overlay(
        root_path=tmp_path / "eclass-overlay", name="eclass-overlay"
    )
    baseboard_fake = portage_testables.Overlay(
        root_path=tmp_path / "baseboard-fake",
        name="baseboard-fake",
    )
    baseboard_fake.create_profile(
        make_defaults={
            "ARCH": "amd64",
            "USE": "some another masked not_masked",
            "USE_EXPAND": "SOME_VAR",
            "SOME_VAR": "baseboard_val",
        },
        use_mask=["masked", "not_masked"],
        use_force=["amd64"],
    )

    overlay_fake = portage_testables.Overlay(
        root_path=tmp_path / "overlay-fake",
        name="fake",
        parent_overlays=[baseboard_fake],
    )
    overlay_fake.create_profile(
        make_defaults={
            "USE": "fake -another -baseboard_fake_private",
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
        root_path=tmp_path / "baseboard-fake-private",
        name="baseboard-fake-private",
        parent_overlays=[baseboard_fake],
    )
    baseboard_fake_private.create_profile(
        make_defaults={"USE": "baseboard_fake_private"},
        profile_parents=[baseboard_fake.profiles[Path("base")]],
    )

    overlay_fake_private = portage_testables.Overlay(
        root_path=tmp_path / "overlay-fake-private",
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
        root_path=tmp_path / "overlay-faux-private",
        name="faux-private",
        parent_overlays=[
            baseboard_fake,
            overlay_fake,
            baseboard_fake_private,
            overlay_fake_private,
        ],
    )
    overlay_faux_private.create_profile(
        profile_parents=[
            overlay_fake_private.profiles[Path("base")],
        ],
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
    ]
    with mock.patch(
        "chromite.lib.portage_util.FindOverlays",
        return_value=[str(x.path) for x in overlays],
    ):
        # We just changed the overlays with our mock, we need to clear the
        # cache.
        # pylint: disable=protected-access
        build_query._get_all_overlays_by_name.cache_clear()
        yield overlays
