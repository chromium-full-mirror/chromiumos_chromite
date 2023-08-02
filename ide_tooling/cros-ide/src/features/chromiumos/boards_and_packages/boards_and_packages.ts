// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {ChrootService} from '../../../services/chromiumos';
import {StatusManager, TaskStatus} from '../../../ui/bg_task_status';
import {Breadcrumbs} from './item';
import {BoardsAndPackagesTreeDataProvider} from './tree_data_provider';

/**
 * The entry point of the boards and packages feature.
 */
export class BoardsAndPackages implements vscode.Disposable {
  private readonly subscriptions: vscode.Disposable[] = [];

  private readonly treeView;

  constructor(chrootService: ChrootService, statusManager: StatusManager) {
    const output = vscode.window.createOutputChannel('Boards and packages');
    this.subscriptions.push(output);

    statusManager.setTask('Boards and packages', {
      status: TaskStatus.OK,
      outputChannel: output,
    });

    this.treeView = vscode.window.createTreeView('boards-and-packages', {
      treeDataProvider: new BoardsAndPackagesTreeDataProvider(
        chrootService,
        output
      ),
    });
    this.subscriptions.push(this.treeView);
  }

  getTreeViewForTesting(): vscode.TreeView<Breadcrumbs> {
    return this.treeView;
  }

  dispose(): void {
    vscode.Disposable.from(...this.subscriptions.reverse()).dispose();
  }
}
