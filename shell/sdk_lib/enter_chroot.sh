#!/bin/bash

# Copyright 2011 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# Script to enter the chroot environment

SCRIPT_ROOT=$(readlink -f "$(dirname "$0")"/..)
# shellcheck source=../common.sh
. "${SCRIPT_ROOT}/common.sh" || exit 1

: "${SUDO_USER:=${USER}}"

# Script must be run outside the chroot and as root.
assert_outside_chroot
assert_root_user

# Define command line flags
# See http://code.google.com/p/shflags/wiki/Documentation10x
# shellcheck disable=SC2154 # Is used under FLAGS_<name>
DEFINE_string chroot "${DEFAULT_CHROOT_DIR}" \
  "The destination dir for the chroot environment." "d"
# shellcheck disable=SC2154 # Mostly here for plumbing. Not used.
DEFINE_string trunk "${GCLIENT_ROOT}" \
  "The source trunk to bind mount within the chroot." "s"
DEFINE_string chrome_root "" \
  "The root of your chrome browser source. Should contain a 'src' subdir."
DEFINE_string chrome_root_mount "/home/${SUDO_USER}/chrome_root" \
  "The mount point of the chrome broswer source in the chroot."
DEFINE_boolean verbose "${FLAGS_FALSE}" "Print out actions taken"

# shellcheck disable=SC2034
CROS_LOG_PREFIX=cros_sdk:enter_chroot
SUDO_HOME=$(eval echo "~${SUDO_USER}")

# Version of info from common.sh that only echos if --verbose is set.
debug() {
  if [[ "${FLAGS_verbose}" -eq "${FLAGS_TRUE}" ]]; then
    info "$*"
  fi
}

# Parse command line flags
FLAGS "$@" || exit 1
eval set -- "${FLAGS_ARGV}"

# Only now can we die on error.  shflags functions leak non-zero error codes,
# so will die prematurely if 'switch_to_strict_mode' is specified before now.
# TODO: replace shflags with something less error-prone, or contribute a fix.
switch_to_strict_mode

INNER_CHROME_ROOT=${FLAGS_chrome_root_mount}  # inside chroot
CHROME_ROOT_CONFIG="/var/cache/chrome_root"   # inside chroot

# We can't use /var/lock because that might be a symlink to /run/lock outside
# of the chroot.  Or /run on the host system might not exist.
LOCKFILE="${FLAGS_chroot}/.enter_chroot.lock"
MOUNTED_PATH=$(readlink -f "${FLAGS_chroot}")

# Copies the specified file owned by the user to the specified location.
# If the copy fails as root (e.g. due to root_squash and NFS), retry the copy
# with the user's account before failing.
user_cp() {
  cp -p "$@" 2>/dev/null || sudo -u "${SUDO_USER}" -- cp -p "$@"
}

# Create the specified directory, along with parents, as the sudo user.
#
# $@ - The directories to create.
user_mkdir() {
  install -o "${SUDO_UID}" -g "${SUDO_GID}" -d "$@"
}

# Return 0 if $1 is mounted read-only.
mount_is_ro() {
  awk -v mount="$1" '
    $5 == mount && ","$6"," ~ /,ro,/ { exit 1 }
  ' /proc/self/mountinfo && return 1 || return 0
}

setup_mount() {
  # If necessary, mount $source in the host FS at $target inside the
  # chroot directory with $mount_args. We don't write to /etc/mtab because
  # these mounts are all contained within an unshare and are therefore
  # inaccessible to other namespaces (e.g. the host desktop system).
  local source="$1"
  local target="$2"
  shift 2
  local mount_args=( -n )
  if [[ $# -gt 0 ]]; then
    mount_args+=( "$@" )
  else
    mount_args+=( --bind )
  fi

  local mounted_path="${MOUNTED_PATH}${target}"

  case " ${MOUNT_CACHE} " in
  *" ${mounted_path} "*)
    # Already mounted!
    ;;
  *)
    # Don't blindly mkdir in case they're trying to bind mount a file.
    if [[ ! -e "${mounted_path}" ]]; then
      if [[ -d "${source}" ]]; then
        mkdir -p "${mounted_path}"
      elif [[ -f "${source}" ]]; then
        mkdir -p "$(dirname "${mounted_path}")"
        touch "${mounted_path}"
      fi
    fi
    # The args are left unquoted on purpose.
    if [[ -n "${source}" ]]; then
      mount "${mount_args[@]}" "${source}" "${mounted_path}"
    else
      mount "${mount_args[@]}" "${mounted_path}"
    fi
    ;;
  esac
}

