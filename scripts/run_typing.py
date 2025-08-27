# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite type checker.

Run the chromite Python codebase through the mypy type checker.
"""

import dataclasses
import logging
import os
from typing import Iterator, Optional

from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib


# These files we haven't cleaned up yet.  We filter entire files to avoid having
# to update the baseline when bad lines move around.
KNOWN_ISSUES = (
    # go/keep-sorted start
    "api/api_config.py",
    "api/gen_test/go/chromium/org/luci/vpython/api/vpython/pep425_pb2.py",
    "api/gen_test/go/chromium/org/luci/vpython/api/vpython/spec_pb2.py",
    "cli/cros/lint.py",
    "cli/cros/lint_unittest.py",
    "cli/deploy.py",
    "cli/deploy_unittest.py",
    "contrib/codemod/auto_type_dunders.py",
    "contrib/codemod/auto_type_none.py",
    "contrib/depgraph_visualization/depgraph_visualization/visualize.py",
    "contrib/depgraph_visualization/setup.py",
    "contrib/fwgdb.py",
    "contrib/gob-meta-config-checkout.py",
    "contrib/libcst_tool.py",
    "cros/test/image_test.py",
    "cros/test/usergroup_baseline.py",
    "format/formatters/json.py",
    "format/formatters/repo_manifest.py",
    "format/formatters/xml.py",
    "ide_tooling/scripts/compdb_no_chroot.py",
    "ide_tooling/scripts/compdb_no_chroot_unittest.py",
    "ide_tooling/scripts/detect_indent.py",
    "ide_tooling/scripts/detect_indent_unittest.py",
    "lib/build_requests.py",
    "lib/buildbot_annotations.py",
    "lib/cidb.py",
    "lib/cidb_unittest.py",
    "lib/constants.py",
    "lib/depgraph.py",
    "lib/dlc_allowlist.py",
    "lib/factory.py",
    "lib/failure_message_lib.py",
    "lib/filetype.py",
    "lib/firmware/ap_firmware_config/__init__.py",
    "lib/gmerge_binhost.py",
    "lib/gs.py",
    "lib/image_test_lib.py",
    "lib/kernel_cmdline.py",
    "lib/luci/test_support/auto_stub.py",
    "lib/terminal.py",
    "lint/linters/make_defaults.py",
    "lint/linters/make_defaults_unittest.py",
    "lint/linters/upstart.py",
    "lint/linters/whitespace.py",
    "scripts/autotest_quickmerge.py",
    "scripts/autotest_quickmerge_unittest.py",
    "scripts/cros_setup_toolchains.py",
    "scripts/gconv_strip.py",
    "scripts/run_tests.py",
    "scripts/virtualenv_wrapper.py",
    "scripts/vpython_consistency_unittest.py",
    "scripts/vpython_wrapper.py",
    "service/dependency.py",
    "test/portage_testables_unittest.py",
    "utils/code_coverage_util.py",
    "utils/field_mask_util.py",
    "utils/os_util_unittest.py",
    "utils/parser/ebuild_license_unittest.py",
    "utils/parser/pms_dependency.py",
    "utils/parser/portage_md5_cache.py",
    "utils/parser/upstart.py",
    "utils/prctl_unittest.py",
    "utils/shell_util.py",
    "utils/telemetry/utils_unittest.py",
    "utils/xdg_util.py",
    "utils/xdg_util_unittest.py",
    # go/keep-sorted end
)


@dataclasses.dataclass(frozen=True)
class Report:
    """A single report."""

    file: str
    line: int
    severity: str
    message: str

    def __str__(self) -> str:
        """Mimic the mypy output."""
        return f"{self.file}:{self.line}: {self.severity}:{self.message}"

    def __lt__(self, other: "Report") -> bool:
        """Basic compare logic to sort results."""
        if self.file == other.file:
            return self.line < other.line
        else:
            return self.file < other.file


def parse_output(output: str) -> Iterator[Report]:
    """Parse the output into structured results."""
    lines = output.splitlines()
    if lines[-1].startswith("Found "):
        lines.pop()

    # Our current version of mypy produces output like:
    #   file.py:88: error: msg
    # Newer versions can produce JSON like:
    #   {"file": "file.py", "line": 88, "severity": "error", "message": "msg"}
    # Once we upgrade to mypy 1.11+, we can switch to the --output=json format
    # instead of parsing ourselves.  Until then, the Report object fields use
    # the same naming conventions as the newer JSON output so it's easier to
    # switch one day.
    for line in lines:
        ele = line.split(":", 3)
        if len(ele) != 4:
            logging.warning("Unknown output: %s", line)
            continue

        yield Report(
            file=ele[0],
            line=int(ele[1]),
            severity=ele[2].strip(),
            message=ele[3],
        )


def sort_results(output: str) -> Iterator[str]:
    """Sort the results by file."""
    blocks = []
    block = []
    file = None
    for report in parse_output(output):
        if file != report.file:
            if block:
                blocks.append(block)
                block = []
            file = report.file
        block.append(report)

    blocks.append(block)
    blocks.sort()
    for block in blocks:
        yield from block


def get_parser() -> commandline.ArgumentParser:
    """Build the parser for command line arguments."""
    parser = commandline.ArgumentParser(
        description=__doc__, default_log_level="notice"
    )
    parser.add_bool_argument(
        "--relaxed",
        True,
        "Ignore known issues in the codebase.",
        "Fail on all errors.",
    )
    parser.add_argument(
        "args",
        metavar="tool arguments",
        nargs="*",
        help="Arguments to pass to the type checker (use -- to help separate)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> Optional[int]:
    parser = get_parser()
    opts = parser.parse_args(argv)
    opts.Freeze()

    # Hacky heuristic to see if a path was specified.  If not, use chromite.
    paths = []
    for arg in opts.args:
        if arg.startswith("-"):
            break
        paths.append(arg)
    if not paths:
        paths = [os.path.relpath(constants.CHROMITE_DIR)]
    else:
        paths.clear()

    # Run the tool, parse its output, sort it, then show it.
    # NB: It's important that we capture the output and post-process before we
    # print it out.  This is because scripts/run_tests.py runs us in parallel
    # and sends our output to a pipe.  If we filled the pipe, we'd block, and
    # we'd slow it down overall.  That could be fixed in run_tests to write the
    # output to a tempfile, but we also workaround it here by post-processing.
    result = cros_build_lib.run(
        [constants.CHROMITE_SCRIPTS_DIR / "mypy"] + opts.args + paths,
        check=False,
        encoding="utf-8",
        stdout=True,
    )
    relaxed_returncode = 0
    for report in sort_results(result.stdout):
        new_problem = (
            report.file not in KNOWN_ISSUES and report.severity != "note"
        )
        if new_problem:
            relaxed_returncode = 1
        print(
            str(report),
            "[chromite/NEW ERROR]" if new_problem else "[chromite/ignoring KI]",
        )
    return relaxed_returncode if opts.relaxed else result.returncode
