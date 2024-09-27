#!/bin/bash
# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

HERE="$(dirname "$0")"
# shellcheck source=common.sh
. "${HERE}/common.sh" || exit 1

if [[ "$1" != "--script-is-run-only-by-chromite-and-not-users" ]]; then
  die_notrace 'This script must not be run by users.' \
    'Please run `update_chroot` instead.'
fi

# Discard the 'script-is-run-only-by-chromite-and-not-users' flag.
shift

DEFINE_boolean usepkg "${FLAGS_TRUE}" \
  "Use binary packages to bootstrap."
DEFINE_integer jobs -1 \
  "How many packages to build in parallel at maximum."
DEFINE_integer backtrack 10 "See emerge --backtrack."

# Parse command line flags
FLAGS "$@" || exit 1
eval set -- "${FLAGS_ARGV}"

# Only now can we die on error.  shflags functions leak non-zero error codes,
# so will die prematurely if 'switch_to_strict_mode' is specified before now.
switch_to_strict_mode

EMERGE_CMD="${CHROMITE_BIN}/parallel_emerge"

EMERGE_FLAGS=( -uNv --backtrack="${FLAGS_backtrack}" )
if [ "${FLAGS_usepkg}" -eq "${FLAGS_TRUE}" ]; then
  EMERGE_FLAGS+=( --getbinpkg )

  # Avoid building toolchain packages or "post-cross" packages from
  # source. The toolchain rollout process only takes place when the
  # chromiumos-sdk builder finishes a successful build.
  PACKAGES=(
    $("${CHROMITE_BIN}/cros_setup_toolchains" --show-packages host)
  )
  # Sanity check we got some valid results.
  [[ ${#PACKAGES[@]} -eq 0 ]] && die_notrace "cros_setup_toolchains failed"
  PACKAGES+=(
    $("${CHROMITE_BIN}/cros_setup_toolchains" --show-packages host-post-cross)
  )
  EMERGE_FLAGS+=(
    $(printf ' --useoldpkg-atoms=%s' "${PACKAGES[@]}")
  )
fi
if [[ "${FLAGS_jobs}" -ne -1 ]]; then
  EMERGE_FLAGS+=( --jobs="${FLAGS_jobs}" )
fi

# Build cros_workon packages when they are changed.
for pkg in $("${CHROMITE_BIN}/cros_list_modified_packages" --host); do
  EMERGE_FLAGS+=( --reinstall-atoms="${pkg}" --usepkg-exclude="${pkg}" )
done

# Second pass, update everything else.
EMERGE_FLAGS+=( --deep )
info_run sudo -E "${EMERGE_CMD}" "${EMERGE_FLAGS[@]}" virtual/target-sdk world

if [ "${FLAGS_usepkg}" -eq "${FLAGS_TRUE}" ]; then
  # Update "post-cross" packages (should only come from binary packages).
  #
  # Use --usepkgonly to ensure that packages are not built from source.
  # Use --with-bdeps=n since we only install binpkgs.
  EMERGE_FLAGS=( -uNv --with-bdeps=n --oneshot --getbinpkg --deep )
  EMERGE_FLAGS+=( --usepkgonly --rebuilt-binaries=n )
  EMERGE_FLAGS+=(
    $("${CHROMITE_BIN}/cros_setup_toolchains" --show-packages host-post-cross)
  )
  info_run sudo -E "${EMERGE_CMD}" "${EMERGE_FLAGS[@]}"
fi
