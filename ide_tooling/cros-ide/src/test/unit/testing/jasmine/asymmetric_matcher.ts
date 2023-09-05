// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This class defines custom AsymmetricMatcher. The type is somehow referred to as
// AsymmetricEqualityTester in the official document.
// https://jasmine.github.io/api/4.1/AsymmetricEqualityTester.html

/**
 * Returns a matcher that will succeed if the actual value is an Array that starts with the given
 * prefix.
 */
export function arrayWithPrefix<T>(
  ...prefix: T[]
): jasmine.AsymmetricMatcher<T[]> {
  return {
    asymmetricMatch(other: T[]): boolean {
      return (
        prefix.length <= other.length && prefix.every((t, i) => other[i] === t)
      );
    },
    jasmineToString(): string {
      return `<an array starts with ${prefix}>`;
    },
  };
}
