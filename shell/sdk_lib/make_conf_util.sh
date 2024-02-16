# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# The default PORTAGE_BINHOST setting selects the preflight
# binhosts.  We override the setting if the build environment
# requests it.
_make_conf_prebuilt() {
  if [[ -n "$IGNORE_PREFLIGHT_BINHOST" ]]; then
    echo 'PORTAGE_BINHOST="$FULL_BINHOST"'
    echo
  fi
}

# Include configuration settings for building private overlay
# packages, if the overlay is present.
_make_conf_private() {
  # If the private overlay dir exists, make sure each sub-piece also exists
  # before we try using it.  Otherwise, simply creating an empty dir will
  # lead to weird build errors.
  local chromeos_overlay="src/private-overlays/chromeos-overlay"
  chromeos_overlay="${CHROOT_TRUNK_DIR}/${chromeos_overlay}"

  if [[ -d "${chromeos_overlay}" ]]; then
    local make_conf="${CHROOT_TRUNK_DIR}/src/third_party/chromiumos-overlay"
    make_conf+="/chromeos/config/make.conf.sdk-chromeos"
    echo "source ${make_conf}"
  fi

  local chromeos_partner_overlay="src/private-overlays/chromeos-partner-overlay"
  chromeos_partner_overlay="${CHROOT_TRUNK_DIR}/${chromeos_partner_overlay}"

  local overlay
  for overlay in "${chromeos_partner_overlay}" "${chromeos_overlay}"; do
    if [[ -d "${overlay}" ]]; then
      echo "PORTDIR_OVERLAY=\"\$PORTDIR_OVERLAY ${overlay}\""
    fi
  done
}

# Create /etc/make.conf.host_setup according to parameters.
#
# Usage:
# $1 - When outside the chroot, path to the chroot.  Empty when
#      inside the chroot.
_create_host_setup() {
  local host_setup="$1/etc/make.conf.host_setup"
  ( echo "# Automatically generated.  EDIT THIS AND BE SORRY."
    echo
    _make_conf_private
    _make_conf_prebuilt
    echo 'MAKEOPTS="-j'${NUM_JOBS}'"' ) | sudo_clobber "$host_setup"
  sudo chmod 644 "$host_setup"
}

# Create /etc/make.conf.host_setup for early bootstrapping of the
# chroot.  This is done early in make_chroot, and the results are
# overwritten later in the process.
#
# Usage:
#   $1 - Path to chroot as seen from outside
create_bootstrap_host_setup() {
  _create_host_setup "$@"
}


# Create /etc/make.conf.host_setup for normal usage.
create_host_setup() {
  _create_host_setup ''
}
