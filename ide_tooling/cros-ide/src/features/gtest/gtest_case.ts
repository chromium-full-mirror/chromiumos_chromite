// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';

/**
 * Represents one gtest test case.
 */
export class GtestCase implements vscode.Disposable {
  readonly item: vscode.TestItem;

  dispose() {
    this.parent.children.delete(this.item.id);
  }

  constructor(
    controller: vscode.TestController,
    private readonly parent: vscode.TestItem,
    readonly uri: vscode.Uri,
    range: vscode.Range,
    private readonly suite: string,
    private readonly name: string
  ) {
    const id = `${uri}/${this.testName}`;
    this.item = controller.createTestItem(id, this.testName, uri);
    this.item.range = range;
    this.parent.children.add(this.item);
  }

  get testName() {
    return `${this.suite}.${this.name}`;
  }
}
