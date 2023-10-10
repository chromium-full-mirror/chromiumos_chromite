// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';

export type EbuildVarName = {
  name: string;
  range: vscode.Range;
};

export type EbuildStrValue = {
  kind: 'string';
  value: string;
  range: vscode.Range;
};

export type EbuildValue =
  | EbuildStrValue
  | {
      kind: 'array';
      value: EbuildStrValue[];
      range: vscode.Range; // Range of the array including '(' and ')'.
    };

type EbuildAssignment = {
  name: EbuildVarName;
  value: EbuildValue;
};

export type ParsedEbuild = {
  assignments: EbuildAssignment[];
};

function indexToPositions(content: string): vscode.Position[] {
  const positions: vscode.Position[] = [];
  let row = 0;
  let col = 0;
  for (const c of content) {
    positions.push(new vscode.Position(row, col));
    if (c === '\n') {
      row += 1;
      col = 0;
    } else if (c === '\t') {
      // Tab \t occupies 2 spaces in vscode range.
      col += 2;
    } else {
      col += 1;
    }
  }
  return positions;
}

export function parseEbuildOrThrow(content: string): ParsedEbuild {
  const positions = indexToPositions(content);

  const assignmentStartRe = /^([\w_][\w\d_]*)=/gm;

  const assignments = [];

  let m;
  while ((m = assignmentStartRe.exec(content))) {
    const name = {
      name: m[1],
      range: new vscode.Range(
        // Range of variable name starts from index of matched string and ends at that
        // of the matched last index, minus 1 for trailing '='.
        positions[m.index],
        positions[assignmentStartRe.lastIndex - 1]
      ),
    };

    const scanner = new Scanner(
      content,
      positions,
      assignmentStartRe.lastIndex
    );

    const value = scanner.nextValue();

    assignmentStartRe.lastIndex = scanner.lastIndex;

    assignments.push({
      name,
      value,
    });
  }

  return {
    assignments,
  };
}

class Scanner {
  constructor(
    private readonly content: string,
    private readonly positions: vscode.Position[],
    private p: number
  ) {}

  get lastIndex() {
    return this.p;
  }

  private peek(): string {
    if (this.p >= this.content.length) {
      throw new Error('Ebuild parse failed: unclosed paren or string?');
    }
    return this.content.charAt(this.p);
  }

  private next(): string {
    const c = this.peek();
    this.p++;
    return c;
  }

  nextValue(): EbuildValue {
    if (this.peek() === '(') {
      const startPos = this.positions[this.p];
      this.next();

      const value: EbuildStrValue[] = [];

      for (;;) {
        this.skipSpaces();
        if (this.peek() === ')') {
          this.next();
          return {
            kind: 'array',
            value,
            range: new vscode.Range(startPos, this.positions[this.p]),
          };
        }
        value.push(this.nextString());
      }

      throw new Error('Ebuild parse failed: unclosed paren');
    }

    return this.nextString();
  }

  private skipSpaces(): void {
    for (;;) {
      switch (this.peek()) {
        // comment line
        case '#': {
          while (this.next() !== '\n');
          continue;
        }
        case '\t':
        case '\n':
        case ' ':
          this.next();
          continue;
        default:
          return;
      }
    }
  }

  private nextString(): EbuildStrValue {
    switch (this.peek()) {
      case '"': {
        this.next();
        const startPos = this.positions[this.p];
        let s = '';
        for (;;) {
          const c = this.next();
          if (c === '"') {
            return {
              kind: 'string',
              value: s,
              range: new vscode.Range(startPos, this.positions[this.p - 1]),
            };
          }
          s += c;
        }
      }
      case '\t':
      case '\n':
      case ' ': {
        return {
          kind: 'string',
          value: '',
          range: new vscode.Range( // empty range
            this.positions[this.p],
            this.positions[this.p]
          ),
        };
      }
      default: {
        const startPos = this.positions[this.p];
        let s = '';
        for (;;) {
          const c = this.peek();
          if (c === '\t' || c === '\n' || c === ' ' || c === ')') {
            return {
              kind: 'string',
              value: s,
              // Range has +1 overload for the ending position.
              range: new vscode.Range(startPos, this.positions[this.p]),
            };
          }
          s += c;
          this.next();
        }
      }
    }
  }
}
