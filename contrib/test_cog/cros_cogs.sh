#!/bin/bash
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Save the current working directory, so that we can restore it later just
# before executing the final command inside the sandbox.
CB_PWD="${CB_PWD:-$(pwd)}"

# Create a new workspace name, with a suffix of 6 random hex chars.
generate_workspace_unique_name() {
  echo "cros-cog-test-$(date +%s)-$(echo "${RANDOM}" | md5sum | head -c 6)"
}

# Find and change the current working directory into the root of the Cog
# workspace.
goto_cog_root() {
  # Check if we're at the root of a Cog workspace now.
  if [[ -d .citc ]]; then
      return 0
  fi

  # Not there yet, go one up and retry.
  # Abort if can't go up any further.
  cd ..
  if [[ $(pwd) = "/" ]]; then
      echo "Could not find root directory of Cog workspace"
      return 1
  fi

  goto_cog_root
}

# Mount a workspace.
# Takes one argument, the workspace name.
# Returns the mountpoint path.
mount_workspace() {
  local workspace_name
  workspace_name=$1

  # Mount overlayfs on top of the Cog workspace
  upper_dir="${HOME}/.cogs/${workspace_name}/upper"
  work_dir="${HOME}/.cogs/${workspace_name}/workdir"
  mountpoint="${HOME}/.cogs/${workspace_name}/mount"

  mkdir -p "${upper_dir}" "${work_dir}" "${mountpoint}"

  sudo mount \
      -t overlay \
      overlay \
      -o userxattr,lowerdir="${workspace_name}",upperdir="${upper_dir}",\
workdir="${work_dir}" "${mountpoint}"
  echo "${mountpoint}"
}
