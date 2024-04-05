#!/bin/bash
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Ensure that chromite/bin is at the head of ${PATH}, in front of the paths set
# by /etc/profile, to ensure that we use `bazel` from chromite/bin rather than
# the one from /usr/bin.
PATH=/mnt/host/source/chromite/bin:${PATH}

# Niceties for interactive logins. (cr) denotes this is a chroot.
PS1="(cr) ${PS1}"

# Warn the user when it's time to exit the chroot.
# When the SDK version is different than the one in their tree, they should exit
# their SDK shell and re-enter to update.
_cros_prompt_command() {
  # Execute in a subshell in order to not leak variables.
  (
    : "${CROS_WORKON_SRCROOT:=/mnt/host/source}"
    chromiumos="${CROS_WORKON_SRCROOT}/src/third_party/chromiumos-overlay"
    # shellcheck disable=SC1091
    source "${chromiumos}/chromeos/binhost/host/sdk_version.conf"
    source /etc/os-release

    if [[ "${SDK_LATEST_VERSION:?}" != "${BUILD_ID:?}" ]]; then
      echo -e "\x1b[31;1mWARNING: Your current SDK version (${BUILD_ID:?})" \
           "is not the latest version (${SDK_LATEST_VERSION:?}).  Please" \
           "exit your SDK shell and re-enter.\x1b[0m"
    fi
  )
}
PROMPT_COMMAND="_cros_prompt_command"
