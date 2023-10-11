// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as fs from 'fs';
import * as path from 'path';
import {
  ParsedEbuild,
  parseEbuildOrThrow,
} from '../../../../../common/chromiumos/portage/parse';

describe('Ebuild parser', () => {
  // Helper functions to concisely define test case expectations.
  const str = (value: string) =>
    ({
      kind: 'string',
      value,
    } as const);
  const arr = (value: string[]) =>
    ({
      kind: 'array',
      value,
    } as const);

  const testCases: {
    name: string;
    content: string;
    want?: ParsedEbuild;
    wantError?: boolean;
  }[] = [
    {
      name: 'parses empty file',
      content: '',
      want: {
        assignments: [],
      },
    },
    {
      name: 'parses one-str-variable file without quotes',
      content: 'a=foo\n',
      want: {
        assignments: [
          {
            name: 'a',
            value: str('foo'),
          },
        ],
      },
    },
    {
      name: 'parses one-str-variable file with quotes',
      content: 'b="bar"\n',
      want: {
        assignments: [
          {
            name: 'b',
            value: str('bar'),
          },
        ],
      },
    },
    {
      name: 'parses one-arr-variable file',
      content: `c=(
\t"foo"
\t"bar"
\t"baz"
)
`,
      want: {
        assignments: [
          {
            name: 'c',
            value: arr(['foo', 'bar', 'baz']),
          },
        ],
      },
    },
    {
      name: 'parses realistic example',
      content: fs.readFileSync(
        path.join(
          __dirname,
          '../../../../../../src/test/testdata/portage/testing-9999.ebuild'
        ),
        'utf8'
      ),
      want: {
        assignments: [
          {
            name: 'a',
            value: str('1'),
          },
          {
            name: 'B',
            value: str('2#3'),
          },
          {
            name: 'C',
            value: str(''),
          },
          {
            name: 'D',
            value: arr([]),
          },
          {
            name: 'E',
            value: arr(['foo']),
          },
          {
            name: 'CROS_WORKON_LOCALNAME',
            value: str('platform2'),
          },
          {
            name: 'CROS_WORKON_DESTDIR',
            value: str('${S}/platform2'),
          },
          {
            name: 'CROS_WORKON_SUBTREE',
            value: str('common-mk codelab .gn'),
          },
          {
            name: 'CROS_WORKON_DESTDIR',
            value: arr(['${S}/platform2', '${S}/aosp/system/keymaster']),
          },
          {
            name: 'CROS_WORKON_DESTDIR_2',
            value: arr([
              '${S}/platform/ec',
              '${S}/third_party/cryptoc',
              '${S}/third_party/eigen3',
              '${S}/third_party/boringssl',
            ]),
          },
          {
            name: 'KEYWORDS',
            value: str('~*'),
          },
          {
            name: 'IUSE',
            value: str(''),
          },
          {
            name: 'DEPEND',
            value: str('${RDEPEND}\n\tx11-drivers/opengles-headers'),
          },
        ],
      },
    },
    {
      name: 'throws on unclosed paren',
      content: 'A=(',
      wantError: true,
    },
    {
      name: 'throws on unclosed string',
      content: 'A="',
      wantError: true,
    },
  ];

  for (const tc of testCases) {
    it(tc.name, () => {
      try {
        const got = parseEbuildOrThrow(tc.content);
        expect(got).toEqual(tc.want!);
      } catch (e) {
        expect(tc.wantError).toEqual(true);
      }
    });
  }
});
