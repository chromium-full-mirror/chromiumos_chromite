// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {GtestRunnable} from './gtest_runnable';
import {GtestSuite} from './gtest_suite';

/**
 * Represents one gtest test case.
 */
export class GtestCase extends GtestRunnable {
  constructor(
    controller: vscode.TestController,
    private readonly testSuite: GtestSuite,
    range: vscode.Range,
    private readonly caseName: string
  ) {
    const item = controller.createTestItem(
      /*id=*/ `case:${caseName}`,
      /*label=*/ caseName,
      testSuite.uri
    );
    item.range = range;
    testSuite.item.children.add(item);
    super(controller, item, testSuite.uri);
  }

  get testName(): string {
    return `${this.testSuite.suiteName}.${this.caseName}`;
  }

  override getChildren(): [] {
    // A test case currently does not have children.
    // TODO(cmfcmf): It will have children once we properly support parametrized tests.
    return [];
  }

  override getGtestFilter(): string {
    if (this.testSuite.isParametrized) {
      // Parametrized tests may or may not have a prefix.
      return `*/${this.testName}/*:${this.testName}/*`;
    } else {
      return this.testName;
    }
  }

  /**
   * Returns a generator over all test cases matching the request.
   */
  override *matchingTestCases(
    request: vscode.TestRunRequest,
    parentIsIncluded: boolean
  ): Generator<GtestCase, void, void> {
    if (request.exclude?.includes(this.item)) {
      return;
    }

    const include =
      parentIsIncluded ||
      !request.include ||
      request.include.includes(this.item);

    if (include) {
      yield this;
    }
  }
}
