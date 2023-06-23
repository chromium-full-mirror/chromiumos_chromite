// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {Position} from './position';
import type * as vscode from 'vscode';

export class Range {
  readonly start: Position;
  readonly end: Position;

  constructor(start: vscode.Position, end: vscode.Position);
  constructor(
    startLine: number,
    startCharacter: number,
    endLine: number,
    endCharacter: number
  );
  constructor(
    startOrStartLine: vscode.Position | number,
    endOrStartCharacter: vscode.Position | number,
    endLine?: number,
    endCharacter?: number
  ) {
    if (typeof startOrStartLine === 'number') {
      this.start = new Position(
        startOrStartLine,
        endOrStartCharacter as number
      );
      this.end = new Position(endLine!, endCharacter!);
    } else {
      this.start = startOrStartLine;
      this.end = endOrStartCharacter as vscode.Position;
    }
  }

  contains(_positionOrRange: Range | Position): boolean {
    throw new Error('Not implemented');
  }

  intersection(_range: Range): Range {
    throw new Error('Not implemented');
  }

  isEqual(_other: Range): boolean {
    throw new Error('Not implemented');
  }

  union(_other: Range): Range {
    throw new Error('Not implemented');
  }

  with(start?: Position, end?: Position): Range;
  with(change: {end: Position; start: Position}): Range;
  with(): Range {
    throw new Error('Not implemented');
  }
}
