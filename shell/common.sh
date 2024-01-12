# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
# shellcheck shell=bash

# This isn't the real common.sh, just a stub to locate it and source it.
# Eventually (at some point in de-shelling), we may want to re-locate the
# real common.sh here for ease of migration.

CHROMITE_DIR="$(realpath "$(dirname "${BASH_SOURCE[0]}")/..")"

find_src_scripts() {
  if [[ -e /etc/cros_chroot_version ]]; then
    # We're inside the SDK.  The path should be fixed.  Use that as it's the
    # most reliable location to find src/scripts.
    echo "/mnt/host/source/src/scripts"
    return
  fi

  local search_dir="${CHROMITE_DIR}"

  while true; do
    search_dir="$(realpath "${search_dir}/..")"
    if [[ "${search_dir}" == "/" ]]; then
      echo "ERR: Unable to locate src/scripts (are you in a cros checkout?)" >&2
      exit 1
    fi

    if [[ -d "${search_dir}/.repo" ]]; then
      echo "${search_dir}/src/scripts"
     return
    fi

    if [[ -d "${search_dir}/.citc" ]]; then
      echo "${search_dir}/chrome-internal/src/scripts"
      return
    fi
  done
}

COMMON_SH="$(find_src_scripts)/common.sh"
# shellcheck source=../../src/scripts/common.sh
source "${COMMON_SH}"
