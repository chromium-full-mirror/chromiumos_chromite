# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configuration options for cbuildbot boards."""

#
# Define assorted constants describing various sets of boards.
#

# Base per-board configuration.
# Every board must appear in exactly 1 of the following sets.

#
# Define assorted constants describing various sets of boards.
#

# Base per-board configuration.
# Every board must appear in exactly 1 of the following sets.

arm_internal_release_boards = frozenset(
    [
        "arkham",
        "gale",
        "hana",
        "littlejoe",
        "nyan_big",
        "nyan_blaze",
        "tael",
        "veyron_mighty",
        "veyron_minnie",
        "veyron_speedy",
        "viking",
        "viking-arm64",
        "viking-poc2",
        "whirlwind",
    ]
)

arm_external_boards = frozenset(
    [
        "arm-generic",
        "arm64-generic",
        "arm64-llvmpipe",
    ]
)

x86_internal_release_boards = frozenset(
    [
        "deltaur",
        "falco_li",
        "glados",
        "guado_labstation",
        "guybrush",
        "jecht",
        "majolica",
        "mancomb",
        "poppy",
        "sludge",
        "tatl",
        "wristpin",
    ]
)

x86_external_boards = frozenset(
    [
        "amd64-generic",
    ]
)

# Board can appear in 1 or more of the following sets.
brillo_boards = frozenset(
    [
        "arkham",
        "gale",
        "mistral",
        "whirlwind",
    ]
)

dustbuster_boards = frozenset(
    [
        "wristpin",
    ]
)

loonix_boards = frozenset([])

reven_boards = frozenset(
    [
        "reven",
        "reven-vmtest",
    ]
)

wshwos_boards = frozenset(
    [
        "littlejoe",
        "viking",
        "viking-arm64",
        "viking-poc2",
    ]
)

moblab_boards = frozenset(
    [
        "puff-moblab",
        "fizz-moblab",
    ]
)

scribe_boards = frozenset(
    [
        "guado-macrophage",
        "puff-macrophage",
    ]
)

termina_boards = frozenset(
    [
        "sludge",
        "tatl",
        "tael",
    ]
)

labstation_boards = frozenset(
    [
        "fizz-labstation",
        "guado_labstation",
    ]
)

nofactory_boards = termina_boards | reven_boards | labstation_boards

noimagetest_boards = (
    termina_boards | scribe_boards | wshwos_boards | dustbuster_boards
)

nohwqual_boards = (
    termina_boards
    | wshwos_boards
    | dustbuster_boards
    | reven_boards
)

base_layout_boards = termina_boards

builder_incompatible_binaries_boards = frozenset(
    [
        "grunt",
        "grunt-arc64",
        "grunt-arc-r",
        "guybrush",
        "majolica",
        "mancomb",
        "zork",
        "zork-arc-r",
        "zork-borealis",
        "skyrim",
        "skyrim-chausie",
        "skyrim-kernelnext",
    ]
)
