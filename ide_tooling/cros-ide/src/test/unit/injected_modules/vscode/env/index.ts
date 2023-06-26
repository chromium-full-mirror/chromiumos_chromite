// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import {LogLevel} from '../log_level';
import {UIKind} from '../ui_kind';
import type * as vscode from 'vscode';

export const appHost = 'fakeAppHost';
export const appName = 'fakeAppName';
export const appRoot = 'fakeAppRoot';
export const clipboard: vscode.Clipboard = {
  readText(): Thenable<string> {
    throw new Error('Unimplemented in injected_modules');
  },
  writeText(_value: string): Thenable<void> {
    throw new Error('Unimplemented in injected_modules');
  },
};
export const isNewAppInstall = false;
export const isTelemetryEnabled = false;
export const language = 'en';
export const logLevel: vscode.LogLevel = LogLevel.Debug;
export const machineId = 'fakeMachineId';
export const remoteName: string | undefined = undefined;
export const sessionId = 'fakeSessionId';
export const shell = 'fakeShell';
export const uiKind = UIKind.Desktop;
export const uriScheme = 'fake';
