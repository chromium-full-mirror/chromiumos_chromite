// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as fs from 'fs/promises';
import * as path from 'path';
import {CancellationTokenSource} from 'vscode';
import * as gnArgs from '../../../../features/chromium/gn_args';
import * as config from '../../../../services/config';
import * as testing from '../../../testing';

describe('gn args', () => {
  const tempDir = testing.tempDir();
  const {fakeExec} = testing.installFakeExec();

  beforeEach(async () => {
    await config.paths.depotTools.update('/opt/custom_depot_tools');
  });

  for (const testCase of [
    {
      name: 'shows warning if neither goma or siso is enabled',
      gnArgs: [{name: 'foo_bar', current: {value: 'true'}}],
      wantWarnings: [
        jasmine.stringContaining('Neither Goma, Siso, nor Reclient is enabled'),
      ],
      wantArgs: {
        use_siso: false,
        use_goma: false,
        use_remoteexec: false,
      },
    },
    {
      name: 'shows warning if goma is explicitly disabled',
      gnArgs: [{name: 'use_goma', current: {value: 'false'}}],
      wantWarnings: [
        jasmine.stringContaining('Neither Goma, Siso, nor Reclient is enabled'),
      ],
      wantArgs: {
        use_siso: false,
        use_goma: false,
        use_remoteexec: false,
      },
    },
    {
      name: 'shows warning if siso is explicitly disabled',
      gnArgs: [{name: 'use_siso', current: {value: 'false'}}],
      wantWarnings: [
        jasmine.stringContaining('Neither Goma, Siso, nor Reclient is enabled'),
      ],
      wantArgs: {
        use_siso: false,
        use_goma: false,
        use_remoteexec: false,
      },
    },
    {
      name: 'shows no warning if goma is enabled',
      gnArgs: [{name: 'use_goma', current: {value: 'true'}}],
      wantWarnings: [],
      wantArgs: {
        use_siso: false,
        use_goma: true,
        use_remoteexec: false,
      },
    },
    {
      name: 'shows no warning if siso is enabled',
      gnArgs: [{name: 'use_siso', current: {value: 'true'}}],
      wantWarnings: [],
      wantArgs: {
        use_siso: true,
        use_goma: false,
        use_remoteexec: false,
      },
    },
    {
      name: 'shows no warning if reclient is enabled',
      gnArgs: [{name: 'use_remoteexec', current: {value: 'true'}}],
      wantWarnings: [],
      wantArgs: {
        use_siso: false,
        use_goma: false,
        use_remoteexec: true,
      },
    },
  ]) {
    it(`queries GN args correctly and ${testCase.name}`, async () => {
      await fs.mkdir(path.join(tempDir.path, 'out'));
      await fs.mkdir(path.join(tempDir.path, 'out/dir1'));

      fakeExec.installStdout(
        'gn',
        [
          'args',
          path.join(tempDir.path, 'out', 'dir1'),
          '--list',
          '--short',
          '--overrides-only',
          '--json',
        ],
        JSON.stringify(testCase.gnArgs),
        jasmine.objectContaining({cwd: tempDir.path})
      );

      const tokenSource = new CancellationTokenSource();
      const args = await gnArgs.readGnArgs(
        tempDir.path,
        'out/dir1',
        tokenSource.token
      );
      expect(args).toEqual({
        type: 'success',
        warnings: testCase.wantWarnings,
        args: testCase.wantArgs,
      });
    });
  }
});
