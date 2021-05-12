#!/usr/bin/env vpython
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# NB: Do not add a ton of wheels here as it's shared among many programs.
# Only list significant ones widely used by chromite.lib modules.
#
# For info on this syntax, see:
# https://chromium.googlesource.com/infra/infra/+/HEAD/doc/users/vpython.md#available-wheels

# [VPYTHON:BEGIN]
# python_version: "2.7"
#
# wheel: <
#   name: "infra/python/wheels/httplib2-py2_py3"
#   version: "version:0.10.3"
# >
# wheel: <
#   name: "infra/python/wheels/oauth2client-py2_py3"
#   version: "version:3.0.0"
# >
# wheel: <
#   name: "infra/python/wheels/pyasn1-py2_py3"
#   version: "version:0.2.3"
# >
# wheel: <
#   name: "infra/python/wheels/pyasn1_modules-py2_py3"
#   version: "version:0.0.8"
# >
# wheel: <
#   name: "infra/python/wheels/rsa-py2_py3"
#   version: "version:3.4.2"
# >
# wheel: <
#   name: "infra/python/wheels/six-py2_py3"
#   version: "version:1.15.0"
# >
# [VPYTHON:END]

"""Wrapper around chromite executable scripts that use vpython."""

import wrapper


def main():
  wrapper.DoMain()


if __name__ == '__main__':
  main()
