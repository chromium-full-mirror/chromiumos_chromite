// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import {vscodeRegisterCommand} from '../../../common/vscode/commands';
import {VscodeComment, VscodeCommentThread} from '../data';
import {CommandContext} from './context';
import {discardDraft, reply} from './draft';

export enum CommandName {
  DISCARD_DRAFT = 'chromiumide.gerrit.discardDraft',
  REPLY = 'chromiumide.gerrit.reply',
  REPLY_AND_RESOLVE = 'chromiumide.gerrit.replyAndResolve',
  REPLY_AND_UNRESOLVE = 'chromiumide.gerrit.replyAndUnresolve',
}

/**
 * Register all the commands for the gerrit support on instantiation and unregister them on dispose.
 */
export class GerritCommands implements vscode.Disposable {
  private readonly onDidExecuteCommandEmitter =
    new vscode.EventEmitter<CommandName>();
  /** Emits the command name after the callback of the command is fulfilled. */
  readonly onDidExecuteCommand = this.onDidExecuteCommandEmitter.event;

  private readonly subscriptions: vscode.Disposable[] = [
    this.onDidExecuteCommandEmitter,
  ];

  constructor(ctx: CommandContext) {
    this.subscriptions.push(
      this.register(CommandName.REPLY, ({thread, text}: vscode.CommentReply) =>
        reply(ctx, thread as VscodeCommentThread, text)
      ),
      this.register(
        CommandName.REPLY_AND_RESOLVE,
        ({thread, text}: vscode.CommentReply) =>
          reply(
            ctx,
            thread as VscodeCommentThread,
            text,
            /* unresolved = */ false
          )
      ),
      this.register(
        CommandName.REPLY_AND_UNRESOLVE,
        ({thread, text}: vscode.CommentReply) =>
          reply(
            ctx,
            thread as VscodeCommentThread,
            text,
            /* unresolved = */ true
          )
      ),
      this.register(CommandName.DISCARD_DRAFT, (comment: VscodeComment) =>
        discardDraft(ctx, comment)
      )
    );
  }

  private register<T>(
    command: CommandName,
    callback: (args: T) => Thenable<void>
  ): vscode.Disposable {
    return vscodeRegisterCommand(command, async args => {
      await callback(args);
      this.onDidExecuteCommandEmitter.fire(command);
    });
  }

  dispose(): void {
    vscode.Disposable.from(...this.subscriptions.splice(0).reverse()).dispose();
  }
}
