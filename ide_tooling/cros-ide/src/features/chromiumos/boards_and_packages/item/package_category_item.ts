// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {Context} from '../context';
import {Package} from '../package';
import {Breadcrumbs} from './breadcrumbs';
import {Item} from './item';
import {PackageNameItem} from './package_name_item';

export class PackageCategoryItem implements Item {
  readonly breadcrumbs;
  readonly treeItem;
  readonly children;

  constructor(parent: Breadcrumbs, category: string, packages: Package[]) {
    this.breadcrumbs = parent.pushed(category);
    this.treeItem = new vscode.TreeItem(
      category,
      vscode.TreeItemCollapsibleState.Collapsed
    );

    this.children = [];
    for (const pkg of packages) {
      this.children.push(new PackageNameItem(this.breadcrumbs, pkg));
    }
  }

  async refreshChildren(_ctx: Context): Promise<void> {}
}
