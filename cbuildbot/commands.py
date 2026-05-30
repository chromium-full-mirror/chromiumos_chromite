# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Module containing the various individual commands a builder can run."""

from chromite.lib import cros_build_lib


class ChromeSDK:
    """Wrapper for the 'cros chrome-sdk' command."""

    def __init__(
        self,
        cwd,
        board,
        extra_args=None,
        chrome_src=None,
        debug_log=True,
        cache_dir=None,
        target_tc=None,
        toolchain_url=None,
    ) -> None:
        """Initialization.

        Args:
            cwd: Where to invoke 'cros chrome-sdk'.
            board: The board to run chrome-sdk for.
            extra_args: Extra args to pass in on the command line.
            chrome_src: Path to pass in with --chrome-src.
            debug_log: If set, run with debug log-level.
            cache_dir: Specify non-default cache directory.
            target_tc: Override target toolchain.
            toolchain_url: Override toolchain url pattern.
        """
        self.cwd = cwd
        self.board = board
        self.extra_args = extra_args or []
        if chrome_src:
            self.extra_args += ["--chrome-src", chrome_src]
        self.debug_log = debug_log
        self.cache_dir = cache_dir
        self.target_tc = target_tc
        self.toolchain_url = toolchain_url

    def Run(self, cmd, extra_args=None, run_args=None):
        """Run a command inside the chrome-sdk context.

        Args:
            cmd: Command (list) to run inside 'cros chrome-sdk'.
            extra_args: Extra arguments for 'cros chorme-sdk'.
            run_args: If set (dict), pass to run as kwargs.

        Returns:
            A CompletedProcess object.
        """
        if run_args is None:
            run_args = {}
        cros_cmd = ["cros"]
        if self.debug_log:
            cros_cmd += ["--log-level", "debug"]
        if self.cache_dir:
            cros_cmd += ["--cache-dir", self.cache_dir]
        if self.target_tc:
            self.extra_args += ["--target-tc", self.target_tc]
        if self.toolchain_url:
            self.extra_args += ["--toolchain-url", self.toolchain_url]
        cros_cmd += ["chrome-sdk", "--board", self.board] + self.extra_args
        cros_cmd += (extra_args or []) + ["--"] + cmd
        return cros_build_lib.run(cros_cmd, cwd=self.cwd, **run_args)

    def Ninja(self, debug=False, run_args=None):
        """Run 'ninja' inside a chrome-sdk context.

        Args:
            debug: Whether to do a Debug build (defaults to Release).
            run_args: If set (dict), pass to run as kwargs.

        Returns:
            A CompletedProcess object.
        """
        return self.Run(self.GetNinjaCommand(debug=debug), run_args=run_args)

    def GetNinjaCommand(self, debug=False):
        """Returns a command line to run "ninja".

        Args:
            debug: Whether to do a Debug build (defaults to Release).

        Returns:
            Command line to run "ninja".
        """
        cmd = ["autoninja"]
        cmd += [
            "-C",
            self._GetOutDirectory(debug=debug),
            "chromiumos_preflight",
        ]
        return cmd

    def VMTest(self, image_path, debug=False):
        """Run cros_run_test in a VM.

        Only run tests for boards where we build a VM.

        Args:
            image_path: VM image path.
            debug: True if this is a debug build.

        Returns:
            A CompletedProcess object.
        """
        return self.Run(
            [
                "cros_run_test",
                "--copy-on-write",
                "--deploy",
                "--board=%s" % self.board,
                "--image-path=%s" % image_path,
                "--build-dir=%s" % self._GetOutDirectory(debug=debug),
            ]
        )

    def _GetOutDirectory(self, debug=False):
        """Returns the path to the output directory.

        Args:
            debug: Whether to do a Debug build (defaults to Release).

        Returns:
            Path to the output directory.
        """
        flavor = "Debug" if debug else "Release"
        return "out_%s/%s" % (self.board, flavor)
