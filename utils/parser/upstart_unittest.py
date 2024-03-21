# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test the upstart module."""

import pytest

from chromite.utils.parser import upstart


TEST_CASES = (
    ("", upstart.Job()),
    (
        """# comment

author "me"
description "desc"

oom score never

import FOO
export BAR
env MOO

exec /bin/true \\
  --version
pre-start script
  prestart
end script
post-start script
  poststart
end script
pre-stop script
  prestop
end script
post-stop script
  poststop
end script
""",
        upstart.Job(
            "me",
            "desc",
            "never",
            "/bin/true   --version",
            "  prestart\n",
            "  poststart\n",
            "  prestop\n",
            "  poststop\n",
        ),
    ),
    ("oom never", upstart.Job(oom="never")),
    ("oom score -100", upstart.Job(oom="-100")),
    ("oom score never", upstart.Job(oom="never")),
)


@pytest.mark.parametrize("data,exp", TEST_CASES)
def test_parser_good_input(data: str, exp: upstart.Job) -> None:
    """Verify parser on good inputs."""
    job = upstart.parse(data)
    assert job == exp


BAD_TEST_CASES = (
    # Bad author lines.
    "author",
    "author YOU",
    # Bad description lines.
    "description",
    "description YES",
    # Bad exec lines.
    "exec",
    # Bad oom lines.
    "oom",
    "oom sc0re",
    "oom score",
    # Bad pre/post stanzas.
    "pre-start",
    "pre-stop",
    "post-start",
    "post-stop",
    # Bad script stanzas.
    "script",
    # Multiple exec lines.
    "exec /bin/true\nexec /bin/false",
    # Multiple script lines.
    """
script
  /bin/true
end script
script
  /bin/true
end script
    """,
    # Multiple exec + script lines.
    """
exec /bin/true
script
  /bin/false
nend script
""",
    # Unknown tokens.
    "foo",
)


@pytest.mark.parametrize("data", BAD_TEST_CASES)
def test_parser_bad_input(data: str) -> None:
    """Check parser on invalid inputs."""
    with pytest.raises(upstart.Error):
        upstart.parse(data)
