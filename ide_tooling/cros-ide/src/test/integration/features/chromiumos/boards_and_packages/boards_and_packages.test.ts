// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {BoardsAndPackages} from '../../../../../features/chromiumos/boards_and_packages';
import {Breadcrumbs} from '../../../../../features/chromiumos/boards_and_packages/item';
import {Packages} from '../../../../../features/chromiumos/boards_and_packages/package';
import {ChrootService} from '../../../../../services/chromiumos';
import {underDevelopment} from '../../../../../services/config';
import * as testing from '../../../../testing';
import {FakeStatusManager} from '../../../../testing/fakes';

describe('Boards and packages', () => {
  const tempDir = testing.tempDir();

  const subscriptions: vscode.Disposable[] = [];

  const originalFlagValue = underDevelopment.boardsAndPackagesV2.get();

  afterEach(async () => {
    vscode.Disposable.from(...subscriptions.reverse()).dispose();
    subscriptions.splice(0);

    await underDevelopment.boardsAndPackagesV2.update(originalFlagValue);
  });

  it('supports revealing tree items from breadcrumbs', async () => {
    const chroot = await testing.buildFakeChroot(tempDir.path);

    await testing.putFiles(chroot, {
      'build/betty/fake': 'x',
    });

    const chrootService = ChrootService.maybeCreate(
      tempDir.path,
      /* setContext = */ false
    )!;

    const boardsAndPackages = new BoardsAndPackages(
      chrootService,
      new FakeStatusManager()
    );
    subscriptions.push(boardsAndPackages);

    const treeView = boardsAndPackages.getTreeViewForTesting();

    expect(treeView.title).toEqual('Boards and Packages');

    spyOn(Packages, 'readOrThrow').and.resolveTo([
      {
        category: 'chromeos-base',
        name: 'codelab',
      },
    ]);

    await treeView.reveal(Breadcrumbs.from('host', 'chromeos-base', 'codelab'));
    await treeView.reveal(
      Breadcrumbs.from('betty', 'chromeos-base', 'codelab')
    );

    await expectAsync(
      treeView.reveal(Breadcrumbs.from('betty', 'chromeos-base', 'not-exist'))
    ).toBeRejected();
  });
});