copy_into_chroot_if_exists() {
  # $1 is file path outside of chroot to copy to path $2 inside chroot.
  if [[ -e "$1" ]]; then
    local dir
    dir=$(dirname "${FLAGS_chroot}/$2")
    if [[ ! -d "${dir}" ]]; then
      user_mkdir "${dir}"
    fi
    user_cp "$1" "${FLAGS_chroot}/$2"
  fi
}

git_config() {
  USER="${SUDO_USER:-${USER}}" \
  HOME="${SUDO_HOME:-${HOME}}" \
  git config "$@"
}

# The --type=path option is new to git-2.18 and not everyone upgrades.
# But not everyone uses the ~ prefix, so try that option if needed.
git_config_path() {
  local out
  out=$(git_config "$@")
  if [[ "${out:0:1}" == "~" ]]; then
    git_config --type path "$@"
  else
    echo "${out}"
  fi
}

setup_git() {
  # Copy .gitconfig into chroot so repo and git can be used from inside.
  # This is required for repo to work since it validates the email address.
  copy_into_chroot_if_exists "${SUDO_HOME}/.gitconfig" \
      "/home/${SUDO_USER}/.gitconfig"
  local -r chroot_gitconfig="${FLAGS_chroot}/home/${SUDO_USER}/.gitconfig"

  # If the user didn't set up their username in their gitconfig, look
  # at the default git settings for the user.
  if ! git config -f "${chroot_gitconfig}" user.email >& /dev/null; then
    local ident
    ident=$(cd /; sudo -u "${SUDO_USER}" -- git var GIT_COMMITTER_IDENT || :)
    local ident_name=${ident%% <*}
    local ident_email=${ident%%>*}; ident_email=${ident_email##*<}
    git config -f "${chroot_gitconfig}" --replace-all user.name \
        "${ident_name}" || :
    git config -f "${chroot_gitconfig}" --replace-all user.email \
        "${ident_email}" || :
  fi

  # Copy the gitcookies file, updating the user's gitconfig to point to it.
  local gitcookies
  if ! gitcookies="$(git_config_path --file "${chroot_gitconfig}" \
                     --get http.cookiefile)"; then
    # Try the default location anyway.
    gitcookies="${SUDO_HOME}/.gitcookies"
  fi
  copy_into_chroot_if_exists "${gitcookies}" "/home/${SUDO_USER}/.gitcookies"
  local -r chroot_gitcookies="${FLAGS_chroot}/home/${SUDO_USER}/.gitcookies"
  if [[ -e "${chroot_gitcookies}" ]]; then
    git config -f "${chroot_gitconfig}" --replace-all http.cookiefile \
        "/home/${SUDO_USER}/.gitcookies"
  fi
  # This line must be at the end because using `git config` changes ownership of
  # the .gitconfig.
  chown "${SUDO_UID}:${SUDO_GID}" "${chroot_gitconfig}"
}

setup_gclient_cache_dir_mount() {
  # Mount "cache_dir" if a glient checkout depends on it.
  # Otherwise, git command inside chroot fails. See https://crbug.com/747349
  local checkout_root="$1"

  if [[ ! -e "${checkout_root}/.gclient" ]]; then
    return 0
  fi

  local cache_dir
  cache_dir=$(sed -n -E "s/^ *cache_dir *= *'(.*)'/\1/p" \
              "${checkout_root}/.gclient")
  if [[ -z "${cache_dir}" ]]; then
    return 0
  fi

  # See if the cache dir exists outside of the chroot.
  if [[ ! -d "${cache_dir}" ]]; then
    # See if it exists inside the chroot (which can happen if the checkout was
    # created in there).
    if [[ ! -d "${FLAGS_chroot}/${cache_dir}" ]]; then
      warn "Gclient cache dir \"${cache_dir}\" is not a directory."
    fi
    return 0
  fi

  setup_mount "${cache_dir}" "${cache_dir}"
}

setup_env() {
  # shellcheck disable=SC2094
  (
    flock 200

    # Make the lockfile writable for backwards compatibility.
    chown "${SUDO_UID}:${SUDO_GID}" "${LOCKFILE}"

    debug "Mounting chroot environment."
    mapfile -t MOUNT_CACHE < <(awk '{print $2}' /proc/mounts)

    debug "Setting up referenced repositories if required."
    REFERENCE_DIR=$(git_config_path --file  \
      "${FLAGS_trunk}/.repo/manifests.git/config" \
      repo.reference)
    if [ -n "${REFERENCE_DIR}" ]; then

      ALTERNATES="${FLAGS_trunk}/.repo/alternates"

      # Ensure this directory exists ourselves, and has the correct ownership.
      user_mkdir "${ALTERNATES}"

      unset ALTERNATES

      mapfile -t required < <( sudo -u "${SUDO_USER}" -- \
        "${FLAGS_trunk}/chromite/lib/rewrite_git_alternates" \
        "${FLAGS_trunk}" "${REFERENCE_DIR}" "${CHROOT_TRUNK_DIR}" )

      setup_mount "${FLAGS_trunk}/.repo/chroot/alternates" \
        "${CHROOT_TRUNK_DIR}/.repo/alternates"

      # Note that as we're bringing up each referened repo, we also
      # mount bind an empty directory over its alternates.  This is
      # required to suppress git from tracing through it- we already
      # specify the required alternates for CHROOT_TRUNK_DIR, no point
      # in having git try recursing through each on their own.
      #
      # Finally note that if you're unfamiliar w/ chroot/vfs semantics,
      # the bind is visible only w/in the chroot.
      user_mkdir "${FLAGS_trunk}/.repo/chroot/empty"
      position=1
      for x in "${required[@]}"; do
        base="${CHROOT_TRUNK_DIR}/.repo/chroot/external${position}"
        setup_mount "${x}" "${base}"
        if [ -e "${x}/.repo/alternates" ]; then
          setup_mount "${FLAGS_trunk}/.repo/chroot/empty" \
            "${base}/.repo/alternates"
        fi
        position=$(( position + 1 ))
      done
      unset required position base
    fi
    unset REFERENCE_DIR

    # Mount additional directories as specified in .local_mounts file.
    local local_mounts="${FLAGS_trunk}/src/scripts/.local_mounts"
    if [[ -f "${local_mounts}" ]]; then
      debug "Mounting local folders"
      # format: mount_source
      #      or mount_source mount_point
      #      or # comments
      local mount_source mount_point
      while read -r mount_source mount_point; do
        if [[ -z "${mount_source}" ]]; then
          continue
        fi
        # if only source is assigned, use source as mount point.
        : "${mount_point:=${mount_source}}"
        debug "  mounting ${mount_source} on ${mount_point}"
        setup_mount "${mount_source}" "${mount_point}"
      done < <(sed -e 's:#.*::' "${local_mounts}" | xargs -0)
    fi

    if [[ -n "${FLAGS_chrome_root}" ]]; then
      if ! CHROME_ROOT="$(readlink -f "${FLAGS_chrome_root}")"; then
        die_notrace "${FLAGS_chrome_root} does not exist."
      fi
    fi
    if [ -z "${CHROME_ROOT}" ]; then
      CHROME_ROOT="$(cat "${FLAGS_chroot}${CHROME_ROOT_CONFIG}" \
        2>/dev/null || :)"
      CHROME_ROOT_AUTO=1
    fi
    if [[ -n "${CHROME_ROOT}" ]]; then
      if [[ ! -d "${CHROME_ROOT}/src" ]]; then
        error "Not mounting chrome source: could not find CHROME_ROOT/src dir."
        error "Full path we tried: ${CHROME_ROOT}/src"
        rm -f "${FLAGS_chroot}${CHROME_ROOT_CONFIG}"
        if [[ -z "${CHROME_ROOT_AUTO}" ]]; then
          exit 1
        fi
      else
        debug "Mounting chrome source at: ${INNER_CHROME_ROOT}"
        echo "${CHROME_ROOT}" > "${FLAGS_chroot}${CHROME_ROOT_CONFIG}"
        setup_mount "${CHROME_ROOT}" "${INNER_CHROME_ROOT}"
        setup_gclient_cache_dir_mount "${CHROME_ROOT}"
      fi
    fi

    setup_git
  ) 200>>"${LOCKFILE}" || die "setup_env failed"
}

# We might have a read-only chroot mount, to help enforce state separation in
# the SDK; if so, temporarily remount it read/write some ephemeral and
# regularly-synced pieces of the environment.
if mount_is_ro "${FLAGS_chroot}"; then
  mount -o bind,remount,rw "${FLAGS_chroot}"
  setup_env
  mount -o bind,remount,ro "${FLAGS_chroot}"
else
  setup_env
fi

exit 0
