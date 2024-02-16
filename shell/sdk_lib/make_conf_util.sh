# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Include configuration settings for building private overlay
# packages, if the overlay is present.
# $1 - Path to source checkout as seen from outside.
_make_conf_private() {
  local source_root="$1"

  # If the private overlay dir exists, make sure each sub-piece also exists
  # before we try using it.  Otherwise, simply creating an empty dir will
  # lead to weird build errors.
  local chromeos_overlay="src/private-overlays/chromeos-overlay"

  if [[ -d "${source_root}/${chromeos_overlay}" ]]; then
    local make_conf="${CHROOT_TRUNK_DIR}/src/third_party/chromiumos-overlay"
    make_conf+="/chromeos/config/make.conf.sdk-chromeos"
    echo "source ${make_conf}"
  fi

  local chromeos_partner_overlay="src/private-overlays/chromeos-partner-overlay"

  local overlay
  for overlay in "${chromeos_partner_overlay}" "${chromeos_overlay}"; do
    if [[ -d "${source_root}/${overlay}" ]]; then
      overlay="${CHROOT_TRUNK_DIR}/${overlay}"
      echo "PORTDIR_OVERLAY=\"\$PORTDIR_OVERLAY ${overlay}\""
    fi
  done
}

# Create /etc/make.conf.host_setup according to parameters.
#
# Usage:
# $1 - When outside the chroot, path to the chroot.  Empty when
#      inside the chroot.
# $2 - Path to source checkout as seen from outside.
_create_host_setup() {
  local root="$1"
  local source_root="$2"
  local host_setup="${root}/etc/make.conf.host_setup"
  ( echo "# Automatically generated.  EDIT THIS AND BE SORRY."
    echo
    _make_conf_private "${source_root}"
  ) | sudo_clobber "$host_setup"
  sudo chmod 644 "$host_setup"
}

# Create /etc/make.conf.host_setup for early bootstrapping of the
# chroot.  This is done early in make_chroot, and the results are
# overwritten later in the process.
#
# Usage:
#   $1 - Path to chroot as seen from outside
#   $2 - Path to source checkout as seen from outside
create_bootstrap_host_setup() {
  _create_host_setup "$@"
}


# Create /etc/make.conf.host_setup for normal usage.
create_host_setup() {
  _create_host_setup '' "${CHROOT_TRUNK_DIR}"
}
