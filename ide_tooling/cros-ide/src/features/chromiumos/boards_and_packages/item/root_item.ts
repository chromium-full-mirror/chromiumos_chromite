// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {getSetupBoardsAlphabetic} from '../../../../common/cros';
import {VIRTUAL_BOARDS_HOST} from '../constant';
import {Context} from '../context';
import {BoardItem} from './board_item';
import {Breadcrumbs} from './breadcrumbs';
import {Item} from './item';

export class RootItem implements Item {
  readonly breadcrumbs = Breadcrumbs.EMPTY;

  readonly treeItem = new vscode.TreeItem('unused');

  readonly children: Item[] = [];

  constructor() {}

  async refreshChildren(ctx: Context): Promise<void> {
    const boardNames = await getSetupBoardsAlphabetic(
      ctx.chrootService.chroot,
      ctx.chrootService.out
    );

    this.children.splice(0);

    for (const boardName of boardNames.concat([VIRTUAL_BOARDS_HOST])) {
      this.children.push(new BoardItem(this.breadcrumbs, boardName));
    }
  }
}
