// Copyright 2022 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as vscode from 'vscode';

/**
 * Options of an entry in an OpenSSH config file.
 *
 * Not all available OpenSSH options are here; they can be added as needed.
 */
export type SshConfigHost = {
  readonly Hostname?: string;
  readonly Port?: number;
  readonly CheckHostIP?: string;
  readonly ControlMaster?: string;
  readonly ControlPath?: string;
  readonly ControlPersist?: string;
  readonly IdentitiesOnly?: string;
  readonly IdentityFile?: string;
  readonly StrictHostKeyChecking?: string;
  readonly User?: string;
  readonly UserKnownHostsFile?: string;
  readonly VerifyHostKeyDNS?: string;
  readonly ProxyCommand?: string;
  readonly HostKeyAlias?: string;
};

/**
 * An entry in an OpenSSH config file (with a single host), including the Host part at the top.
 * Currently this is designed for use with the ssh-config lib.
 */
export type SshConfigHostEntry = SshConfigHost & {
  readonly Host?: string;
};

/**
 * Returns the path to the testing_rsa file bundled in the extension.
 *
 * The activation function of the device management feature ensures that the file
 * has a safe permission (0600).
 */
export function getTestingRsaPath(extensionUri: vscode.Uri): string {
  return vscode.Uri.joinPath(extensionUri, 'resources', 'testing_rsa').fsPath;
}

/**
 * Constructs a command line to run SSH for a host.
 *
 * @param host hostname, which can be in the format of 'hostname' or 'hostname:port'
 * @param extensionUri extension's installation path
 * @param extraOptions additional SSH options for your command
 * @param cmd remote command to execute
 * @returns a command line
 */
export function buildSshCommand(
  host: string,
  extensionUri: vscode.Uri,
  extraOptions: string[] = [],
  cmd?: string
): string[] {
  const [hostname, portname] = host.split(':');

  const args = ['ssh', '-i', getTestingRsaPath(extensionUri)];
  args.push(
    '-o',
    'StrictHostKeyChecking=no',
    '-o',
    'UserKnownHostsFile=/dev/null'
  );
  if (portname) {
    args.push('-p', portname);
  }
  if (extraOptions) {
    args.push(...extraOptions);
  }
  args.push(`root@${hostname}`);
  if (cmd) {
    args.push(cmd);
  }
  return args;
}
