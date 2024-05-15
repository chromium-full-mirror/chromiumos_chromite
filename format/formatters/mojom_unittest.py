# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the mojom module."""

import pytest

from chromite.format import formatters


# pylint: disable=line-too-long


# None means input is already formatted to avoid having to repeat.
@pytest.mark.parametrize(
    "data,exp",
    (
        ("", None),
        # Enum
        (
            """module test;
enum Foo {kValue = 0, kAnotherValue = -3, [MinVersion=1] kExtra = 4 };
interface I { [Stable] enum NestedEnum { kTrue, kFalse }; };""",
            """module test;

enum Foo {
  kValue = 0,
  kAnotherValue = -3,
  [MinVersion=1] kExtra = 4,
};

interface I {
  [Stable]
  enum NestedEnum {
    kTrue,
    kFalse,
  };
};
""",
        ),
        # Struct
        (
            "module foo; [Native] struct Native;",
            """module foo;

[Native]
struct Native;
""",
        ),
        (
            """module foo; struct Empty {

};""",
            """module foo;

struct Empty {};
""",
        ),
        (
            """module foo;
struct Foobar {
            \thandle over_indented;
  array<foo.bar.mojom.LongNamedType> very_long_name_that_needs_to_wrap_past_this_line;
  string simple_field;
  int32
              weird_wrap;
  uint32 x=24;
  handle<  platform\t>moo;
  [MinVersion=1] bool foo;

   mojo_base.mojom.TimeDelta? first_input_delay_after_back_forward_cache_restore;

  map<string, array<foo.bar.mojom.LongNamedType>> very_long_name_that_needs_to_wrap_past_this_line;
};""",
            """module foo;

struct Foobar {
  handle over_indented;
  array<foo.bar.mojom.LongNamedType>
      very_long_name_that_needs_to_wrap_past_this_line;
  string simple_field;
  int32 weird_wrap;
  uint32 x = 24;
  handle<platform> moo;
  [MinVersion=1]
  bool foo;

  mojo_base.mojom.TimeDelta? first_input_delay_after_back_forward_cache_restore;

  map<string, array<foo.bar.mojom.LongNamedType>>
      very_long_name_that_needs_to_wrap_past_this_line;
};
""",
        ),
        # Interface
        (
            """module test;

[Stable, SandboxType=kSecure, Extensible]
interface Interface {
  // First.
  Mount@0(uint32 uid, int32 mount_id) => (handle? fd);

  // Line Break -----.

  // Second.
  [MinVersion] DoAThing() => (pending_remote<VeryLongAbstractTypeNameThatDoesNotFit> long_response_type,
    map<uint32, array<foo.bar.mojom.LongTypeNameThatAlsoMakesForInterestingWrap>> tt);

  // Third.
  Another([MinVersion=2] handle<platform>? param);

  // Fourth.
  CountFeature(WebFeature feature);
};""",
            """module test;

[Stable, SandboxType=kSecure, Extensible]
interface Interface {
  // First.
  Mount@0(uint32 uid, int32 mount_id) => (handle? fd);

  // Line Break -----.

  // Second.
  [MinVersion]
  DoAThing()
      => (pending_remote<VeryLongAbstractTypeNameThatDoesNotFit>
              long_response_type,
          map<uint32,
              array<foo.bar.mojom.LongTypeNameThatAlsoMakesForInterestingWrap>>
                  tt);

  // Third.
  Another([MinVersion=2] handle<platform>? param);

  // Fourth.
  CountFeature(WebFeature feature);
};
""",
        ),
    ),
)

# pylint: enable=line-too-long


def test_check_format(data, exp) -> None:
    """Verify inputs match expected outputs."""
    if exp is None:
        exp = data
    assert exp == formatters.mojom.Data(data)


@pytest.mark.parametrize(
    "data",
    ("module test; interface I {",),
)
def test_format_failures(data) -> None:
    """Verify inputs raise ParseErrors as expected."""
    with pytest.raises(formatters.ParseError):
        formatters.mojom.Data(data)
