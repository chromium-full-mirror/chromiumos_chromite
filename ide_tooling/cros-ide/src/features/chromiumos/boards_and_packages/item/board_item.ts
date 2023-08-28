// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {BoardOrHost} from '../../../../common/chromiumos/board_or_host';
import * as config from '../../../../services/config';
import {ViewItemContext} from '../constant';
import {Context} from '../context';
import {listPackages, type Package} from '../package';
import {Breadcrumbs} from './breadcrumbs';
import {Item} from './item';
import {PackageCategoryItem} from './package_category_item';

export class BoardItem implements Item {
  readonly breadcrumbs;
  readonly treeItem;
  readonly children: Item[] = [];

  constructor(parent: Breadcrumbs, private readonly board: BoardOrHost) {
    this.breadcrumbs = parent.pushed(board.toString());

    const treeItem = new vscode.TreeItem(
      board.toString(),
      vscode.TreeItemCollapsibleState.Collapsed
    );

    const isHost = board.isHost;
    const isDefault = config.board.get() === board.toString();

    treeItem.iconPath = isHost
      ? new vscode.ThemeIcon('device-desktop')
      : new vscode.ThemeIcon('circuit-board');

    if (isDefault) {
      treeItem.description = 'default';
    }

    treeItem.contextValue = isDefault
      ? ViewItemContext.BOARD_DEFAULT
      : isHost
      ? ViewItemContext.BOARD_HOST
      : ViewItemContext.BOARD;

    this.treeItem = treeItem;
  }

  async refreshChildren(ctx: Context): Promise<void | Error> {
    const packages = await listPackages(ctx, this.board);
    if (packages instanceof Error) return packages;

    const categoryToPackages = new Map<string, Package[]>();

    for (const pkg of packages) {
      if (!categoryToPackages.has(pkg.category)) {
        categoryToPackages.set(pkg.category, []);
      }
      categoryToPackages.get(pkg.category)?.push(pkg);
    }

    const favoriteCategories = new Set(
      config.boardsAndPackages.favoriteCategories.get() ?? []
    );

    const categories = [...categoryToPackages.keys()].map(category => ({
      category,
      favorite: favoriteCategories.has(category),
    }));
    categories.sort((a, b) => {
      if (a.favorite !== b.favorite) {
        return a.favorite ? -1 : 1;
      }
      return a.category.localeCompare(b.category);
    });

    this.children.splice(0);

    for (const {category, favorite} of categories) {
      this.children.push(
        new PackageCategoryItem(
          this.breadcrumbs,
          category,
          favorite,
          categoryToPackages.get(category)!
        )
      );
    }
  }
}
