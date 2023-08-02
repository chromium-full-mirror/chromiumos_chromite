// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

/**
 * Immutable data structure representing breadcrumbs to reach a tree item
 * from the root node.
 */
export class Breadcrumbs {
  /** The empty breadcrumbs. */
  static readonly EMPTY = new this([]);

  /** Creates a breadcrumbs from the strings. */
  static from(...breadcrumbs: string[]): Breadcrumbs {
    return new this(breadcrumbs);
  }

  private constructor(readonly breadcrumbs: readonly string[]) {}

  /** Returns a new Breadcrumbs. */
  pushed(token: string): Breadcrumbs {
    return new Breadcrumbs([...this.breadcrumbs, token]);
  }

  /** Returns whether the breadcrumbs starts with the prefix. */
  startsWith(prefix: Breadcrumbs): boolean {
    for (let i = 0; i < prefix.breadcrumbs.length; i++) {
      if (prefix.breadcrumbs[i] !== this.breadcrumbs[i]) {
        return false;
      }
    }
    return true;
  }

  /** Returns the length of the breadcrumbs. */
  get length(): number {
    return this.breadcrumbs.length;
  }

  /**
   * Returns the parent breadcrumbs. It returns an empty breadcrumbs for an
   * empty breadcrumbs.
   */
  parent(): Breadcrumbs {
    return new Breadcrumbs(
      this.breadcrumbs.slice(0, this.breadcrumbs.length - 1)
    );
  }
}
