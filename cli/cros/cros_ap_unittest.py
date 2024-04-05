# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""cros ap tests."""

from chromite.cli import command
from chromite.cli.cros import cros_ap
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import path_util


def test_cros_ap_flash_image_translation(monkeypatch, tmp_path) -> None:
    """Test image path translations."""
    monkeypatch.setattr(cros_build_lib, "IsInsideChroot", lambda: False)

    def _to_chroot_mock(path, *_args, **_kwargs):
        return str(path).replace(str(outside), str(inside))

    monkeypatch.setattr(path_util, "ToChrootPath", _to_chroot_mock)

    inside = tmp_path / "inside"
    inside.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    img = outside / "image.bin"
    img.touch()
    expected_img = inside / "image.bin"

    flash_parse_args = ["--image", str(img), "-b", "board"]
    argv = ["ap", "flash", *flash_parse_args]
    monkeypatch.setattr(
        command.CliCommand, "TranslateToChrootArgv", lambda _: argv
    )

    parser = commandline.ArgumentParser()
    cros_ap.FlashSubcommand.AddParser(parser)
    namespace = parser.parse_args(flash_parse_args)
    cros_ap.FlashSubcommand.ProcessOptions(parser, namespace)
    cmd = cros_ap.FlashSubcommand(namespace)
    inside_argv = cmd.TranslateToChrootArgv()
    expected_argv = ["ap", "flash", "--image", str(expected_img), "-b", "board"]

    assert expected_argv == inside_argv
