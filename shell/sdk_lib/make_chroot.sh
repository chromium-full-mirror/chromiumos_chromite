#!/bin/bash

# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

SCRIPT_ROOT=$(readlink -f "$(dirname "$0")/..")
# shellcheck source=../common.sh
. "${SCRIPT_ROOT}/common.sh" || exit 1

# Script must be run outside the chroot and as root.
assert_outside_chroot
assert_root_user

DEFINE_string chroot "$DEFAULT_CHROOT_DIR" \
  "Destination dir for the chroot environment."

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

# shellcheck source=make_conf_util.sh
. "${SCRIPT_ROOT}"/sdk_lib/make_conf_util.sh

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

   # The portage gid is hardcoded to 250.
   chown "${SUDO_USER}:250" "${FLAGS_chroot}/var/cache/chromeos-chrome"

   # TODO(zbehan): Configure stuff that is usually configured in postinst's,
   # but wasn't. Fix the postinst's.
   info "Running post-inst configuration hacks"
   bare_chroot env-update --no-ldconfig
}

# Create a special /etc/make.conf.host_setup that we use to bootstrap
# the chroot.  The regular content for the file will be generated the
# first time we invoke update_chroot (further down in this script).
create_bootstrap_host_setup "${FLAGS_chroot}" "${GCLIENT_ROOT}"

# Run all the init stuff to setup the env.
init_setup

command_completed
