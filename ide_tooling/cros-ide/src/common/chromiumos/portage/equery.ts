// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ParsedPackageName} from './ebuild';

/**
 * Builds a command run in chroot to get the 9999 ebuild filepath.
 */
export function buildGet9999EbuildCommand(
  board: string | undefined,
  pkg: ParsedPackageName
): string[] {
  return [
    'env',
    // Accept 9999 ebuilds that have the ~* keyword.
    // https://wiki.gentoo.org/wiki/ACCEPT_KEYWORDS
    'ACCEPT_KEYWORDS=~*',
    equeryExecutableName(board),
    'which',
    `=${pkg.category}/${pkg.name}-9999`,
  ];
}

function equeryExecutableName(board: string | undefined): string {
  return board ? `equery-${board}` : 'equery';
}
