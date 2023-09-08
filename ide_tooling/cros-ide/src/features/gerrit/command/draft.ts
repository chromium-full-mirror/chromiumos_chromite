// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';
import * as api from '../api';
import * as auth from '../auth';
import {Comment, VscodeComment, VscodeCommentThread} from '../data';
import {CommandContext} from './context';

export async function reply(
  ctx: CommandContext,
  thread: VscodeCommentThread,
  message: string,
  unresolved?: boolean
): Promise<void> {
  const {
    repoId,
    changeId,
    lastComment: {commentId},
    changeNumber,
    revisionNumber,
    filePath,
  } = thread.gerritCommentThread;
  const authCookie = await auth.readAuthCookie(repoId, ctx.sink);
  if (!authCookie) {
    void (async () => {
      const choice = await vscode.window.showErrorMessage(
        'Failed to read auth cookie; confirm your .gitcookies is properly set up and you can run repo upload',
        'Open document'
      );
      if (choice) {
        await vscode.env.openExternal(
          vscode.Uri.parse(
            'https://www.chromium.org/chromium-os/developer-guide/gerrit-guide'
          )
        );
      }
    })();
    return;
  }

  // Comment shown until real draft is fetched from Gerrit.
  const tentativeComment: VscodeComment = {
    body: message,
    mode: vscode.CommentMode.Preview,
    author: {name: 'Draft being created'},
    gerritComment: new Comment(repoId, changeNumber, {
      isPublic: true,
      author: {
        _account_id: 0,
      },
      in_reply_to: commentId,
      id: '',
      updated: 'now',
      message,
    }),
  };

  thread.comments = [...thread.comments, tentativeComment];
  thread.canReply = false;

  try {
    await api.createDraftOrThrow(
      repoId,
      authCookie,
      changeId,
      revisionNumber.toString(),
      {
        in_reply_to: commentId,
        path: filePath,
        message,
        unresolved,
      },
      ctx.sink
    );
  } catch (e) {
    const err = e as Error;
    const message = `Failed to create draft: ${err}`;
    ctx.sink.show({
      log: message,
      metrics: message,
      noErrorStatus: true,
    });
    void vscode.window.showErrorMessage(message);
  }
}
