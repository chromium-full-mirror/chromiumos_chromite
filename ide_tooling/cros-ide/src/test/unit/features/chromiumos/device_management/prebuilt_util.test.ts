// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as commonUtil from '../../../../../common/common_util';
import * as prebuiltUtil from '../../../../../features/device_management/prebuilt_util';
import * as services from '../../../../../services';
import * as testing from '../../../../testing';
import * as fakes from '../../../../testing/fakes';

describe('Prebuilt utilities', () => {
  const {fakeExec} = testing.installFakeExec();
  fakes.installFakeSudo(fakeExec);
  const tempDir = testing.tempDir();

  it('list available images', async () => {
    await testing.buildFakeChroot(tempDir.path);

    const FAKE_STDOUT = `gs://chromeos-image-archive/xyz-release/R100-10000.0.0/
gs://chromeos-image-archive/xyz-release/R100-10001.0.0/
gs://chromeos-image-archive/xyz-release/R101-10100.0.0/
gs://chromeos-image-archive/xyz-release/R101-10101.0.0/
gs://chromeos-image-archive/xyz-release/R99-9900.0.0/
gs://chromeos-image-archive/xyz-release/R99-9901.0.0/
gs://chromeos-image-archive/xyz-release/garbage.txt
`;

    fakes.legacyInstallChrootCommandHandler(
      fakeExec,
      tempDir.path as commonUtil.Source,
      'gsutil',
      testing.exactMatch(
        ['ls', 'gs://chromeos-image-archive/xyz-release/'],
        async () => FAKE_STDOUT
      )
    );

    const versions = await prebuiltUtil.listPrebuiltVersions(
      'xyz',
      services.chromiumos.ChrootService.maybeCreate(tempDir.path, false)!,
      new fakes.VoidOutputChannel()
    );
    expect(versions).toEqual([
      'R101-10101.0.0',
      'R101-10100.0.0',
      'R100-10001.0.0',
      'R100-10000.0.0',
      'R99-9901.0.0',
      'R99-9900.0.0',
    ]);
  });
});
