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
