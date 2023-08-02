// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

export const VIRTUAL_BOARDS_HOST = 'host';

/**
 * All the values that can be set as the contextValue of a tree item.
 */
export enum ViewItemContext {
  // Set for board item.
  BOARD = 'board',
  // Set for package name item.
  PACKAGE = 'package',
}
