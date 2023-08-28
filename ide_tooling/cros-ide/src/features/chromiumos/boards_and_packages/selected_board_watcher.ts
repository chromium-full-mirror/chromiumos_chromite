// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {Breadcrumbs} from './item';

/**
 * This class watches the selection of boards and packages view and fires an event when the board
 * the item under which is selected is changed.
 */
export class SelectedBoardWatcher implements vscode.Disposable {
  private readonly onDidChangeSelectedBoardEmitter =
    new vscode.EventEmitter<string>();
  readonly onDidChangeSelectedBoard =
    this.onDidChangeSelectedBoardEmitter.event;

  private readonly subscriptions: vscode.Disposable[] = [
    this.onDidChangeSelectedBoardEmitter,
  ];

  private board: string | undefined = undefined;

  get value(): string | undefined {
    return this.board;
  }

  constructor(treeView: vscode.TreeView<Breadcrumbs>) {
    this.subscriptions.push(
      treeView.onDidChangeSelection(({selection}) => {
        if (selection.length === 0) {
          return;
        }
        // BoardsAndPackages doesn't set canSelectMany on creating the treeView, so we can assume
        // the selection contains only one element.
        const board = selection[0].breadcrumbs[0];

        if (this.board !== board) {
          this.board = board;
          this.onDidChangeSelectedBoardEmitter.fire(board);
        }
      })
    );
  }

  dispose(): void {
    vscode.Disposable.from(...this.subscriptions.splice(0).reverse()).dispose();
  }
}
