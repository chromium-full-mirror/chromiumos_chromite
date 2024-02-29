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
DEFINE_boolean skip_toolchain_update "${FLAGS_FALSE}" \
  "Don't update the toolchains."
DEFINE_string toolchain_boards "" \
  "Extra toolchains to setup for the specified boards."
DEFINE_boolean eclean "${FLAGS_TRUE}" "Run eclean to delete old binpkgs."
DEFINE_integer backtrack 10 "See emerge --backtrack."

# Parse command line flags
FLAGS "$@" || exit 1
eval set -- "${FLAGS_ARGV}"

# Only now can we die on error.  shflags functions leak non-zero error codes,
# so will die prematurely if 'switch_to_strict_mode' is specified before now.
switch_to_strict_mode

# First update the cross-compilers.
# Note that this uses binpkgs only, unless we pass --nousepkg below.
if [ "${FLAGS_skip_toolchain_update}" -eq "${FLAGS_FALSE}" ]; then
  info "Updating cross-compilers"
  TOOLCHAIN_FLAGS=()

  if [[ -n ${FLAGS_toolchain_boards} ]]; then
    TOOLCHAIN_FLAGS+=(
      "--include-boards=${FLAGS_toolchain_boards}"
    )
  fi

  # This should really only be skipped while bootstrapping.
  if [ "${FLAGS_usepkg}" -eq "${FLAGS_FALSE}" ]; then
    TOOLCHAIN_FLAGS+=( --nousepkg )
  fi
  # Expand the path before sudo, as root doesn't have the same path magic.
  info_run sudo -E "$(type -p cros_setup_toolchains)" "${TOOLCHAIN_FLAGS[@]}"
fi

EMERGE_CMD="${CHROMITE_BIN}/parallel_emerge"

# Clean out any stale binpkgs we've accumulated. This is done immediately after
# regenerating the cache in case ebuilds have been removed (e.g. from a revert).
if [[ "${FLAGS_eclean}" -eq "${FLAGS_TRUE}" ]]; then
  info "Cleaning stale binpkgs"
  get_eclean_exclusions | sudo eclean -e /dev/stdin packages
fi

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
  # Update "post-cross"  and "nobdeps" packages. Both should only come from
  # binary packages.
  #
  # Use --usepkgonly to ensure that packages are not built from source.
  # Use --with-bdeps=n since we only install binpkgs.
  EMERGE_FLAGS=( -uNv --with-bdeps=n --oneshot --getbinpkg --deep )
  EMERGE_FLAGS+=( --usepkgonly --rebuilt-binaries=n )
  EMERGE_FLAGS+=(
    $("${CHROMITE_BIN}/cros_setup_toolchains" --show-packages host-post-cross)
  )
  EMERGE_FLAGS+=( virtual/target-sdk-nobdeps )
  info_run sudo -E "${EMERGE_CMD}" "${EMERGE_FLAGS[@]}"
fi

# Automatically discard all CONFIG_PROTECT'ed files. Those that are
# protected should not be overwritten until the variable is changed.
# Autodiscard is option "-9" followed by the "YES" confirmation.
printf '%s\nYES\n' -9 | sudo etc-update

# If the user still has old perl modules installed, update them.
"${SCRIPTS_DIR}/build_library/perl_rebuild.sh"

# Deep clean any stale binpkgs. This includes any binary packages that do not
# correspond to a currently installed package (different versions are kept).
if [[ "${FLAGS_eclean}" -eq "${FLAGS_TRUE}" ]]; then
  info "Deep cleaning stale binpkgs"
  get_eclean_exclusions | sudo eclean -e /dev/stdin -d packages
fi
