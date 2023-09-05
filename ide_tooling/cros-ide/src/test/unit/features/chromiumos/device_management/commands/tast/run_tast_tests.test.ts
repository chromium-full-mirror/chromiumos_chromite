// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as path from 'path';
import * as vscode from 'vscode';
import * as commonUtil from '../../../../../../../common/common_util';
import {CommandContext} from '../../../../../../../features/device_management/commands/common';
import {
  RunTastTestsResult,
  runTastTests,
} from '../../../../../../../features/device_management/commands/tast/run_tast_tests';
import {DeviceCategory} from '../../../../../../../features/device_management/device_repository';
import {Metrics} from '../../../../../../../features/metrics/metrics';
import {ChrootService} from '../../../../../../../services/chromiumos';
import * as testing from '../../../../../../testing';
import {
  FakeTextDocument,
  VoidOutputChannel,
  legacyInstallChrootCommandHandler,
} from '../../../../../../testing/fakes';
import {FakeDeviceRepository} from '../../fake_device_repository';
import {FakeSshServer} from '../../fake_ssh_server';

describe('runTastTests', () => {
  const {vscodeSpy, vscodeEmitters, vscodeGetters} =
    testing.installVscodeDouble();
  testing.installFakeConfigs(vscodeSpy, vscodeEmitters);

  const {fakeExec} = testing.installFakeExec();

  const tempDir = testing.tempDir();

  it('runs Tast tests on device', async () => {
    // Prepare a fake chroot.
    const chromiumos = tempDir.path as commonUtil.Source;
    await testing.buildFakeChroot(chromiumos);

    // Prepare a fake device.
    const sshServer = new FakeSshServer();
    await sshServer.listen();
    const port = sshServer.listenPort;
    const hostname = `localhost:${port}`;

    const deviceRepository = FakeDeviceRepository.create([
      {hostname: hostname, category: DeviceCategory.OWNED},
      {hostname: 'other', category: DeviceCategory.OWNED},
    ]);

    // Prepare a fake Tast test.
    vscodeGetters.window.activeTextEditor.and.returnValue({
      document: new FakeTextDocument({
        uri: vscode.Uri.file(
          path.join(
            chromiumos,
            'src/platform/tast-tests/src/go.chromium.org/tast-tests/cros/local/bundles/cros/example/chrome_fixture.go'
          )
        ),
        text: `func init() {
  testing.AddTest(&testing.Test{
    Func: ChromeFixture,
  })
}

func ChromeFixture(ctx context.Context, s *testing.State) {}`,
      }) as vscode.TextDocument,
    } as vscode.TextEditor);

    // Prepare user responses.
    spyOn(Metrics, 'send');
    vscodeSpy.window.showQuickPick
      .withArgs([hostname, 'other'], jasmine.anything())
      .and.resolveTo(hostname);
    vscodeSpy.window.showQuickPick
      .withArgs(['example.ChromeFixture'], jasmine.anything())
      .and.resolveTo('example.ChromeFixture');

    // Prepare external command responses.
    legacyInstallChrootCommandHandler(
      fakeExec,
      chromiumos,
      'tast',
      testing.prefixMatch([], async args => {
        switch (args[0]) {
          case 'list':
            return 'example.ChromeFixture\n';
          case 'run':
            return ''; // OK
        }
        return new Error(`unsupported: tast ${args}`);
      })
    );

    // Test.
    const result = await runTastTests(
      {
        deviceRepository,
        sshSessions: new Map(),
        output: new VoidOutputChannel() as vscode.OutputChannel,
      } as CommandContext,
      ChrootService.maybeCreate(chromiumos, /* setContext = */ false)!
    );

    expect(result).toEqual(new RunTastTestsResult());
  });
});
