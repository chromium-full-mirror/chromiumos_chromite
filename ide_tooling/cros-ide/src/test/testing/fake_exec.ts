// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {
  ExecOptions,
  ExecResult,
  setExecForTesting,
  exec as commonUtilExec,
} from '../../common/common_util';
import {cleanState} from './clean_state';

type ExecType = typeof commonUtilExec;

/**
 * Returns execution result or undefined if args is not handled.
 *
 * The result can be just a string, which will be returned as stdout with zero exit status.
 * `ExecResult`, can emulate return with stderr and non-zero exit status.
 * `Error` can be used to simulate that the command was not found.
 */
export type Handler = (
  args: string[],
  options: ExecOptions
) => Promise<string | ExecResult | Error | undefined>;

export function exactMatch(
  wantArgs: string[],
  handle: (options: ExecOptions) => Promise<string | ExecResult | Error>
): Handler {
  return async (args, options) => {
    if (
      wantArgs.length === args.length &&
      wantArgs.every((x, i) => x === args[i])
    ) {
      return await handle(options);
    }
    return undefined;
  };
}

/**
 * Returns a handler that first checks if the prefix of the given args matches with
 * wantPrefix and if so calls handle with the args without the prefix.
 */
export function prefixMatch(wantPrefix: string[], handle: Handler): Handler {
  return async (args, options) => {
    if (
      wantPrefix.length <= args.length &&
      wantPrefix.every((x, i) => x === args[i])
    ) {
      return await handle(args.slice(wantPrefix.length), options);
    }
    return undefined;
  };
}

export function lazyHandler(f: () => Handler): Handler {
  return async (args, options) => {
    return f()(args, options);
  };
}

/**
 * FakeExec class is an extension of a jasmine spy object that provides utilities to install canned
 * responses.
 */
export class FakeExec
  // Spy interface is a hybrid type and is a callable. We omit the callable from the interface here
  // because a class cannot be a callable. It's presumably OK since test code wouldn't call on a
  // spy.
  implements Pick<jasmine.Spy<ExecType>, 'calls' | 'withArgs' | 'and'>
{
  readonly handlers: Map<string, Handler[]> = new Map();

  constructor(private readonly spy: jasmine.Spy<ExecType>) {}

  /**
   * @deprecated install handlers via standard jasmine methods on spy object.
   */
  on(name: string, ...handle: Handler[]): FakeExec {
    if (!this.handlers.has(name)) {
      this.handlers.set(name, []);
    }
    this.handlers.get(name)!.push(...handle);
    return this;
  }
  async fakeExec(
    name: string,
    args: string[],
    options: ExecOptions = {}
  ): Promise<ExecResult | Error> {
    for (const handler of this.handlers.get(name) || []) {
      const result = await handler(args, options);
      if (result === undefined) {
        continue;
      }
      if (typeof result === 'string') {
        return {exitStatus: 0, stdout: result, stderr: ''};
      }
      return result;
    }
    throw new Error(`${name} ${args.join(' ')}: not handled`);
  }

  /**
   * Installs fixed stdout. The last optional parameter is if given used to match the options given
   * to exec.
   */
  installStdout(
    name: jasmine.Expected<string>,
    args: jasmine.Expected<string[]>,
    stdout: string,
    options?: jasmine.Expected<ExecOptions>
  ): void {
    this.installCallback(name, args, () => stdout, options);
  }

  /**
   * Installs a callback. If the callback returns a string, it's converted to a successful result
   * with the stdout being the returned string and stderr empty. The last optional parameter is if
   * given used to match the options given to exec.
   */
  installCallback(
    name: jasmine.Expected<string>,
    args: jasmine.Expected<string[]>,
    callback: (
      name: string,
      args: string[],
      options?: ExecOptions
    ) => Promise<Awaited<ReturnType<ExecType>> | string> | string,
    options: jasmine.Expected<ExecOptions> = jasmine.anything()
  ): void {
    this.withArgs(name, args, options).and.callFake(
      async (name, args, options) => {
        const res = await callback(name, args, options);
        if (typeof res === 'string') {
          return {exitStatus: 0, stdout: res, stderr: ''};
        }
        return res;
      }
    );
  }

  // jasmine.Spy APIs follow.
  readonly calls = this.spy.calls;
  readonly withArgs = this.spy.withArgs.bind(this.spy);
  readonly and = this.spy.and;
}

/**
 * Installs fake exec for testing. This function should be called in describe.
 *
 * Calling this function replaces commonUtil.exec with a fake, and returns a
 * handler to it. It internally uses cleanState to create fresh instances per
 * test.
 */
export function installFakeExec(): {fakeExec: FakeExec} {
  const fakeExec = new FakeExec(jasmine.createSpy('exec'));

  const state = cleanState(() => {
    const exec = jasmine.createSpy('exec', commonUtilExec);

    const fe = new FakeExec(exec);
    Object.assign(fakeExec, fe); // clear handlers

    exec.and.callFake(fe.fakeExec.bind(fe));

    return {undo: setExecForTesting(exec)};
  });
  afterEach(() => {
    state.undo();
  });

  return {fakeExec};
}
