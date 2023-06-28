// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as fs from 'fs';
import * as path from 'path';
import {ChrootService, Packages} from '../../../services/chromiumos';
import * as testing from '../../testing';
import {getChromiumosDirectory} from '../common/fs';

describe('C++ xrefs in platform2', () => {
  testing.installVscodeDouble();

  const chromiumos = getChromiumosDirectory();

  it('expects chroot to exist', () => {
    expect(fs.existsSync(path.join(chromiumos, 'chroot'))).toBeTrue();
  });

  const chrootService = ChrootService.maybeCreate(chromiumos, false)!;
  const packages = Packages.getOrCreate(chrootService);

  // Create a test case for each platform2 directory containing a C++ file.
  const platform2 = path.join(chromiumos, 'src/platform2');

  for (const cppFile of listCppFileRepresentatives(platform2)) {
    describe(`for ${cppFile}`, () => {
      it('can find package to compile', async () => {
        const packageInfo = await packages.fromFilepath(cppFile);

        expect(packageInfo).toBeTruthy();
      });
    });
  }
});

/**
 * Rather than listing up all the C++ files, list up all the directories
 * containing a C++ file, and pick one C++ file from each such a directory.
 */
function listCppFileRepresentatives(dir: string, res: string[] = []): string[] {
  let cppFileChosen = false;

  for (const name of fs.readdirSync(dir)) {
    const file = path.join(dir, name);
    const stat = fs.lstatSync(file);

    if (stat.isSymbolicLink()) {
      continue;
    }
    if (stat.isDirectory()) {
      listCppFileRepresentatives(file, res);
      continue;
    }
    if (!cppFileChosen && ['.c', '.cc', '.cpp'].includes(path.extname(file))) {
      res.push(file);
      cppFileChosen = true;
    }
  }

  return res;
}
