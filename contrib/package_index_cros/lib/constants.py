# Copyright 2022 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

PACKAGE_ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
PACKAGE_SCRIPTS_DIR = os.path.join(PACKAGE_ROOT_DIR, 'scripts')

PRINT_DEPS_SCRIPT_PATH = os.path.join(PACKAGE_SCRIPTS_DIR, 'print_deps.py')

# Set of packages that should be fine to work with but are not handled properly
# yet.
TEMPORARY_UNSUPPORTED_PACKAGES = {
    # Reason: build dir does not contain out/Debug
    # Is built with Makefile but lists .gn in CROS_WORKON_SUBTREE.
    'chromeos-base/avtest_label_detect',

    # Reason: Fails build because it cannot find src/aosp/external/perfetto.
    # It's a go package that pretends to be an actual package. Should be
    # properly ignored.
    'dev-go/perfetto-protos',

    # TODO(b/308121733): Remove once symlinks are handled correctly.
    "chromeos-base/debugd",

    # Appears to want both llvm-12 and llvm-15 at the same time when printing
    # deps. crbug.com/1501725
    'sys-devel/llvm',
    'sys-libs/llvm-libunwind',
}

# Set of packages that are not currently supported when building.
TEMPORARY_UNSUPPORTED_PACKAGES_WITH_BUILD = {
    # Reason: There are no ebuilds to satisfy
    # ">=dev-lang/python-2.7.5-r2:2.7[threads(+)]".
    # Probably perfectly fine packages otherwise.
    'app-benchmarks/glmark2',
    'chromeos-base/autotest-deps-glmark2',

    # Reason: sys-devel/arc-build fails, but I cannot figure out which package
    # triggers it.
    # Perfectly fine package otherwise.
    'chromeos-base/arc-adbd',
    'chromeos-base/arc-appfuse',
    'chromeos-base/arc-apk-cache',
    'chromeos-base/arc-data-snapshotd',
    'chromeos-base/arc-host-clock-service',
    # A bit strange package with both local sources and aosp url, but should be
    # buildable.
    'chromeos-base/arc-keymaster',
    'chromeos-base/arc-obb-mounter',
    'chromeos-base/arc-sensor-service',
    'chromeos-base/arc-setup',
    'chromeos-base/arcvm-boot-notification-server',
    # Reason: Required 'USE=arcpp' or 'USE=arcvm' fails builds
    # Probably a perfectly fine package otherwise.
    'chromeos-base/arc-base',
    # A bit strange package using files from platform2/vm_tools, but should be
    # buildable.
    'chromeos-base/arcvm-forward-pstore',
    'chromeos-base/arcvm-mojo-proxy',
    # A bit strange package using files from platform2/camera, but should be
    # buildable.
    'media-libs/arc-camera-profile',
    # Package has BUILD.gn and it does something, but there are no cpp sources.
    # If it can be built but has empty compile_commands, there should be no
    # harm, need to be NO_LOCAL_SOURCE otherwise.
    'chromeos-base/arc-sdcard',

    # Reason: Cannot find build or temp dir
    # Probably a perfectly fine package otherwise.
    'chromeos-base/arc-myfiles',
    'chromeos-base/arc-removable-media',
    'chromeos-base/arc-common-scripts',
    'chromeos-base/arcvm-common-scripts',
    'chromeos-base/arcvm-mount-media-dirs',

    # TODO: notify owners.
    # Reason: include path is misspelled vs actual dir: nNCache vs
    # https://source.chromium.org/chromiumos/chromiumos/codesearch/+/main:src/aosp/frameworks/ml/driver/cache/nnCache/
    'chromeos-base/aosp-frameworks-ml-nn',
    'chromeos-base/aosp-frameworks-ml-nn-vts',

    # Target //croslog/log_rotator:_log_rotator-install_config has metadata
    # field which makes merge complicated.
    'chromeos-base/bootid-logger',

    # Reason: Cannot find temp dir
    # Probably a perfectly fine package otherwise.
    'chromeos-base/cdm-oemcrypto',
    'chromeos-base/cdm-oemcrypto-hw-test',

    # Reason: REQUIRED_USE=any-of: test factory_netboot_ramfs factory_shim_ramfs
    # hypervisor_ramfs recovery_ramfs minios_ramfs.
    # Probably a perfectly fine package otherwise.
    'chromeos-base/chromeos-initramfs',

    # Has cryptohome-flatbuffers-binding gn target which has sources field which
    # is almost the same as the target in chromeos-base/cryptohome except that
    # it uses paths generated for this package.
    'chromeos-base/cryptohome-dev-utils',

    # Reason: REQUIRED_USE=fuzzer fails builds.
    # Probably a perfectly fine package otherwise.
    'chromeos-base/cups-fuzz',

    # Reason: Required 'USE=cheets' fails builds.
    # Probably a perfectly fine package otherwise.
    'chromeos-base/demo_mode_resources',

    # Reason: Missing dependency
    # //diagnostics/mojom/public:cros_healthd_mojo_connectivity_bindings
    'chromeos-base/diagnostics-test',

    # Reason: Several missing headers referenced and typos in types.
    'chromeos-base/factory_runtime_probe',

    # Reason: sys-cluster/fcp dependency fails build.
    # Perfectly fine package otherwise.
    'chromeos-base/federated-service',

    # Target //u2fd:webauthntool-install_config has metadata field
    # which makes merge complicated.
    'chromeos-base/g2f_tools',

    # Has lorgnette-proxies gn target which has args field which is almost the
    # same as the target in chromeos-base/lorgnette except for one path.
    'chromeos-base/lorgnette_cli',

    # Reason: Include path ./third_party/libuweave/ does not exist.
    # https://source.chromium.org/chromiumos/chromiumos/codesearch/+/main:src/weave/libweave/BUILD.gn;l=29
    'chromeos-base/libweave',

    # Has libmanatee-client-headers gn target which has args field which is
    # almost the same as the target in chromeos-base/vm_host_tools except for
    # one path and one additional arg.
    'chromeos-base/manatee-client',

    # Reason: REQUIRED_USE="minios" fails build.
    # Perfectly fine package otherwise.
    'chromeos-base/minios',

    # Target //ml:_ml_cmdline-install_config has metadata field which makes
    # merge complicated.
    'chromeos-base/ml-cmdline',

    # Reason: Mismatched proto versions in generated files and referenced
    # library.
    # Probably a perfectly fine package otherwise.
    'chromeos-base/modemfwd',

    # Reason: media_perception_impl.cc:86:13: error: no member named
    # 'AdaptCallbackForRepeating' in namespace 'base'
    'chromeos-base/mri_package',

    # Reason: /etc/init/ocr_service.conf: missing 'oom score' line
    # Perfectly fine package otherwise.
    'chromeos-base/ocr',

    # Reason: Cannot find temp dir
    # Perfectly fine package otherwise.
    'chromeos-base/smogcheck',

    # Reason: REQUIRED_USE="kvm_guest" fails build.
    # Perfectly fine package otherwise.
    'chromeos-base/sommelier',

    # Reason: override-max-pressure-seccomp-amd64.policy does not exist. Only
    # arm. Not sure if it supposed to be compilable under amd64-generic or need
    # another seccomp.
    'chromeos-base/touch_firmware_calibration',

    # Reason: Dependency chromeos-base/vm_guest_tools can't be built due to
    # missing REQUIRED_USE.
    # Probably a perfectly fine package otherwise.
    'chromeos-base/tremplin',

    # Reason: Given path does not exist: /build/hatch/usr/include/u2f/client vs
    # /build/hatch/usr/include/u2f/client
    # Perfectly fine package otherwise.
    'chromeos-base/u2fd',

    # Reason: compilation errors because base::WriteFileDescriptor.
    # Should be solved by using older libchrome or updating the package.
    # Perfectly fine package otherwise.
    'chromeos-base/ureadahead-diff',

    # Reason: Required 'USE=vulkan' fails build
    # Probably a perfectly fine package otherwise.
    'chromeos-base/vkbench',

    # Reason: REQUIRED_USE="kvm_guest" fails build.
    # Perfectly fine package otherwise.
    'chromeos-base/vm_guest_tools',

    # Reason: Lint error, needs a tmpfiles.d configuration.
    # Probably a perfectly fine package otherwise.
    'chromeos-base/webserver',

    # Reason: Require dev-lang/python with USE: +sqlite
    # Probably perfectly fine packages otherwise.
    'chromeos-base/zephyr-build-tools',
    'dev-python/hypothesis',

    # Reason: There are no ebuilds built with USE flags to satisfy
    # "dev-libs/gmp[static-libs]" has to USE: +static-libs
    # Probably a perfectly fine package otherwise.
    'dev-util/shellcheck',

    # Reason: Masked packages for dependency ebuild x11-libs/arc-libdrm are
    # missing keywords
    # Probably a perfectly fine package otherwise.
    'media-libs/arc-mesa-freedreno',
    'media-libs/arc-mesa-virgl',
    'media-libs/arcvm-mesa-freedreno',

    # Reason: Required 'USE=cheets' fails builds
    # Probably a perfectly fine package otherwise.
    'media-libs/arc-mesa-iris',

    # Reason: Several headers can't be found
    # Probably a perfectly fine package otherwise.
    'media-libs/cros-camera-hdrnet-tests',

    # Reason: There are no ebuilds to satisfy "media-libs/libcamera-configs"
    # Probably a perfectly fine package otherwise.
    'media-libs/libcamera',

    # Reason: Requires media-libs/intel-ipu6-camera-bins which is missing.
    # Perfectly fine package otherwise.
    'media-libs/cros-camera-hal-intel-ipu6',

    # Reason: Compilation errors due to some script.
    # Perfectly fine package otherwise.
    'media-libs/cros-camera-libjda_test',

    # Reason: REQUIRED_USE either rockchip or rockchip_v2.
    # Probably a perfectly fine package otherwise.
    'media-libs/libv4lplugins',

    # Reason: Cannot find temp dir
    # Perfectly fine package otherwise.
    'net-print/brother_mlaser',

    # Reason: Multiple package instances within a single package slot have been
    # pulled in
    # Perfectly fine package otherwise.
    'sci-libs/tensorflow',
}

# Set of packages that are not currently supported when building with tests.
TEMPORARY_UNSUPPORTED_PACKAGES_WITH_TESTS = {
    'chromeos-base/screen-capture-utils',
    'chromeos-base/update_engine',
    'chromeos-base/mtpd',
    'net-wireless/floss',
}

# Set of packages failing test run. To be skipped for test run.
PACKAGES_FAILING_TESTS = {
    "chromeos-base/vboot_reference",
    "chromeos-base/chromeos-installer",
    "chromeos-base/chromeos-init",
    "chromeos-base/chromeos-trim",
}
