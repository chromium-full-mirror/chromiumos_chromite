# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

_make_conf_fetchcommand() {
  local cmd options output_opt resume_opt
  local fileref='\"\${DISTDIR}/\${FILE}\"'
  local uri_ref='\"\${URI}\"'

  cmd=curl
  options="-f -y 30 --retry 9 -L"
  resume_opt="-C -"
  output_opt="--output"

  local args="$options $output_opt $fileref $uri_ref"
  echo FETCHCOMMAND=\"$cmd $args\"
  echo RESUMECOMMAND=\"$cmd $resume_opt $args\"
  echo
}

# The default PORTAGE_BINHOST setting selects the preflight
# binhosts.  We override the setting if the build environment
# requests it.
_make_conf_prebuilt() {
  if [[ -n "$IGNORE_PREFLIGHT_BINHOST" ]]; then
    echo 'PORTAGE_BINHOST="$FULL_BINHOST"'
    echo
  fi
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
    _make_conf_fetchcommand
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
