// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import 'jasmine';
import * as cipd from '../../../common/cipd';
import {FakeExec, exactMatch} from '../fake_exec';
import {tempDir as testingTempDir} from '../fs';

/**
 * Installs a fake cipd executable for testing, and returns a CipdRepository
 * ready to use for testing. Returned CipdRepository is refreshed per test.
 *
 * This function should be called in describe.
 */
export function installFakeCipd(fakeExec: FakeExec): cipd.CipdRepository {
  const tempDir = testingTempDir();
  const cipdRepository = new cipd.CipdRepository(tempDir.path);

  beforeEach(() => {
    Object.assign(cipdRepository, new cipd.CipdRepository(tempDir.path));
    fakeExec.on(
      'cipd',
      exactMatch(['init', tempDir.path, '-force'], async () => 'ok')
    );
    fakeExec.on(
      'cipd',
      exactMatch(
        [
          'install',
          '-root',
          tempDir.path,
          'chromiumos/infra/crosfleet/${platform}',
          'prod',
        ],
        async () => 'ok'
      )
    );
  });

  return cipdRepository;
}
