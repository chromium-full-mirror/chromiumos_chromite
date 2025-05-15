# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Dump all per-file ACLs in a bucket.

gsutil doesn't have a way of dumping ACLs on multiple URIs at once.

NB: You might want to disable metrics due to high overhead:
$ printf DISABLED > ~/.gsutil/analytics-uuid
"""

import functools
import json
import logging
from pathlib import Path
from typing import Optional

from chromite.lib import commandline
from chromite.lib import gs
from chromite.lib import parallel
from chromite.utils import gs_urls_util
from chromite.utils import pformat
from chromite.utils import timer


# Terminal escape sequence to erase the current line after the cursor.
CSI_ERASE_LINE_AFTER = "\x1b[K"


def get_acl_cache(cache_dir: Path, url: str) -> Optional[dict]:
    """Try to read |url|'s cache."""
    cache = cache_dir / url[5:].replace("/", "_")
    try:
        return json.loads(cache.read_bytes())
    except FileNotFoundError:
        return None


def get_acl(ctx: gs.GSContext, cache_dir: Path, url: str) -> str:
    """Get |url|'s ACL."""
    cache = cache_dir / url[5:].replace("/", "_")
    try:
        result = ctx.DoCommand(
            ["acl", "get", "--", url],
            debug_level=logging.DEBUG,
            capture_output=True,
        )
    except gs.GSContextException as e:
        logging.warning("%s: %s", url, e)
        return (url, {})
    data = result.stdout.encode("utf-8")
    cache.write_bytes(data)

    return (url, json.loads(data))


def list_files(ctx: gs.GSContext, url: str, cache: Path) -> list[str]:
    """Enumerate the specified bucket."""
    try:
        urls = cache.read_text(encoding="utf-8").splitlines()
        if urls:
            logging.notice("Using cached listing from %s", cache)
            return urls
    except FileNotFoundError:
        pass

    logging.notice("Enumerating bucket %s", url)
    with timer.timer(f"`gsutil ls ... > {cache.name}`"):
        files = ctx.List(
            f"{url}/**", generation=True, debug_level=logging.DEBUG
        )

    # gsutil can't handle wildcard chars.
    # https://github.com/GoogleCloudPlatform/gsutil/issues/220
    urls = [f"{gs.escape_gsutil_url(x.url)}#{x.generation}" for x in files]
    cache.write_text("".join(f"{x}\n" for x in urls))
    return urls


def get_parser() -> commandline.ArgumentParser:
    """Get CLI parser."""
    parser = commandline.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--working-dir",
        required=True,
        type="dir_exists",
        help="Directory for saving intermediate artifacts",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Number of connections to make in parallel",
    )
    parser.add_argument(
        "bucket",
        help="Which GS bucket to enumerate",
    )
    return parser


def main(argv: Optional[list[str]]) -> Optional[int]:
    """The main entry point for scripts."""
    parser = get_parser()
    opts = parser.parse_args(argv)

    # Validate arguments
    bucket = gs_urls_util.extract_gs_bucket(opts.bucket)
    url_base = f"{gs_urls_util.BASE_GS_URL}{bucket}"

    workdir = opts.working_dir
    log_list = workdir / f"{bucket}.list"
    log_summary = workdir / f"{bucket}.summary"

    # List all the files.
    ctx = gs.GSContext()
    files = list_files(ctx, url_base, log_list)

    # Dump their ACLs.
    num_files = len(files)
    logging.notice("Getting ACLs for %i files", num_files)
    with timer.timer("`gsutil acl get ...`"):
        acls = []
        network_files = []
        for i, file in enumerate(files):
            if (i % 100) == 0:
                print(
                    f"\rChecking cache {i} / {num_files}{CSI_ERASE_LINE_AFTER}",
                    end="",
                )
            acl = get_acl_cache(workdir, file)
            if acl is None:
                network_files.append(file)
            else:
                acls.append((file, acl))
        print(f"\r{CSI_ERASE_LINE_AFTER}", end="", flush=True)

        if network_files:
            logging.notice(
                "Loading ACLs for %i files from the network", len(network_files)
            )
            acls += parallel.RunTasksInProcessPool(
                functools.partial(get_acl, ctx, workdir),
                [[x] for x in network_files],
            )

    # Write a summary of the results.
    logging.notice("Writing out summary")
    with log_summary.open("w", encoding="utf-8") as fp:
        public_read = []
        public_owner = []
        private = []
        for file, acl in sorted(acls, key=lambda x: x[0]):
            if any(
                (
                    x.get("entity") == "allUsers"
                    or x.get("entity") == "allAuthenticatedUsers"
                )
                and x.get("role") == "READER"
                for x in acl
            ):
                public_read.append((file, acl))
            elif any(
                x.get("entity") == "allUsers" and x.get("role") == "OWNER"
                for x in acl
            ):
                public_owner.append((file, acl))
            else:
                private.append((file, acl))

        for header, files in (
            ("Public readable", public_read),
            ("Public owner", public_owner),
            ("Private", private),
        ):
            fp.write(f"### {header} ({len(files)} files)\n\n")
            for file, acl in files:
                fp.write(f"# {file}\n{pformat.json(acl, compact=True)}\n")
            fp.write("\n")
