// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
import * as vscode from 'vscode';
import {Metrics} from '../../metrics/metrics';

export function activate(context: vscode.ExtensionContext): void {
  context.subscriptions.push(
    vscode.languages.registerHoverProvider(
      {language: 'shellscript', pattern: '**/*.{ebuild,eclass}'},
      new PortageReferenceHoverProvider()
    )
  );
}

export const PORTAGE_PREDEFINED_READ_ONLY_VARIABLES_HOVER_STRING =
  ' is a portage predefined read-only variable. Please check https://devmanual.gentoo.org/ebuild-writing/variables/#predefined-read-only-variables for its purpose.';
export const EBUILD_DEFINED_VARIABLES_HOVER_STRING =
  ' is a portage ebuild-defined variable. Please check https://devmanual.gentoo.org/ebuild-writing/variables/#ebuild-defined-variables for its purpose.';

const PORTAGE_PREDEFINED_READ_ONLY_VARAIBLES = [
  'P',
  'PN',
  'PV',
  'PR',
  'PVR',
  'PF',
  'A',
  'CATEGORY',
  'FILESDIR',
  'WORKDIR',
  'T',
  'D',
  'HOME',
  'ROOT',
  'DISTDIR',
  'EPREFIX',
  'ED',
  'EROOT',
  'SYSROOT',
  'ESYSROOT',
  'BROOT',
  'MERGE_TYPE',
  'REPLACING_VERSIONS',
  'REPLACED_BY_VERSION',
];

const EBUILD_DEFINED_VARIABLES = [
  'EAPI',
  'DESCRIPTION',
  'HOMEPAGE',
  'SRC_URI',
  'LICENSE',
  'SLOT',
  'KEYWORDS',
  'IUSE',
  'REQUIRED_USE',
  'PROPERTIES',
  'RESTRICT',
  'DEPEND',
  'BDEPEND',
  'RDEPEND',
  'PDEPEND',
  'S',
  'DOCS',
  'HTML_DOCS',
];

export class PortageReferenceHoverProvider implements vscode.HoverProvider {
  constructor() {}

  provideHover(
    document: vscode.TextDocument,
    position: vscode.Position,
    _token: vscode.CancellationToken
  ): vscode.ProviderResult<vscode.Hover> {
    const range = document.getWordRangeAtPosition(position);
    const word = document.getText(range);
    if (PORTAGE_PREDEFINED_READ_ONLY_VARAIBLES.includes(word)) {
      Metrics.send({
        category: 'background',
        group: 'ebuild',
        name: 'show_portage_predefined_read_only_variable_hover',
        description:
          'ebuild: user hovered on portage predefined read-only variable',
        variable: word,
      });
      return new vscode.Hover(
        word + PORTAGE_PREDEFINED_READ_ONLY_VARIABLES_HOVER_STRING,
        range
      );
    }
    if (EBUILD_DEFINED_VARIABLES.includes(word)) {
      Metrics.send({
        category: 'background',
        group: 'ebuild',
        name: 'show_ebuild_defined_variable_hover',
        description: 'ebuild: user hovered on ebuild-defined variable',
        variable: word,
      });
      return new vscode.Hover(
        word + EBUILD_DEFINED_VARIABLES_HOVER_STRING,
        range
      );
    }
  }
}
