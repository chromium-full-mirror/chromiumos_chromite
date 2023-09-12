# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Check whether a package links libraries not in RDEPEND.

If no argument is provided it will check all installed packages. It takes the
BOARD environment variable into account.

Example:
    package_hash_missing_deps.py --board=amd64-generic --match \
        chromeos-base/cryptohome
"""

import argparse
import collections
import os
from pathlib import Path
import pprint
import sys
from typing import List, Optional, Set, Union

from chromite.lib import build_target_lib
from chromite.lib import chroot_lib
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import parallel
from chromite.lib import portage_util
from chromite.lib.parser import package_info


VIRTUALS = {
    "virtual/acl": ("sys-apps/acl", "media-libs/img-ddk-bin"),
    "virtual/arc-opengles": (
        "media-libs/arc-img-ddk",
        "media-libs/arc-mesa-img",
        "media-libs/arc-mali-drivers",
        "media-libs/arc-mali-drivers-bifrost",
        "media-libs/arc-mali-drivers-bifrost-bin",
        "media-libs/arc-mali-drivers-valhall",
        "media-libs/arc-mali-drivers-valhall-bin",
        "media-libs/arc-mesa",
        "media-libs/arc-mesa-amd",
        "media-libs/arc-mesa-freedreno",
        "media-libs/arc-mesa-iris",
        "media-libs/arc-mesa-virgl",
        "x11-drivers/opengles-headers",
    ),
    "virtual/cros-camera-hal": (
        "media-libs/cros-camera-hal-intel-ipu3",
        "media-libs/cros-camera-hal-intel-ipu6",
        "media-libs/cros-camera-hal-mtk",
        "media-libs/cros-camera-hal-qti",
        "media-libs/cros-camera-hal-rockchip-isp1",
        "media-libs/cros-camera-hal-usb",
        "media-libs/qti-7c-camera-tuning",
    ),
    "virtual/img-ddk": ("media-libs/img-ddk", "media-libs/img-ddk-bin"),
    "virtual/jpeg": ("media-libs/libjpeg-turbo", "media-libs/jpeg"),
    "virtual/krb5": ("app-crypt/mit-krb5", "app-crypt/heimdal"),
    "virtual/libcrypt": ("sys-libs/libxcrypt",),
    "virtual/libelf": ("dev-libs/elfutils", "sys-freebsd/freebsd-lib"),
    "virtual/libiconv": ("dev-libs/libiconv",),
    "virtual/libintl": ("dev-libs/libintl",),
    "virtual/libudev": (
        "sys-apps/systemd-utils",
        "sys-fs/udev",
        "sys-fs/eudev",
        "sys-apps/systemd",
    ),
    "virtual/libusb": ("dev-libs/libusb", "sys-freebsd/freebsd-lib"),
    "virtual/opengles": (
        "media-libs/img-ddk",
        "media-libs/img-ddk-bin",
        "media-libs/mali-drivers-bin",
        "media-libs/mali-drivers-bifrost",
        "media-libs/mali-drivers-bifrost-bin",
        "media-libs/mali-drivers-valhall",
        "media-libs/mali-drivers-valhall-bin",
        "media-libs/mesa",
        "media-libs/mesa-amd",
        "media-libs/mesa-freedreno",
        "media-libs/mesa-iris",
        "media-libs/mesa-llvmpipe",
        "media-libs/mesa-panfrost",
        "media-libs/mesa-reven",
        "x11-drivers/opengles-headers",
    ),
    "virtual/vulkan-icd": (
        "media-libs/img-ddk",
        "media-libs/img-ddk-bin",
        "media-libs/mali-drivers-bifrost",
        "media-libs/mali-drivers-bifrost-bin",
        "media-libs/mali-drivers-valhall",
        "media-libs/mali-drivers-valhall-bin",
        "media-libs/mesa",
        "media-libs/mesa-freedreno",
        "media-libs/mesa-iris",
        "media-libs/mesa-llvmpipe",
        "media-libs/mesa-radv",
        "media-libs/vulkan-loader",
    ),
}


def env_to_libs(var: str) -> List[str]:
    """Converts value of REQUIRES to a list of .so files.

    For example:
      "arm_32: libRSSupport.so libblasV8.so libc.so ..."
    Becomes:
      ["libRSSupport.so", "libblasV8.so", "libc.so", ...]
    """
    return [x for x in var.split() if not x.endswith(":")]


class DotSoResolver:
    """Provides shared library related dependency operations."""

    def __init__(
        self,
        board: Optional[str] = None,
        root: Union[os.PathLike, str] = "/",
        chroot: Optional[chroot_lib.Chroot] = None,
    ):
        self.board = board
        self.chroot = chroot if chroot else chroot_lib.Chroot()

        self.sdk_db = portage_util.PortageDB()
        self.db = self.sdk_db if root == "/" else portage_util.PortageDB(root)
        self.provided_libs_cache = {}

        # Lazy initialize since it might not be needed.
        self.lib_to_package_map = None

    def get_package(
        self, query: str, from_sdk=False
    ) -> Optional[portage_util.InstalledPackage]:
        """Try to find an InstalledPackage for the provided package string"""
        packages = (self.sdk_db if from_sdk else self.db).InstalledPackages()
        info = package_info.parse(query)
        for package in packages:
            if info.package != package.package:
                continue
            if info.category != package.category:
                continue
            dep_info = package.package_info
            if info.revision and info.revision != dep_info.revision:
                continue
            if info.pv and info.pv != dep_info.pv:
                continue
            return package
        return None

    def get_required_libs(self, package) -> Set[str]:
        """Return a set of required .so files."""
        requires = package.requires
        if requires is not None:
            return set(env_to_libs(package.requires))
        # Fallback to needed if requires is not available.
        aggregate = set()
        needed = package.needed
        if needed is not None:
            for libs in needed.values():
                aggregate.update(libs)
        return aggregate

    def get_deps(self, package) -> List[portage_util.InstalledPackage]:
        """Return a list of dependencies.

        This expands the virtuals listed below.
        """
        cpvr = f"{package.category}/{package.pf}"
        expanded = []
        deps = []
        for dep in portage_util.GetFlattenedDepsForPackage(
            cpvr, board=self.board, depth=1
        ):
            info = package_info.parse(dep)
            if not info:
                continue

            cp = info.cp
            if cp in VIRTUALS:
                expanded += VIRTUALS[cp]
                continue

            pkg = self.db.GetInstalledPackage(info.category, info.pvr)
            if pkg:
                deps.append(pkg)

        for dep in expanded:
            pkg = self.get_package(dep)
            if pkg:
                deps.append(pkg)

        return deps

    def get_implicit_libs(self):
        """Return a set of .so files that are provided by the system."""
        implicit_libs = set()
        for dep, from_sdk in (
            ("cross-aarch64-cros-linux-gnu/glibc", True),
            ("cross-armv7a-cros-linux-gnueabihf/glibc", True),
            ("cross-i686-cros-linux-gnu/glibc", True),
            ("cross-x86_64-cros-linux-gnu/glibc", True),
            ("sys-libs/glibc", False),
            ("sys-libs/libcxx", False),
            ("sys-libs/llvm-libunwind", False),
        ):
            pkg = self.get_package(dep, from_sdk)
            if not pkg:
                continue
            implicit_libs.update(self.provided_libs(pkg))
        return implicit_libs

    def provided_libs(self, package: portage_util.InstalledPackage) -> Set[str]:
        """Return a set of .so files provided by |package|."""
        cpvr = f"{package.category}/{package.pf}"
        if cpvr in self.provided_libs_cache:
            return self.provided_libs_cache[cpvr]

        libs = set()
        contents = package.ListContents()
        # Keep only the .so files
        for typ, path in contents:
            if typ == package.DIR:
                continue
            filename = os.path.basename(path)
            if filename.endswith(".so") or ".so." in filename:
                libs.add(filename)
        self.provided_libs_cache[cpvr] = libs
        return libs

    def cache_libs_from_build(
        self, package: portage_util.InstalledPackage, image_dir: Path
    ):
        """Populate the provided_libs_cache for the package from the image dir.

        When using build-info, CONTENTS might not be available yet. so provide
        alternative using the destination directory of the ebuild.
        """

        cpvr = f"{package.category}/{package.pf}"
        libs = set()
        for _, _, files in os.walk(image_dir):
            for file in files:
                if file.endswith(".so") or ".so." in file:
                    libs.add(os.path.basename(file))
        self.provided_libs_cache[cpvr] = libs

    def get_provided_from_all_deps(
        self, package: portage_util.InstalledPackage
    ) -> Set[str]:
        """Return a set of .so files provided by the immediate dependencies."""
        provided_libs = set()
        # |package| may not actually be installed yet so manually add it to the
        # since a package can depend on its own libs.
        provided_libs.update(self.provided_libs(package))
        for pkg in self.get_deps(package):
            provided_libs.update(self.provided_libs(pkg))
        return provided_libs

    def lib_to_package(self, lib_filename: str = None) -> Set[str]:
        """Return a set of packages that contain the library."""
        if self.lib_to_package_map is None:
            lookup = collections.defaultdict(set)
            for pkg in self.db.InstalledPackages():
                cpvr = f"{pkg.category}/{pkg.pf}"
                # Packages with bundled libs for internal use and/or standaline
                # binary packages.
                if f"{pkg.category}/{pkg.package}" in (
                    "app-emulation/qemu",
                    "chromeos-base/aosp-frameworks-ml-nn-vts",
                    "chromeos-base/factory",
                    "chromeos-base/signingtools-bin",
                    "sys-devel/gcc-bin",
                ):
                    continue
                for lib in set(self.provided_libs(pkg)):
                    lookup[lib].add(cpvr)
            self.lib_to_package_map = lookup
        else:
            lookup = self.lib_to_package_map
        if not lib_filename:
            return set()
        try:
            return lookup[lib_filename]
        except KeyError:
            return set()


def get_parser() -> commandline.ArgumentParser:
    """Build the argument parser."""
    parser = commandline.ArgumentParser(description=__doc__)

    parser.add_argument("package", nargs="*", help="package atom")

    parser.add_argument(
        "-b",
        "--board",
        "--build-target",
        default=cros_build_lib.GetDefaultBoard(),
        help="ChromeOS board (Uses the SDK if not specified)",
    )

    parser.add_argument(
        "-i",
        "--build-info",
        default=None,
        type=Path,
        help="Path to build-info folder post src_install",
    )

    parser.add_argument(
        "-x",
        "--image",
        default=None,
        type=Path,
        help="Path to image folder post src_install (${D} if unspecified)",
    )

    parser.add_argument(
        "--match",
        default=False,
        action="store_true",
        help="Try to match missing libraries",
    )

    parser.add_argument(
        "-j",
        "--jobs",
        default=None,
        type=int,
        help="Number of parallel processes",
    )

    return parser


def parse_arguments(argv: List[str]) -> argparse.Namespace:
    """Parse and validate arguments."""
    parser = get_parser()
    opts = parser.parse_args(argv)
    if opts.build_info and opts.package:
        parser.error("Do not specify a package when setting --board-info")
    if opts.image and not opts.build_info:
        parser.error("--image requires --board-info")
    if opts.build_info or len(opts.package) == 1:
        opts.jobs = 1
    return opts


def check_package(
    package: portage_util.InstalledPackage,
    implicit: Set[str],
    resolver: DotSoResolver,
    match: bool,
    debug: bool,
) -> bool:
    """Returns false if the package has missing dependencies"""
    if not package:
        print("missing package")
        return False

    provided = resolver.get_provided_from_all_deps(package)
    if debug:
        print("provided")
        pprint.pprint(provided)

    available = provided.union(implicit)
    required = resolver.get_required_libs(package)
    if debug:
        print("required")
        pprint.pprint(required)
    unsatisfied = required - available
    if unsatisfied:
        cpvr = package.package_info.cpvr
        print(f"'{cpvr}' missing deps for: ", end="")
        pprint.pprint(unsatisfied)
        if match:
            missing = set()
            for lib in unsatisfied:
                missing.update(resolver.lib_to_package(lib))
            if missing:
                print(f"'{cpvr}' needs: ", end="")
                pprint.pprint(missing)
        return False
    return True


def main(argv: Optional[List[str]]):
    """Main."""
    opts = parse_arguments(argv)
    opts.Freeze()

    board = opts.board
    root = build_target_lib.get_default_sysroot_path(board)
    if board:
        os.environ["PORTAGE_CONFIGROOT"] = root
        os.environ["SYSROOT"] = root
        os.environ["ROOT"] = root

    failed = False
    resolver = DotSoResolver(board, root)

    if not opts.package:
        if opts.build_info:
            pkg = portage_util.InstalledPackage(resolver.db, opts.build_info)
            image_path = opts.image or os.environ.get("D")
            if image_path:
                resolver.cache_libs_from_build(pkg, Path(image_path))
            packages = [pkg]
        else:
            packages = resolver.db.InstalledPackages()
    else:
        packages = [resolver.get_package(p) for p in opts.package]

    implicit = resolver.get_implicit_libs()
    if opts.debug:
        print("implicit")
        pprint.pprint(implicit)

    if opts.jobs == 1:
        for package in packages:
            if not check_package(
                package,
                implicit,
                resolver,
                opts.match,
                opts.debug,
            ):
                failed = True
    else:
        if opts.match:
            # Pre initialize the map before starting jobs.
            resolver.lib_to_package()
        for ret in parallel.RunTasksInProcessPool(
            lambda p: check_package(
                p, implicit, resolver, opts.match, opts.debug
            ),
            [[p] for p in packages],
            opts.jobs,
        ):
            if not ret:
                failed = True

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
