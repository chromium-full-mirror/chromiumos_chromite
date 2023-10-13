// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {
  EBUILD_DEFINED_VARIABLES_HOVER_STRING,
  PORTAGE_PREDEFINED_READ_ONLY_VARIABLES_HOVER_STRING,
  PortageReferenceHoverProvider,
} from '../../../../../features/chromiumos/ebuild/portage_reference';
import {
  FakeCancellationToken,
  FakeTextDocument,
} from '../../../../testing/fakes';

const SIMPLE_EBUILD = `
EAPI=7
inherit multilib-minimal arc-build-constants

DESCRIPTION="Ebuild for per-sysroot arc-build components."

LICENSE="BSD-Google"
SLOT="0"
KEYWORDS="*"

RDEPEND=""
DEPEND=""

S=\${WORKDIR}
`;

describe('Portage Reference Hover Provider', () => {
  it('show hover', async () => {
    const portageReferenceHoverProvider = new PortageReferenceHoverProvider();
    const textDocument = new FakeTextDocument({text: SIMPLE_EBUILD});

    let position = new vscode.Position(1, 1); // Of EAPI
    const hoverEapi = portageReferenceHoverProvider.provideHover(
      textDocument,
      position,
      new FakeCancellationToken()
    );
    expect(hoverEapi).toEqual(
      new vscode.Hover(
        'EAPI' + EBUILD_DEFINED_VARIABLES_HOVER_STRING,
        new vscode.Range(1, 0, 1, 4)
      )
    );

    position = new vscode.Position(13, 8); // Of WORKDIR
    const hoverWorkdir = portageReferenceHoverProvider.provideHover(
      textDocument,
      position,
      new FakeCancellationToken()
    );
    expect(hoverWorkdir).toEqual(
      new vscode.Hover(
        'WORKDIR' + PORTAGE_PREDEFINED_READ_ONLY_VARIABLES_HOVER_STRING,
        new vscode.Range(13, 4, 13, 11)
      )
    );
  });
});
