// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// Executable to build ChromiumIDE extension.

import {build, BuildOptions} from 'esbuild';

const VIEW_ENTRY_POINTS = {
  vnc: './views/src/vnc.ts',
  syslog_view: './views/src/features/device_management/syslog/view.tsx',
};

async function buildWebview(production: boolean) {
  // Bundle files
  const options: BuildOptions = {
    entryPoints: VIEW_ENTRY_POINTS,
    bundle: true,
    target: 'es2020',
    outdir: './dist/views',
    minify: production,
    sourcemap: !production,
    tsconfig: './views/tsconfig.json',
  };
  await build(options);
}

async function main() {
  const production = process.env.NODE_ENV === 'production';

  // TODO(oka): build extension as well.
  await buildWebview(production);
}

main().catch(e => {
  process.stderr.write(`${e}`);
  // eslint-disable-next-line no-process-exit
  process.exit(1);
});
