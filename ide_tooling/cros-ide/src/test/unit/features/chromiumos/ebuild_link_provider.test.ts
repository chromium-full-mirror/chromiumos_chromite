// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {EbuildLinkProvider} from '../../../../features/chromiumos/ebuild_link_provider';
import {FakeCancellationToken, FakeTextDocument} from '../../../testing/fakes';

const csBase =
  'http://source.corp.google.com/h/chromium/chromiumos/codesearch/+/main:';

function documentLink(
  range: vscode.Range,
  target: vscode.Uri,
  tooltip: string
): vscode.DocumentLink {
  const link = new vscode.DocumentLink(range, target);
  link.tooltip = tooltip;
  return link;
}

function openFolderCmdUri(path: string): vscode.Uri {
  return vscode.Uri.parse(
    `command:vscode.openFolder?${encodeURIComponent(
      JSON.stringify([
        vscode.Uri.file(path),
        {
          forceNewWindow: true,
        },
      ])
    )}`
  );
}

describe('Ebuild Link Provider', () => {
  it('extracts links', async () => {
    const SIMPLE_LOCALNAME = `
EAPI=7
CROS_WORKON_USE_VCSID="1"
CROS_WORKON_LOCALNAME="platform2"
CROS_WORKON_PROJECT="chromiumos/platform2"
CROS_WORKON_OUTOFTREE_BUILD=1
CROS_WORKON_SUBTREE="common-mk biod .gn"
PLATFORM_SUBDIR="biod"
`;

    const ebuildLinkProvider = new EbuildLinkProvider('/path/to/cros');
    const textDocument = new FakeTextDocument({text: SIMPLE_LOCALNAME});

    const documentLinks = ebuildLinkProvider.provideDocumentLinks(
      textDocument,
      new FakeCancellationToken()
    );

    const rangeLocalName = new vscode.Range(3, 23, 3, 32);
    const rangeCommonMk = new vscode.Range(6, 21, 6, 30);
    const rangeBiod = new vscode.Range(6, 31, 6, 35);
    const rangeGn = new vscode.Range(6, 36, 6, 39);

    expect(documentLinks).toEqual([
      documentLink(
        rangeLocalName,
        vscode.Uri.parse(csBase + 'src/platform2'),
        'Open src/platform2 in CodeSearch'
      ),
      documentLink(
        rangeLocalName,
        openFolderCmdUri('/path/to/cros/src/platform2'),
        'Open src/platform2 in New VS Code Window'
      ),
      documentLink(
        rangeCommonMk,
        vscode.Uri.parse(csBase + 'src/platform2/common-mk'),
        'Open src/platform2/common-mk in CodeSearch'
      ),
      documentLink(
        rangeCommonMk,
        openFolderCmdUri('/path/to/cros/src/platform2/common-mk'),
        'Open src/platform2/common-mk in New VS Code Window'
      ),
      documentLink(
        rangeBiod,
        vscode.Uri.parse(csBase + 'src/platform2/biod'),
        'Open src/platform2/biod in CodeSearch'
      ),
      documentLink(
        rangeBiod,
        openFolderCmdUri('/path/to/cros/src/platform2/biod'),
        'Open src/platform2/biod in New VS Code Window'
      ),
      documentLink(
        rangeGn,
        vscode.Uri.parse(csBase + 'src/platform2/.gn'),
        'Open src/platform2/.gn in CodeSearch'
      ),
      documentLink(
        rangeGn,
        openFolderCmdUri('/path/to/cros/src/platform2/.gn'),
        'Open src/platform2/.gn in New VS Code Window'
      ),
    ]);
  });

  it('handles local name with leading two dots', async () => {
    const TPM_EBUILD = `
EAPI="7"
CROS_WORKON_PROJECT="chromiumos/platform/tpm"
CROS_WORKON_LOCALNAME="../third_party/tpm"

inherit cros-sanitizers cros-workon toolchain-funcs
`;

    const ebuildLinkProvider = new EbuildLinkProvider('/path/to/cros');
    const textDocument = new FakeTextDocument({text: TPM_EBUILD});

    const documentLinks = ebuildLinkProvider.provideDocumentLinks(
      textDocument,
      new FakeCancellationToken()
    );

    const rangeLocalName = new vscode.Range(3, 23, 3, 41);

    expect(documentLinks).toEqual([
      documentLink(
        rangeLocalName,
        vscode.Uri.parse(csBase + 'src/third_party/tpm'),
        'Open src/third_party/tpm in CodeSearch'
      ),
      documentLink(
        rangeLocalName,
        openFolderCmdUri('/path/to/cros/src/third_party/tpm'),
        'Open src/third_party/tpm in New VS Code Window'
      ),
    ]);
  });
});
