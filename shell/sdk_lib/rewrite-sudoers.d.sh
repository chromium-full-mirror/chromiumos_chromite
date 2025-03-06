#!/bin/bash
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

set -e

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
