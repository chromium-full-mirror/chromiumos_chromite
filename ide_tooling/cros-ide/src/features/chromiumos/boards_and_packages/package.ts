// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {ParsedPackageName} from '../../../common/chromiumos/portage/ebuild';
import {Context} from './context';

export type Package = ParsedPackageName;

export class Packages {
  /**
   * Reads the package infos available for the board. It runs a few cros
   * commands and throws on their failures.
   */
  static async readOrThrow(_ctx: Context, _board: string): Promise<Package[]> {
    // TODO(oka): Implement it.
    return [
      {
        category: 'chromeos-base',
        name: 'codelab',
      },
      {
        category: 'chromeos-base',
        name: 'missive',
      },
      {
        category: 'dev-go',
        name: 'delve',
      },
    ];
  }
}
