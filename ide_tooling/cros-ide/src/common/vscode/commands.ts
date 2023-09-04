// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';

const commandsToDismissError = new Set<string>();

/**
 * Register a command. This is a wrapper of vscode.commands.registerCommand
 * which does error handling on callback failure.
 */
export function vscodeRegisterCommand(
  command: string,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  callback: (...args: any[]) => any | Promise<any>
): vscode.Disposable {
  return vscode.Disposable.from(
    vscode.commands.registerCommand(command, async (...args) => {
      try {
        return await callback(...args);
      } catch (e) {
        if (!commandsToDismissError.has(command)) {
          void (async () => {
            const choice = await vscode.window.showErrorMessage(
              `Command ${command} failed: ${e}`,
              'Ignore'
            );
            if (choice) {
              commandsToDismissError.add(command);
            }
          })();
        }
        throw e;
      }
    }),
    new vscode.Disposable(() => {
      // For testability, clear the state on unregistration.
      commandsToDismissError.delete(command);
    })
  );
}
