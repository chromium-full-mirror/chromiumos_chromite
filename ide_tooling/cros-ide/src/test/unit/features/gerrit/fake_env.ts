// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as api from '../../../../features/gerrit/api';
import * as git from '../../../../features/gerrit/git';
import * as https from '../../../../features/gerrit/https';
import * as fakeData from './fake_data';

export type FakeGerritInitialOpts = Readonly<{
  accountsMe?: api.AccountInfo;
  internal?: boolean;
}>;

function COOKIE(repoId: git.RepoId): string {
  return `o=git-ymat.google.com=${
    repoId === 'cros' ? 'chromium-newtoken' : 'chrome-internal-newtoken'
  }`;
}

function OPTIONS(repoId: git.RepoId) {
  return {
    headers: {
      cookie: COOKIE(repoId),
    },
  };
}
const CHROMIUM_OPTIONS = OPTIONS('cros');
const CHROME_INTERNAL_OPTIONS = OPTIONS('cros-internal');

const CHROMIUM_GERRIT = 'https://chromium-review.googlesource.com';
const CHROME_INTERNAL_GERRIT =
  'https://chrome-internal-review.googlesource.com';

/** Fluent helper for creating mocking `http.getOrThrow`. */
export class FakeGerrit {
  private readonly httpsGetSpy;
  private readonly httpsPutSpy;

  private readonly baseUrl;
  private readonly reqOpts;

  private readonly idToChangeInfo = new Map<
    string,
    {
      info?: api.ChangeInfo;
      comments?: api.FilePathToBaseCommentInfos;
      drafts?: api.FilePathToBaseCommentInfos;
    }
  >();

  static initialize(opts?: FakeGerritInitialOpts): FakeGerrit {
    return new this(opts);
  }

  /**
   * Processes `internal` option and sets up `/a/accounts/me`.
   */
  private constructor(opts?: FakeGerritInitialOpts) {
    this.baseUrl = opts?.internal ? CHROME_INTERNAL_GERRIT : CHROMIUM_GERRIT;

    this.reqOpts = opts?.internal ? CHROME_INTERNAL_OPTIONS : CHROMIUM_OPTIONS;

    this.httpsGetSpy = spyOn(https, 'getOrThrow')
      .withArgs(`${this.baseUrl}/a/accounts/me`, this.reqOpts)
      .and.resolveTo(apiString(opts?.accountsMe));

    this.httpsPutSpy = spyOn(https, 'putJsonOrThrow');

    this.registerFakePut();
  }

  /**
   * Sets up `/changes/<changeId>?o=ALL_REVISIONS`, `/changes/<changeId>/comments`,
   * and `/a/changes/<changeId>/drafts`.
   */
  setChange(c: {
    id: string;
    info?: api.ChangeInfo;
    comments?: api.FilePathToBaseCommentInfos;
    drafts?: api.FilePathToBaseCommentInfos;
  }): FakeGerrit {
    const {id, info, comments, drafts} = c;

    this.idToChangeInfo.set(id, {info, comments, drafts});

    this.httpsGetSpy
      .withArgs(`${this.baseUrl}/changes/${c.id}?o=ALL_REVISIONS`, this.reqOpts)
      .and.callFake(async () => apiString(this.idToChangeInfo.get(c.id)?.info))
      .withArgs(`${this.baseUrl}/changes/${c.id}/comments`, this.reqOpts)
      .and.callFake(async () =>
        apiString(this.idToChangeInfo.get(c.id)?.comments)
      )
      .withArgs(`${this.baseUrl}/a/changes/${c.id}/drafts`, this.reqOpts)
      .and.callFake(async () =>
        apiString(this.idToChangeInfo.get(c.id)?.drafts)
      );

    return this;
  }

  private registerFakePut(): void {
    this.httpsPutSpy.and.callFake(async (url, postData, options) => {
      expect(options).toEqual(this.reqOpts);

      const createDraftRegex = new RegExp(
        `${this.baseUrl}/a/changes/([^/]+)/revisions/([^/]+)/drafts`
      );
      const m = createDraftRegex.exec(url);
      if (!m) throw new Error(`Unexpected URL: ${url}`);

      const changeId = m[1];
      const revisionId = m[2];

      const req = postData as api.CommentInput;

      const changeInfo = this.idToChangeInfo.get(changeId);
      if (!changeInfo) throw new Error(`Unknown change id: ${changeId}`);

      const comments = changeInfo.comments?.[req.path];
      if (!comments) throw new Error(`Unexpected path: ${req.path}`);

      const target = comments.find(comment => comment.id === req.in_reply_to);
      if (!target) {
        throw new Error(`Unexpected in_reply_to: ${req.in_reply_to}`);
      }

      expect(req.in_reply_to).toEqual(target.id);

      const wantRevisionId = changeInfo.info?.revisions?.[target.commit_id!]
        ?._number as number;
      expect(revisionId).toEqual(wantRevisionId.toString());

      const unresolved = req.unresolved ?? target.unresolved;
      const createCommentInfo = unresolved
        ? fakeData.unresolvedCommentInfo
        : fakeData.resolvedCommentInfo;

      const commentInfo = createCommentInfo({
        line: target.line,
        range: target.range,
        message: req.message,
        commitId: target.commit_id,
        inReplyTo: req.in_reply_to,
      });

      const newDraftComments: api.BaseCommentInfo[] = [
        ...(changeInfo.drafts?.[req.path] ?? []),
        commentInfo,
      ];

      changeInfo.drafts = {
        ...(changeInfo.drafts ?? {}),
        [req.path]: newDraftComments,
      };

      return apiString(commentInfo)!;
    });
  }
}

/** Build Gerrit API response from typed input. */
function apiString(data?: Object): string | undefined {
  if (!data) {
    return undefined;
  }
  return ')]}\n' + JSON.stringify(data);
}
