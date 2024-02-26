#!/bin/bash
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e

: "${REAL_SCRIPT:=$(readlink -f -- "$0")}"
: "${SCRIPT_LOCATION:=$(dirname "${REAL_SCRIPT}")}"

cd "${SCRIPT_LOCATION}" || exit 1

# Some chroot upgrade hooks symlink & run us as non-root.
if [[ $# -eq 0 ]]; then
  # shellcheck source=../common.sh
  . "../common.sh" || exit 1

  assert_inside_chroot
  load_environment_whitelist

  set -- / "${USER}" "${ENVIRONMENT_WHITELIST[@]}"
  echo "Rewriting with env list ${*:3}"

  if [[ "${UID:-$(id -u)}" != 0 ]]; then
    # Note that since we're screwing w/ sudo variables, this script
    # explicitly bounces up to root for everything it does- that way
    # if anyone introduces a temp depriving in the sudo setup, it can't break
    # mid upgrade.

    exec sudo bash "${REAL_SCRIPT}" "$@"
  fi
fi

# Reaching here means we have access to the path.

root=$1
username=$2
shift 2

file="${root}/etc/sudoers.d/90_cros"
rm -f "${file}"
mkdir -p "${file%/*}"
cat > "${file}" <<EOF
Defaults env_keep += "$*"

# adm lets users & ebuilds run sudo (e.g. platform2 sysroot test runners).
%adm ALL=(ALL) NOPASSWD: ALL
${username} ALL=(ALL) NOPASSWD: ALL

# Simplify the -v option checks due to overlap of the adm group and the user's
# supplementary groups.  We don't set any passwords, so disable asking.
# https://crbug.com/762445
Defaults verifypw = any
EOF

chmod 0644 "${file}"
# NB: No need to chown as we we're running as root.
