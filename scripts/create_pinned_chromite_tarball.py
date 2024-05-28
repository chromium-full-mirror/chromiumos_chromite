# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build a tarball of Chromite to use as a pinned version of Chromite."""

from pathlib import Path
from typing import List, Optional

from chromite.lib import commandline
from chromite.lib import compression_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import git


def _get_parser() -> commandline.ArgumentParser:
    """Creates the argparse parser."""
    parser = commandline.ArgumentParser(description=__doc__, dryrun=True)
    parser.add_argument(
        "--chromite-dir",
        type="dir_exists",
        default=constants.CHROMITE_DIR,
        help="Chromite repo directory.",
    )
    parser.add_argument(
        "--output-dir",
        type="dir_exists",
        default=constants.CHROMITE_DIR,
        help=(
            "Directory to write the Chromite tarball to, with filename "
            "chromite-${chromite_commit_date}-${chromite_commit_sha}.tar.zst."
        ),
    )
    return parser


def _create_chromite_tarball(chromite_dir: Path, output_dir: Path) -> None:
    """Create a Chromite tarball.

    Use `git archive` to create separate tarballs for the chromite repo at HEAD
    and for the pyelftools repo at HEAD (as referenced via the symlink at
    third_party/pyelftools), then merge the two tarballs. Merging unfortunately
    requires that we create the tarball uncompressed and then use zstd to
    compress the merged tarball since tar doesn't allow appending to compressed
    archives.

    Args:
        chromite_dir: The path to the Chromite repo to be bundled.
        output_dir: The path to the directory in which to create the Chromite
            tarball.
    """

    def compute_tar_filename(archive_name: str, repo_path: Path) -> str:
        """Compute the filename of the tarball for the given repo.

        Args:
            archive_name: The name of the archive to create (e.g. "chromite").
            repo_path: The path to the repo being archived.
        """
        commit = git.GetLastCommit(repo_path)
        sha1 = commit.sha
        commit_date = commit.commit_date
        commit_date_str = commit_date.strftime("%Y%m%d_%H%M%S")

        tar_filename = f"{archive_name}-{commit_date_str}-{sha1}.tar"
        return tar_filename

    chromite_tar_filename = compute_tar_filename("chromite", chromite_dir)
    chromite_tar_path = Path(output_dir) / chromite_tar_filename

    pyelftools_dir = (chromite_dir / "third_party/pyelftools").resolve()
    pyelftools_tar_filename = compute_tar_filename("pyelftools", pyelftools_dir)
    pyelftools_tar_path = Path(output_dir) / pyelftools_tar_filename

    # Use git archive to create a tarball for the chromite repo. Remove the
    # third_party/pyelftools symlink so we can later copy the contents of the
    # pyelftools repo there.
    cros_build_lib.run(
        ["git", "archive", "--output", chromite_tar_path, "HEAD"],
        cwd=chromite_dir,
    )
    cros_build_lib.run(
        ["tar", "--delete", "-f", chromite_tar_path, "third_party/pyelftools"],
    )

    # Use git archive to create a tarball for the pyelftools repo.
    cros_build_lib.run(
        [
            "git",
            "archive",
            "--prefix=third_party/pyelftools/",
            "--output",
            pyelftools_tar_path,
            "HEAD",
        ],
        cwd=pyelftools_dir,
    )

    # Merge the pyelftools tarball into the Chromite one.
    cros_build_lib.run(
        ["tar", "--concatenate", "-f", chromite_tar_path, pyelftools_tar_path],
    )
    pyelftools_tar_path.unlink()

    # ZSTD-compress the Chromite tarball.
    zstd = compression_lib.find_compressor(compression_lib.CompressionType.ZSTD)
    cros_build_lib.run([zstd, "-9", "--rm", "-f", chromite_tar_path])


def main(argv: Optional[List[str]] = None) -> Optional[int]:
    parser = _get_parser()
    opts = parser.parse_args(argv)

    chromite_dir = opts.chromite_dir
    output_dir = opts.output_dir

    _create_chromite_tarball(chromite_dir, output_dir)
