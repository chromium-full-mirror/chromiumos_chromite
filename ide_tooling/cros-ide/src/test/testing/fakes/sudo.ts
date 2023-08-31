// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as commonUtil from '../../../common/common_util';
import {FakeExec, prefixMatch} from '../fake_exec';

/**
 * Installs a FakeExec handler that responds to sudo calls.
 *
 * This function must be called in describe.
 */
export function installFakeSudo(fakeExec: FakeExec): void {
  beforeEach(() => {
    fakeExec.on(
      'sudo',
      prefixMatch(['--askpass', '--'], (restArgs, options) => {
        return commonUtil.exec(restArgs[0], restArgs.slice(1), options);
      })
    );
  });
}
