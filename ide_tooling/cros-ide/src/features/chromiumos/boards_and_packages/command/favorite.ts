// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

import * as config from '../../../../services/config';

export async function addFavorite(category: string): Promise<void> {
  const favorite = new Set(
    config.boardsAndPackages.favoriteCategories.get() ?? []
  );
  favorite.add(category);
  await config.boardsAndPackages.favoriteCategories.update([...favorite]);
}

export async function deleteFavorite(category: string): Promise<void> {
  const favorite = new Set(
    config.boardsAndPackages.favoriteCategories.get() ?? []
  );
  favorite.delete(category);
  await config.boardsAndPackages.favoriteCategories.update([...favorite]);
}
