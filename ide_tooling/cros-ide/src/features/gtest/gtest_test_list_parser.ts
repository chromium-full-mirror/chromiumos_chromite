// Copyright 2023 The ChromiumOS Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

type TestNameComponents = {
  readonly suite: string;
  readonly case: string;
} & (
  | {readonly parameterKind: 'none'}
  | {
      readonly parameterKind: 'value';
      readonly instantiation: string;
      readonly paramName: string;
    }
  | {
      // We do not distinguish between typed and type-parameterized tests, because their test name
      // format overlaps.
      readonly parameterKind: 'type';
      readonly instantiation: string;
      readonly typeName: string;
    }
);

/**
 * Gtest names can have a variety of formats:
 *
 * Non-parameterized tests:
 * - <Suite>.<Case> for `TEST(Suite, Case)`
 * - <Fixture>.<Case> for `TEST_F(Fixture, Case)`
 *
 * Value-parameterized tests:
 * - <Suite>.<Case>/<ParamName> for
 *   ```
 *   TEST_P(Suite, Case) {}
 *   INSTANTIATE_TEST_SUITE_P( , Suite, Case, Values(...))
 *                            ^- note how the instantiation param is empty.
 *   ```
 * - <Instantiation>/<Suite>.<Case>/<ParamName> for
 *   ```
 *   TEST_P(Suite, Case) {}
 *   INSTANTIATE_TEST_SUITE_P(Instantiation, Suite, Case, Values(...))
 *   ```
 *
 * Typed tests:
 * - <Suite>/<TypeName>.<Case> for
 *   ```
 *   TYPED_TEST_SUITE(Suite, Types(...))
 *   TYPED_TEST(Suite, Case)
 *   ```
 *
 * Type-parameterized tests:
 * - <Suite>/<TypeName>.<Case> for
 *   ```
 *   TYPED_TEST_SUITE_P(Suite)
 *   TYPED_TEST_P(Suite, Case)
 *   INSTANTIATE_TYPED_TEST_SUITE_P( , Suite, Types(...))
 *                                  ^- note how the instantiation param is empty.
 *   ```
 * - <Instantiation>/<Suite>/<TypeName>.<Case> for
 *   ```
 *   TYPED_TEST_SUITE_P(Suite)
 *   TYPED_TEST_P(Suite, Case)
 *   INSTANTIATE_TYPED_TEST_SUITE_P(Instantiation, Suite, Types(...))
 *   ```
 */
export class TestNameCollection {
  private readonly fullTestNames: ReadonlySet<string>;
  private readonly suiteAndCaseNames: ReadonlySet<string>;

  constructor(parsedTestNames: TestNameComponents[]) {
    const fullTestNames = new Set<string>();
    const suiteAndCaseNames = new Set<string>();

    parsedTestNames.forEach(parsedTestName => {
      suiteAndCaseNames.add(`${parsedTestName.suite}.${parsedTestName.case}`);

      let testName;
      switch (parsedTestName.parameterKind) {
        case 'none':
          testName = `${parsedTestName.suite}.${parsedTestName.case}`;
          break;
        case 'value':
          testName = `${parsedTestName.suite}.${parsedTestName.case}/${parsedTestName.paramName}`;
          if (parsedTestName.instantiation.length > 0) {
            testName = `${parsedTestName.instantiation}/${testName}`;
          }
          break;
        case 'type':
          testName = `${parsedTestName.suite}/${parsedTestName.typeName}.${parsedTestName.case}`;
          if (parsedTestName.instantiation.length > 0) {
            testName = `${parsedTestName.instantiation}/${testName}`;
          }
          break;
      }

      fullTestNames.add(testName);
    });

    this.fullTestNames = fullTestNames;
    this.suiteAndCaseNames = suiteAndCaseNames;
  }

  hasFullTestName(fullTestName: string): boolean {
    return this.fullTestNames.has(fullTestName);
  }

  hasSuiteAndCaseName(suiteAndCaseName: string): boolean {
    return this.suiteAndCaseNames.has(suiteAndCaseName);
  }

  getFullTestNames(): ReadonlySet<string> {
    return this.fullTestNames;
  }

  getSuiteAndCaseNames(): ReadonlySet<string> {
    return this.suiteAndCaseNames;
  }
}

