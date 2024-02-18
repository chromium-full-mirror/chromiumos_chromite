# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Script to rebuild Chromite's BUILD.bazel file.

This script recalculates the set of Chromite modules that need to be in
Chromite's BUILD.bazel file and replaces the substitution placeholders in
BUILD.bazel.template with the computed values.

This will stop being needed as soon as Chromite is pinned, since then we'll just
include all files in the pinned repo instead of trying to minimize the set of
files Bazel includes.
"""

import re
import subprocess
from typing import List, Optional

from chromite.utils import file_util


def format_modules_for_build_bazel(modules: List[str]) -> List[str]:
    """Format module filenames to match BUILD.bazel's format."""

    # Insert spaces, quotes, and comma before the newline (if present) to match
    # the format of BUILD.bazel.
    modules = [
        module[:-1] if module.endswith("\n") else module for module in modules
    ]
    return sorted([f'            "{module}",\n' for module in modules])


def generate_content(
    import_lines: List[str], additional_files: List[str]
) -> List[str]:
    """Identify all files for a single pkg_files, and format for BUILD.bazel.

    Identify all files for a single pkg_files, including all modules
    transitively imported from the given list of import plus all files provided
    in the additional files list, and format them for BUILD.bazel.

    Args:
        import_lines: The list of import lines for which to find all
            transitively imported modules.
        additional_files: The list of additional files to include, for the case
            where some files are needed but not referenced by Python imports,
            such as data files.

    Returns:
        The list of formatted filenames to include in BUILD.bazel.
    """

    imports = "; ".join(import_lines)
    py_script = f"{imports}; import sys; print('\\n'.join(\
        module.__file__ for name, module in sys.modules.items()\
        if name.startswith('chromite.') and module.__file__) )"
    with subprocess.Popen(
        f'python3 -c "{py_script}" | sort | sed "s|.*/chromite/\\(.*\\)|\\1|"',
        stdout=subprocess.PIPE,
        shell=True,
        cwd="..",
        encoding="UTF-8",
    ) as p:
        result = format_modules_for_build_bazel(
            list(p.stdout) + additional_files
        )
        return result


def generate_content_for_pkg_file(pkg_file_name: str) -> List[str]:
    """Identify all files for the given pkg_files, and format for BUILD.bazel.

    Identify all files for the given pkg_files name, including all modules
    transitively imported from the given list of import plus all files provided
    in the additional files list, and format them for BUILD.bazel.

    Args:
        pkg_file_name: The name of the pkg_file for which to identify files.

    Returns:
        The list of formatted filenames to include in BUILD.bazel.
    """

    if pkg_file_name == "__cros_generate_coverage_artifacts_files__":
        return generate_content(
            [
                "from chromite.scripts import cros_generate_coverage_artifacts",
            ],
            [
                "scripts/cros_generate_coverage_artifacts",
                "scripts/testdata/test.profdata",
            ],
        )
    elif pkg_file_name == "__licensing_files__":
        return generate_content(
            [
                "from chromite.licensing import ebuild_license_hook",
            ],
            [
                "licensing/ebuild_license_hook",
            ],
        )
    elif pkg_file_name == "__cros_lint_files__":
        return generate_content(
            [
                "from chromite.cli.cros import cros_lint",
                "from chromite.scripts import cros",
            ],
            [
                "bin/cros",
                "bin/cros.py",
                "lint/linters/**",
            ],
        )
    elif pkg_file_name == "__generate_reclient_inputs_files__":
        return generate_content(
            [
                "from chromite.scripts import generate_reclient_inputs",
            ],
            [
                "bin/generate_reclient_inputs",
            ],
        )
    elif pkg_file_name == "__meson_test_files__":
        # We can't import platform2_test.py directly because it has several
        # imports that aren't recognized, so we grep the chromite imports
        # from it and import those directly instead.
        with subprocess.Popen(
            'grep "from chromite\\." \
                src/platform2/common-mk/platform2_test.py',
            stdout=subprocess.PIPE,
            shell=True,
            cwd="..",
            encoding="UTF-8",
        ) as p:
            lines = [
                line[:-1] if line.endswith("\n") else line for line in p.stdout
            ]
            return generate_content(lines, [])
    elif pkg_file_name == "__build_dlc_files__":
        return generate_content(
            [
                "from chromite.scripts import build_dlc",
            ],
            [
                "bin/build_dlc",
            ],
        )
    elif pkg_file_name == "__lddtree_files__":
        return generate_content(
            [
                "from chromite.scripts import lddtree",
            ],
            [
                "bin/lddtree",
            ],
        )

    return []


def replace_placeholders() -> None:
    """Replace the substitution placeholders in BUILD.bazel.template"""
    with file_util.Open("BUILD_template.bazel") as template_file:
        template_lines = template_file.readlines()

        placeholder_regex = re.compile("^ *# Placeholder for (.*?) *$")
        new_content = []
        for line in template_lines:
            match = placeholder_regex.search(line)
            if match:
                pkg_file_name = match.group(1)
                new_content += generate_content_for_pkg_file(pkg_file_name)
            else:
                new_content.append(line)

        with file_util.Open("BUILD.bazel", "w") as build_bazel_file:
            build_bazel_file.writelines(new_content)


def main(_: Optional[List[str]] = None) -> Optional[int]:
    """Main."""
    replace_placeholders()
