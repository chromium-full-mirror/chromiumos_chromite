// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';

export type TestInstance = {
  range: vscode.Range; // 0-based
  suite: string;
  name: string;
};

/**
 * Parse the given file content and finds gtest test cases.
 */
export function parse(content: string): TestInstance[] {
  const res: TestInstance[] = [];

  // Match with strings like "TEST(foo, bar)".
  // https://google.github.io/googletest/reference/testing.html
  const re = /^[^\S\n]*TEST(?:_F|_P)?\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)/gm;
  let m;

  let index = 0;
  let row = 0;
  let col = 0;

  const proceed = (endIndex: number) => {
    for (; index < endIndex; index++) {
      if (content[index] === '\n') {
        row++;
        col = 0;
      } else {
        col++;
      }
    }
  };

  while ((m = re.exec(content)) !== null) {
    proceed(m.index);
    const start = new vscode.Position(row, col);

    proceed(m.index + m[0].length);
    const end = new vscode.Position(row, col);

    const range = new vscode.Range(start, end);

    res.push({
      range,
      suite: m[1],
      name: m[2],
    });
  }

  return res;
}
