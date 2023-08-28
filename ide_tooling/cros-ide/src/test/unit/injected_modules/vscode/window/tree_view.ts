// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {readPackageJson} from '../../../../testing/package_json';
import {Disposable} from '../disposable';
import {EventEmitter} from '../event';
import type * as vscode from 'vscode';

export function createTreeView<T>(
  viewId: string,
  options: vscode.TreeViewOptions<T>
): vscode.TreeView<T> {
  return new TreeView(viewId, options);
}

class TreeView<T> implements vscode.TreeView<T> {
  onDidExpandElementEmitter = new EventEmitter<
    vscode.TreeViewExpansionEvent<T>
  >();
  onDidExpandElement: vscode.Event<vscode.TreeViewExpansionEvent<T>> =
    this.onDidExpandElementEmitter.event;

  onDidCollapseElementEmitter = new EventEmitter<
    vscode.TreeViewExpansionEvent<T>
  >();
  onDidCollapseElement = this.onDidCollapseElementEmitter.event;

  onDidChangeSelectionEmitter = new EventEmitter<
    vscode.TreeViewSelectionChangeEvent<T>
  >();
  onDidChangeSelection = this.onDidChangeSelectionEmitter.event;

  onDidChangeVisibilityEmitter =
    new EventEmitter<vscode.TreeViewVisibilityChangeEvent>();
  onDidChangeVisibility = this.onDidChangeVisibilityEmitter.event;

  private readonly subscriptions = [
    this.onDidExpandElementEmitter,
    this.onDidCollapseElementEmitter,
    this.onDidChangeSelectionEmitter,
    this.onDidChangeVisibilityEmitter,
  ];

  selection: readonly T[] = [];
  visible = true;
  message?: string | undefined;
  title?: string | undefined;
  description?: string | undefined;
  badge?: vscode.ViewBadge | undefined;

  private readonly treeDataProvider: vscode.TreeDataProvider<T>;

  constructor(viewId: string, options: vscode.TreeViewOptions<T>) {
    this.treeDataProvider = options.treeDataProvider;

    const packageJson = readPackageJson();

    const entry = packageJson.contributes.views['cros-view'].find(
      e => e.id === viewId
    );
    if (!entry) {
      fail(`${viewId} not found in package.json`);
      return;
    }

    this.title = entry.name;
  }

  async reveal(
    element: T,
    options?:
      | {
          select?: boolean | undefined;
          focus?: boolean | undefined;
          expand?: number | boolean | undefined;
        }
      | undefined
  ): Promise<void> {
    if (!this.treeDataProvider.getParent) {
      fail('Missing getParent is not supported in injected TreeView');
      return;
    }

    const elements = [];

    // Push elements from bottom to top.
    for (
      let e: T | null | undefined = element;
      e;
      e = await this.treeDataProvider.getParent(e)
    ) {
      elements.push(e);
    }
    elements.push(undefined); // undefined is the element corresponding to the root.

    // Reverse it to order them from top to bottom.
    elements.reverse();

    // Reveal the items from top to bottom.
    for (const e of elements) {
      await this.treeDataProvider.getChildren(e);
    }

    // The VSCode API reads: By default revealed element is selected. In order to not to select, set
    // the option `select` to `false`.
    if (options?.select !== false) {
      this.selection = [element];
    }
  }

  dispose() {
    Disposable.from(...this.subscriptions.reverse()).dispose();
  }
}
