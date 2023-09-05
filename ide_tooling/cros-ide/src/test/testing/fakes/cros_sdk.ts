// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as path from 'path';
import * as commonUtil from '../../../common/common_util';
import {arrayWithPrefixAnd} from '../../unit/testing/jasmine/asymmetric_matcher';
import {FakeExec, Handler, prefixMatch} from '../fake_exec';

/**
 * Installs a fake handler for the command invoked inside chroot.
 *
 * @deprecated use installChrootCommandHandler.
 */
export function legacyInstallChrootCommandHandler(
  fakeExec: FakeExec,
  source: commonUtil.Source,
  name: string,
  handler: Handler,
  chrootOption?: {crosSdkWorkingDir?: string}
): void {
  const crosSdk = path.join(source, 'chromite/bin/cros_sdk');

  fakeExec.on(
    crosSdk,
    prefixMatch(['--', name], (restArgs, options) => {
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
    prefixMatch(prefix, (restArgs, options) => {
      return handler(restArgs, options);
    })
  );
}

/**
 * Installs a fake handler for the command invoked inside chroot.
 *
 * callback takes the arguments that are given to the command with the given name in chroot.
 */
export function installChrootCommandHandler(
  fakeExec: FakeExec,
  source: commonUtil.Source,
  name: string,
  argsMatcher: jasmine.AsymmetricMatcher<string[]> | string[],
  callback: (
    args: string[],
    options?: commonUtil.ExecOptions
  ) => ReturnType<typeof commonUtil.exec> | string,
  chrootOption?: {crosSdkWorkingDir?: string}
): void {
  const crosSdk = path.join(source, 'chromite/bin/cros_sdk');

  const crosSdkPrefix = [crosSdk];
  if (chrootOption?.crosSdkWorkingDir) {
    crosSdkPrefix.push('--working-dir', chrootOption.crosSdkWorkingDir);
  }
  crosSdkPrefix.push('--', name);

  const sudoCrosSdkPrefix = ['sudo', '--askpass', '--', ...crosSdkPrefix];

  for (const prefix of [crosSdkPrefix, sudoCrosSdkPrefix]) {
    fakeExec
      .withArgs(
        prefix[0],
        arrayWithPrefixAnd(prefix.slice(1), argsMatcher),
        jasmine.anything()
      )
      .and.callFake(async (_name, args, options) => {
        const res = await callback(args.slice(prefix.slice(1).length), options);
        if (typeof res === 'string') {
          return {exitStatus: 0, stdout: res, stderr: ''};
        }
        return res;
      });
  }
}
