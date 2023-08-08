// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as path from 'path';
import * as commonUtil from '../../../common/common_util';
import * as testing from '../../testing';

/**
 * Installs a fake handler for the command invoked inside chroot.
 */
export function installChrootCommandHandler(
  fakeExec: testing.FakeExec,
  source: commonUtil.Source,
  name: string,
  handler: testing.Handler,
  chrootOption?: {crosSdkWorkingDir?: string}
): void {
  const crosSdk = path.join(source, 'chromite/bin/cros_sdk');

  fakeExec.on(
    crosSdk,
    testing.prefixMatch(['--', name], (restArgs, options) => {
      return handler(restArgs, options);
    })
  );

  const prefix = ['--askpass', '--', crosSdk];
  if (chrootOption?.crosSdkWorkingDir) {
    prefix.push('--working-dir', chrootOption.crosSdkWorkingDir);
  }
  prefix.push('--', name);

  fakeExec.on(
    'sudo',
    testing.prefixMatch(prefix, (restArgs, options) => {
      return handler(restArgs, options);
    })
  );
}