function parseLine(line: string): {
  value: string;
  isIndented: boolean;
  comment: string;
} {
  const commentIdx = line.indexOf('#');
  let value = (commentIdx >= 0 ? line.slice(0, commentIdx) : line).trim();
  if (value.endsWith('.')) {
    value = value.slice(0, -1);
  }
  return {
    value,
    isIndented: line.startsWith('  '),
    comment: commentIdx >= 0 ? line.slice(commentIdx) : '',
  };
}

/**
 * Parses output from a gtest executable run with the --gtest_list_tests flag and returns the
 * tests names as an instance of `TestNameCollection`.
 */
export function parse(stdout: string): TestNameCollection | Error {
  const allTestNameComponents: TestNameComponents[] = [];
  let testNameComponents: TestNameComponents | null = null;
  const rawLines = stdout.trim().split('\n');
  for (let i = 0; i < rawLines.length; ++i) {
    const rawLine = rawLines[i]!;
    const nextRawLine = rawLines[i + 1] ?? null;
    const {value, isIndented, comment} = parseLine(rawLine);

    if (!isIndented) {
      const parts = value.split('/');
      if (parts.length === 1) {
        // This is either a non-parameterized test, or a value-parameterized test without an
        // instantiation name. This line contains the name of the test suite/fixture:
        // ```
        // TestSuite.                       // <- this line
        //   TestCase
        // ```
        // ```
        // ParameterizedTest.                // <- this line
        //   TestCase/0  # GetParam() = ...
        // ```
        const suite = parts[0]!;
        if (nextRawLine && nextRawLine.includes('# GetParam()')) {
          testNameComponents = {
            parameterKind: 'value',
            instantiation: '',
            suite,
            case: '',
            paramName: '',
          };
        } else {
          testNameComponents = {parameterKind: 'none', suite, case: ''};
        }
      } else if (parts.length === 2) {
        // This is either a value-parameterized test with an instantiation name, a typed test, or a
        // type-parameterized test without an instantiation name:
        // ```
        // Instantiation/ParameterizedTest.            // <- this line
        //   TestCase/0  # GetParam() = ...
        // ```
        // ```
        // TypedTest/0.  # TypeParam = ...            // <- this line
        //   TestCase
        // ```
        // ```
        // TypeParameterizedTest/0.  # TypeParam = ... // <- this line
        //   TestCase
        // ```
        if (comment.startsWith('# TypeParam')) {
          testNameComponents = {
            parameterKind: 'type',
            instantiation: '',
            suite: parts[0],
            typeName: parts[1],
            case: '',
          };
        } else {
          testNameComponents = {
            parameterKind: 'value',
            instantiation: parts[0],
            suite: parts[1],
            case: '',
            paramName: '',
          };
        }
      } else if (parts.length === 3) {
        // This is a type-parameterized test. This line contains the name of the instantiation, the
        // test suite/fixture, and the type index:
        // ```
        // Instantiation/TypeParameterizedTest/0.  # TypeParam = ... // <- this line
        //   TestCase
        // ```
        testNameComponents = {
          parameterKind: 'type',
          instantiation: parts[0],
          suite: parts[1],
          typeName: parts[2],
          case: '',
        };
      } else {
        return new Error(`Unable to parse test list line: "${rawLine}"`);
      }
    } else {
      if (testNameComponents === null) {
        return new Error(
          `Unable to parse test list: Expected at least one line starting without "  " preceeding any line starting with "  ": "${rawLine}"`
        );
      }

      const parts = value.split('/');
      switch (testNameComponents.parameterKind) {
        case 'none':
        case 'type':
          if (parts.length !== 1) {
            return new Error(
              `Unable to parse test list line "${rawLine}" for a ${
                testNameComponents.parameterKind
              } test: ${JSON.stringify(testNameComponents)}`
            );
          }
          allTestNameComponents.push({...testNameComponents, case: parts[0]});
          break;
        case 'value':
          if (parts.length !== 2) {
            return new Error(
              `Unable to parse test list line "${rawLine}" for a value-parameterized test: ${JSON.stringify(
                testNameComponents
              )}`
            );
          }
          allTestNameComponents.push({
            ...testNameComponents,
            case: parts[0],
            paramName: parts[1],
          });
          break;
      }
    }
  }
  return new TestNameCollection(allTestNameComponents);
}
