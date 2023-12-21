#!/bin/bash

# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This script sets up a Gentoo chroot environment. The script is passed the
# path to an empty folder, which will be populated with a Gentoo stage3 and
# setup for development. Once created, the password is set to PASSWORD (below).
# One can enter the chrooted environment for work by running enter_chroot.sh.

SCRIPT_ROOT=$(readlink -f "$(dirname "$0")/..")
# shellcheck source=../common.sh
. "${SCRIPT_ROOT}/common.sh" || exit 1

ENTER_CHROOT=$(readlink -f "$(dirname "$0")/enter_chroot.sh")

# Check if the host machine architecture is supported.
ARCHITECTURE="$(uname -m)"
if [[ "$ARCHITECTURE" != "x86_64" ]]; then
  echo "$SCRIPT_NAME: $ARCHITECTURE is not supported as a host machine architecture."
  exit 1
fi

# Script must be run outside the chroot and as root.
assert_outside_chroot
assert_root_user

# Define command line flags.
# See http://code.google.com/p/shflags/wiki/Documentation10x

DEFINE_string chroot "$DEFAULT_CHROOT_DIR" \
  "Destination dir for the chroot environment."
DEFINE_string out_dir "${DEFAULT_OUT_DIR}" \
  "The destination dir for build output and state."
DEFINE_string cache_dir "" "Directory to store caches within."

# Parse command line flags.
FLAGS_HELP="usage: $SCRIPT_NAME [flags]"
FLAGS "$@" || exit 1
eval set -- "${FLAGS_ARGV}"

CROS_LOG_PREFIX=cros_sdk:make_chroot

# Set the right umask for chroot creation.
umask 022

# Only now can we die on error.  shflags functions leak non-zero error codes,
# so will die prematurely if 'switch_to_strict_mode' is specified before now.
# TODO: replace shflags with something less error-prone, or contribute a fix.
switch_to_strict_mode

[[ -z "${FLAGS_cache_dir}" ]] && die "--cache_dir is required"

# shellcheck source=make_conf_util.sh
. "${SCRIPT_ROOT}"/sdk_lib/make_conf_util.sh

ENTER_CHROOT_ARGS=(
  CROS_WORKON_SRCROOT="${CHROOT_TRUNK_DIR}"
  PORTAGE_USERNAME="${SUDO_USER}"
  IGNORE_PREFLIGHT_BINHOST="$IGNORE_PREFLIGHT_BINHOST"
)

# Invoke enter_chroot.  This can only be used after sudo has been installed.
enter_chroot() {
  echo "$(date +%H:%M:%S) [enter_chroot] $*"
  "${ENTER_CHROOT}" --cache_dir "${FLAGS_cache_dir}" --chroot \
    "${FLAGS_chroot}" --out_dir "${FLAGS_out_dir}" --nopivot_root -- \
    "${ENTER_CHROOT_ARGS[@]}" "$@"
}

# Invoke enter_chroot running the command as root, and w/out sudo.
# This should be used prior to sudo being merged.
early_env=()
early_enter_chroot() {
  echo "$(date +%H:%M:%S) [early_enter_chroot] $*"
  "${ENTER_CHROOT}" --chroot "${FLAGS_chroot}" \
    --out_dir "${FLAGS_out_dir}" --early_make_chroot \
    --cache_dir "${FLAGS_cache_dir}" --nopivot_root \
    -- "${ENTER_CHROOT_ARGS[@]}" "${early_env[@]}" "$@"
}

# Run a command within the chroot.  The main usage of this is to avoid the
# overhead of enter_chroot.  It's when we do not need access to the source
# tree, don't need the actual chroot profile env, and can run the command as
# root.  We do have to make sure PATH includes all the right programs as
# found inside of the chroot since the environment outside of the chroot
# might be insufficient (like distros with merged /bin /sbin and /usr).
bare_chroot() {
  PATH="/bin:/sbin:/usr/bin:/usr/sbin:${PATH}" \
    chroot "${FLAGS_chroot}" "$@"
}

init_setup () {
   info "Running init_setup()..."

   # Use the standardized upgrade script to setup proxied vars.
   load_environment_whitelist
   "${SCRIPT_ROOT}/sdk_lib/rewrite-sudoers.d.sh" \
     "${FLAGS_chroot}" "${SUDO_USER}" "${ENVIRONMENT_WHITELIST[@]}"

   find "${FLAGS_chroot}/etc/"sudoers* -type f -exec chmod 0440 {} +
   # Fix bad group for some.
   chown -R root:root "${FLAGS_chroot}/etc/"sudoers*

   # Create directories referred to by our conf files.
   echo "export CHROMEOS_CACHEDIR=/var/cache/chromeos-cache" > \
     "${FLAGS_chroot}/etc/profile.d/chromeos-cachedir.sh"
   chmod 0644 "${FLAGS_chroot}/etc/profile.d/chromeos-cachedir.sh"

   # Run this from w/in the chroot so we use whatever uid/gid
   # these are defined as w/in the chroot.
   bare_chroot chown "${SUDO_USER}:portage" /var/cache/chromeos-chrome

   # TODO(zbehan): Configure stuff that is usually configured in postinst's,
   # but wasn't. Fix the postinst's.
   info "Running post-inst configuration hacks"
   early_enter_chroot env-update
}

# Pass proxy variables into the environment.
for type in http ftp all; do
   value=$(env | grep "${type}_proxy" || true)
   if [ -n "${value}" ]; then
      CHROOT_PASSTHRU+=("$value")
   fi
done

# Create a special /etc/make.conf.host_setup that we use to bootstrap
# the chroot.  The regular content for the file will be generated the
# first time we invoke update_chroot (further down in this script).
create_bootstrap_host_setup "${FLAGS_chroot}"

# Run all the init stuff to setup the env.
init_setup

# The java-config package atm does not support $ROOT.  Select a default
# VM ourselves until that gets fixed upstream.
enter_chroot sudo eselect java-vm set system openjdk-bin-11

command_completed
