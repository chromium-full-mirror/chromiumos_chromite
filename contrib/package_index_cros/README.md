# Package index pregenerator

A script to generate build artifacts for Chrome OS packages.

WARNING: this script is only manually tested for very limited purposes and
by very limited engineer. The engineer tried to list possible
pitfalls here but certainly missed something. Use at your own
risk.

## Overview

The ultimate goal for the script is to generate input for
[`package_index`] which makes references available for Chrome on Codesearch
page. The script should help to reuse [`package_index`] for ChromeOS purposes.

Currently, it is able to generate, fix and merge:

- compile_commands.json
- gn_targets.json
- build dir (generated source files, ninja artifacts etc)

## Usage

1. Clone [`package_index_cros`] somewhere in Chrome OS checkout. E.g
   `chromeos/package_index_cros`, `chromeos/tmp/package_index_cros`. The
   script needs `chromite` in one of parent directories.

   You can clone the script as part of infra repo (see
   [Chromium checkout instructions]):

   ```bash
   fetch --nohooks infra
   ```

1. Make `package_index_cros/main.py` executable.
1. Run `/path/to/package_index_cros/main.py --help` for details.

## Local usage

NOTE: same chroot notation used as in
[ChromiumOS](https://chromium.googlesource.com/chromiumos/docs/+/HEAD/developer_guide.md#typography-conventions).

Side effect of the `compile_commands.json` generator is that it can be used
locally with clangd.

1. Install [`package_index_cros`] with steps above.
1. Install [clangd].
1. Build packages and preserve build targets:

   ```bash
   (inside)
   $ cros-workon-${BOARD} start package1 package2 package3
   $ FEATURES="noclean test" emerge-${BOARD} package1 package2 package3
   ```

1. Generate `compile_commands.json`:

   ```bash
   (outside)
   $ /path/to/package_index_cros/main.py \
     --with-tests \
     --compile-commands \
     /path/to/clangd/compile/commands/dir/compile_commands.json \
     package1 package2 package3
   ```

   Where:

   - `--with-tests` indicates that packages were built with tests.
   - `--compile-commands /some/path/compile_commands.json` will store
     tells the script to generate compile commands and store it in given file.
   - packages: which packages you want to include. Compile commands will
     include these packages plus their dependencies of unlimited depth.
     You can skip packages, then compile commands will be generated for all
     available and supported packages (may take a while because of build).
   - Optional `--build-dir ${some_dir}` will create a dir and merge all
     packages' build dirs and generated files there. Can be useful when
     working with proto files but fully optional.

   NOTE: The existing `${some_dir}` is removed each script run. Be careful
   with that axe.

1. Bosh. Done. Now you can use clangd and click references in your
   favorite IDE.

NOTE: The script does not clean up after itself. You might want to use
`cros_sdk clean`.

NOTE: The script has deprecated `--with-build` option which builds packages
before generating compile commands. The option is not supported and
flaky. Prefer building packages manually.

### Cover all packages

To have as many packages as possible in compile commands, build all the packages
and run the script on top level packages:

```bash
(inside)
$ FEATURES="noclean" build_packages \
  --board ${BOARD} \
  --no-usepkg --no-usepkgonly \
  --withtest --withdev --withfactory

$ FEATURES="noclean" cros_run_unit_tests --board ${BOARD}

(outside)
$ /path/to/package_index_cros/main.py \
  --with-tests \
  --compile-commands \
  /path/to/clangd/compile/commands/dir/compile_commands.json \
  virtual/target-chromium-os virtual/target-chromium-os-test \
  virtual/target-chromium-os-dev virtual/target-chromium-os-factory \
  virtual/target-chromium-os-factory-shim
```

<!-- Links -->

[chromium checkout instructions]: https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md#get-the-code
[clangd]: go/clangd
[`package_index`]: https://source.chromium.org/chromium/infra/infra/+/main:go/src/infra/cmd/package_index
[`package_index_cros`]: https://source.chromium.org/chromium/infra/infra/+/main:go/src/infra/cmd/package_index_cros
