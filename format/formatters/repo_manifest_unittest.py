# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the repo_manifest module."""

import pytest

from chromite.format.formatters import repo_manifest


# None means input is already formatted to avoid having to repeat.
TEST_CASES = (
    (
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest/>
""",
        None,
    ),
    # Project element without children is collapsed.
    (
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project path="path"
           name="name">
  </project>
</manifest>
""",
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project path="path"
           name="name" />

</manifest>
""",
    ),
    # Multiple newlines are collapsed.
    (
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project path="path"
           name="name" />


  <project path="path"
           name="name" />
</manifest>
""",
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <project path="path"
           name="name" />

  <project path="path"
           name="name" />
</manifest>
""",
    ),
    # Comments are indented correctly.
    (
        """<?xml version="1.0" encoding="UTF-8"?>
<!-- yes
       too much
no
\t
maybe -->
<!--x-->
<manifest></manifest>
""",
        """<?xml version="1.0" encoding="UTF-8"?>
<!-- yes
     too much
     no

     maybe -->
<!-- x -->
<manifest/>
""",
    ),
    (
        """<?xml version="1.0" encoding="UTF-8"?>
<!--
-->
<!--

-->
<!-- --><manifest/>""",
        """<?xml version="1.0" encoding="UTF-8"?>
<!--  -->
<!--  -->
<!--  -->
<manifest/>
""",
    ),
    # Whitespace text nodes are handled as expected, and <notice> text nodes are
    # only trimmed, and the closing block is aligned on a newline.
    (
        """<?xml version="1.0" encoding="UTF-8"?>
        <manifest>

        <project name="name" path="path" />


<notice>An announcement!\t\t</notice>
        </manifest>""",
        """<?xml version="1.0" encoding="UTF-8"?>
<manifest>

  <project path="path"
           name="name" />

  <notice>An announcement!
  </notice>
</manifest>
""",
    ),
)


# Use a separate variable to avoid pytest log spam.
@pytest.mark.parametrize("data,exp", TEST_CASES)
def test_check_format(data, exp) -> None:
    """Verify inputs match expected outputs."""
    if exp is None:
        exp = data
    assert exp == repo_manifest.Data(data)


FAILING_TEST_CASES = (
    # Fails because <notice> should only contain text nodes
    """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <notice>An announcement!
    <project path="path"
             name="name" />
  </notice>
</manifest>""",
    # Fails because <notice> must contain a child text node
    """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <notice/>
</manifest>""",
)


@pytest.mark.parametrize("data", FAILING_TEST_CASES)
def test_format_failures(data) -> None:
    """Verify inputs raise AssertionErrors as expected."""
    with pytest.raises(AssertionError):
        repo_manifest.Data(data)
