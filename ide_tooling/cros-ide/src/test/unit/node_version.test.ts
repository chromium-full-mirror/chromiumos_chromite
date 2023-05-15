// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import 'jasmine';
import * as commonUtil from '../../common/common_util';

const WANT_VERSION = /v14\..*/;

describe('Node', () => {
  it('should be configured following go/cros-ide-dev-guide', async () => {
    const version = await commonUtil.execOrThrow('node', ['--version']);
    expect(version.stdout).toMatch(WANT_VERSION);
  });
});
