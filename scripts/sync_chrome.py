# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Sync the Chrome source code used by Chrome OS to the specified directory."""

from __future__ import print_function

import os
import shutil

from chromite.cbuildbot import constants
from chromite.lib import commandline
from chromite.lib import cros_build_lib
from chromite.lib import gclient
from chromite.lib import osutils


def GetParser():
  """Creates the argparse parser."""
  parser = commandline.ArgumentParser(description=__doc__)

  version = parser.add_mutually_exclusive_group()
  version.add_argument('--tag', help='Sync to specified Chrome release',
                       dest='version')
  version.add_argument('--revision', help='Sync to specified git revision',
                       dest='version')

  parser.add_argument('--internal', help='Sync internal version of Chrome',
                      action='store_true', default=False)
  parser.add_argument('--reset', help='Revert local changes',
                      action='store_true', default=False)
  parser.add_argument('--gclient', help=commandline.argparse.SUPPRESS,
                      default=None)
  parser.add_argument('--gclient_template', help='Template gclient input file')
  parser.add_argument('--skip_cache', help='Skip using git cache',
                      dest='use_cache', action='store_false')
  parser.add_argument('chrome_root', help='Directory to sync chrome in')

  return parser


def main(argv):
  parser = GetParser()
  options = parser.parse_args(argv)

  if options.gclient is '':
    parser.error('--gclient can not be an empty string!')
  gclient_path = options.gclient or osutils.Which('gclient')
  if not gclient_path:
    gclient_path = os.path.join(constants.DEPOT_TOOLS_DIR, 'gclient')

  # Revert any lingering local changes.
  if not osutils.SafeMakedirs(options.chrome_root) and options.reset:
    try:
      gclient.Revert(gclient_path, options.chrome_root)
    except cros_build_lib.RunCommandError:
      osutils.RmDir(options.chrome_root)
      osutils.SafeMakedirs(options.chrome_root)

  # We're not going to use the deps file provided, instead overriding
  # to resolve gclient backwards incompatibility issues, see: crbug.com/1044411
  script_dir = os.path.dirname(os.path.realpath(__file__))
  hack_dep_file = os.path.realpath(os.path.join(script_dir,
                                                '..',
                                                'CRBUG1044411_DEPS'))
  hack_dep_file_dest = os.path.join(options.chrome_root, 'CRBUG1044411_DEPS')
  shutil.copyfile(hack_dep_file, hack_dep_file_dest)


  # Sync new Chrome.
  gclient.WriteConfigFile(gclient_path, options.chrome_root,
                          options.internal, options.version,
                          options.gclient_template, options.use_cache)
  gclient.Sync(gclient_path, options.chrome_root, reset=options.reset)

  return 0
