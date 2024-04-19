# Chromite Development: Starter Guide

This doc tries to give an overview and head start to anyone just starting out on
Chromite development.

[TOC]

## Background

Before you get started on Chromite, we recommend that you go through ChromeOS
developer guides at
[external (first)](https://www.chromium.org/chromium-os/developer-library/guides/development/developer-guide/)
and then [goto/chromeos-building](http://goto/chromeos-building) for internal.
The
[Gerrit starter guide](https://www.chromium.org/chromium-os/developer-library/guides/development/git-and-gerrit-intro/)
may also be helpful. You should flash a built image on a test device (Ask around
for one!).

Chromite was intended to be the unified codebase for anything related to
building ChromeOS/ChromiumOS. Currently, it is the codebase responsible for
several things including: building the OS from the requisite packages for the
necessary board (`parallel_emerge`), driving the infrastructure build workflow
(CBuildBot), hosting a Google App Engine App, and providing utility functions
for various scripts scattered around ChromeOS repositories. It is written for
the most part in Python with some Bash sprinkled in.

## Directory Overview

You can use
[Code Search](https://source.chromium.org/chromiumos/chromiumos/codesearch/)
to lookup things in
[Chromite](https://source.chromium.org/chromiumos/chromiumos/codesearch/+/HEAD:chromite/)
or Chromium OS in general.

Non-public code has a separate
[internal Code Search site](https://source.corp.google.com/).
It's organized into different ["repositories"](https://source.corp.google.com/repos),
and we have two:
["Chrome OS - Internal"](https://source.corp.google.com/chromeos_internal) (only
internal repositories) &
["Chrome OS - Public"](https://source.corp.google.com/chromeos_public) (only
public repositories).
You can add a search query for a single combined view (public & private) in the
[Saved Queries settings page](https://source.corp.google.com/settings/savedqueries).
Use the query `package:^chromeos_(internal|public)$`.
NB: The "Chrome OS - Public" repository is exactly the same as the public
source.chromium.org site.

### chromite/api

The Chromite API for the CI system. The API exposes a subset of the chromite
functionality that needs to be strictly maintained as much as possible.

### chromite/cbuildbot

CBuildBot is the collection of entire code that runs on both the parent and the
child build machines. It kicks off the individual stages in a particular build.
It is a configurable bot that builds ChromeOS.

This project is heavily deprecated as everything has moved to LUCI recipes and
the BuildAPI interface. Do not use this project for anything new.

### chromite/cbuildbot/builders

This folder contains configurations of the different builders in use. Each has
its own set of stages to run usually called under RunStages function. Most
builders used regularly are derived from SimpleBuilder class.

### chromite/cbuildbot/stages

Each file here has implementations of stages in the build process grouped by
similarity. Each stage usually has PerformStage as its primary function.

### chromite/docs

Additional documentation.

### chromite/lib

Code here is expected to be imported whenever necessary throughout Chromite.

A notable exception: see [chromite/utils](#chromite_utils).

### chromite/scripts

Unlike lib, code in scripts will not and should not be imported anywhere.
Instead they are executed as required in the build process. Each executable is
linked to either `wrapper3.py` or `vpython_wrapper.py`. Some of these links
are in `chromite/bin`. When we want to make the tool available to developers
(e.g. in `$PATH`), we put the symlink under `bin/`. If it's more "internal"
usage, then we use `scripts/`.

The wrapper figures out the directory of the executable script and the
`$PYTHONPATH`. Finally, it invokes the correct Python installation by moving up
the directory structure to find which git repo is making the call.

Do not use `virtualenv_wrapper.py` in new code.

### chromite/shell

This directory is a staging area for migrating shell scripts to Python.

### chromite/service

These files act as the centralized business logic for processes, utilizing lib
for the implementation details. Any process that's implemented in chromite
should generally have an entry point somewhere in a service such that it can be
called from a script, the API, or anywhere else in lib where the process may be
useful.

### chromite/third_party

This folder contains all the third_party python libraries required by Chromite.
You need a very strong reason to add any library to the current list. Please
confirm with the owners beforehand.

### chromite/utils

This folder contains smaller, generic utility functionality that is not tied to
any specific entities in the codebase that would make them more at home in a lib
module.

Code must not import modules outside of utils/ as this directory is intended to
be standalone & isolated. This restriction does *not* apply to unittest modules.
Those may freely use Chromite APIs (e.g. chromite.lib.*).

### chromite/infra

This folder contains the chromite-specific infra repos.

### chromite/systemd

Systemd unit files for services provided by chromite.

### chromite/test

This folder contains test-only utilities and helper functions used to make
writing tests in other modules easier.

### chromite/*

There are smaller folders with miscellaneous functions like config, licencing,
cidb, etc.

## Testing your Chromite changes

Before any testing, you should check your code for lint errors with:

```shell
$ cros lint <filename>
```

### Unit Tests

Chromite now uses [pytest](https://docs.pytest.org/en/latest/) for running and
writing unit tests. All new code & tests should be written with the expectation
to be run under pytest.

Pytest is responsible for running unit tests under Python 3, with the legacy
unit test runner `scripts/run_tests` responsible for running unit tests under
Python 2.

### Running Chromite's unit tests

Chromite provides a single `run_tests` wrapper in the top dir that runs all the
unittests for you.
It's the same as `scripts/run_tests`, but in an easier-to-find location.

Every Python file in Chromite is accompanied by a corresponding `*_unittest.py`
file. Running a particular file's unit tests is best done via
```shell
$ ./run_tests example_file_unittest.py
```

This script initializes a Python 3 virtualenv with necessary test dependencies
and runs `pytest` inside that virtualenv over all tests in Chromite, with the
configuration specified in [pytest.ini](./pytest.ini). The default configuration
runs tests in parallel and skips some tests known to be flaky or take a very
long time.

Tests will not run in a standalone git checkout of chromite. Use the repo-based
flow described above to obtain a functional-testing environment.

### Network Tests

By default, any test that reaches out to the network (those wrapped in a
`@cros_test_lib.pytestmark_network_test` decorator) will not be run. To include
these tests, add the `--network` option:
```shell
$ ./run_tests --network -- ...
```

### Writing unit tests

Chromite's unit tests make use of pytest
[fixtures](https://doc.pytest.org/en/latest/fixture.html). Fixtures that are
defined in a
[`conftest.py`](https://doc.pytest.org/en/latest/fixture.html#conftest-py-sharing-fixture-functions)
file are visible to tests in the same directory and all child directories. If
it's unclear where a test function is getting an argument from, try searching
for a fixture with that argument's name in a `conftest.py` file.

Be sure to consult pytest's
[excellent documentation](https://doc.pytest.org/en/latest/contents.html) for
guidance on how to take advantage of the features pytest offers when writing
unit tests.

Unit tests must clean up after themselves and in particular must not leak child
processes after running. There is no guaranteed order in which tests are run or
that tests are even run in the same process.

### Debugging unit tests

Pass flag
[`--pdb`](https://docs.pytest.org/en/6.2.x/usage.html#dropping-to-pdb-python-debugger-at-the-start-of-a-test)
to pytest in order to start an interactive Python debugger on errors or
`KeyboardInterrupt` (e.g. Ctrl+C):
```shell
$ ./run_tests -- --pdb
```
The easiest way to set breakpoints is via the
[`breakpoint()`](https://docs.python.org/3/library/functions.html#breakpoint)
built-in function.

If you wish to attach an external debugger, invoke `./run_tests` with the
`--wait-for-debugger` flag. It is recommended to first set any desired
breakpoints with the `breakpoint()` built-in function, and to narrow down the
test runner to a specific unit test, e.g.
```shell
$ ./run_tests --wait-for-debugger lib/portage_util_unittest.py
```
You may attach your external debugger as soon as `run_tests` prints a line that
looks like this:
```
16:51:38: NOTICE: Waiting for a debugger to connect to port 5678...
```
As an example, you may attach the VSCode built-in
[debugger](https://code.visualstudio.com/docs/editor/debugging), which requires
the
[Python](https://marketplace.visualstudio.com/items?itemName=ms-python.python)
extension. Bring up the "Run and Debug" view, then attach the debugger using
the
[`Python: Attach`](https://chromium.googlesource.com/chromiumos/chromite/+/97144c1b68e1c888512de8af23b2016808e3b236/.vscode/launch.json#24)
launch configuration. See
[screencast](https://screencast.googleplex.com/cast/NTUyNjU1NDk5Mjk2NzY4MHxjZDlhNmE0NS01Mw)
(Googlers only).

### Commit Queue

Once you mark your CL as Commit-Queue +1 (dry run) or +2 (full run) on the
[Chromium Gerrit](https://chromium-review.googlesource.com), the CQ will pick
up your change and run a comprehensive set of tests. Once a CL is verified by
CQ, it is merged into the codebase. A dry run runs the same tests as a full
run, but doesn't submit the CL when complete.

## How does ChromeOS build work?

Refer to these
[talk slides](https://docs.google.com/presentation/d/1q8POSy8-LgqVvZu37KeXdd2-6F_4CpnfPzqu1fDlnW4)
on ChromeOS Build Overview.
