# Copyright 2012 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Manage SDK chroots.

This script is used for manipulating local chroot environments; creating,
deleting, downloading, etc.  If given --enter (or no args), it defaults
to an interactive bash shell within the chroot.

If given args those are passed to the chroot environment, and executed.
"""

import argparse
import functools
import glob
import logging
import multiprocessing
import os
from pathlib import Path
import pwd
import shlex
import sys
from typing import Iterable, List, Optional, Tuple

from chromite.cbuildbot import cbuildbot_alerts
from chromite.lib import chromite_config
from chromite.lib import chroot_lib
from chromite.lib import commandline
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import cros_sdk_lib
from chromite.lib import locking
from chromite.lib import namespaces
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib import process_util
from chromite.utils import shell_util
from chromite.utils import xdg_util


# Which compression algos the SDK tarball uses.  We've used xz since 2012, and
# zst since 2024.
COMPRESSION_PREFERENCE = ("zst", "xz")

# Proxy simulator configuration.
PROXY_HOST_IP = "192.168.240.1"
PROXY_PORT = 8080
PROXY_GUEST_IP = "192.168.240.2"
PROXY_NETMASK = 30
PROXY_VETH_PREFIX = "veth"
PROXY_CONNECT_PORTS = (80, 443, 9418)
PROXY_APACHE_FALLBACK_USERS = ("www-data", "apache", "nobody")
PROXY_APACHE_MPMS = ("event", "worker", "prefork")
PROXY_APACHE_FALLBACK_PATH = ":".join(
    "/usr/lib/apache2/mpm-%s" % mpm for mpm in PROXY_APACHE_MPMS
)
PROXY_APACHE_MODULE_GLOBS = ("/usr/lib*/apache2/modules", "/usr/lib*/apache2")

# We need these tools to run. Very common tools (tar,..) are omitted.
NEEDED_TOOLS = ("curl",)

# Tools needed for --proxy-sim only.
PROXY_NEEDED_TOOLS = ("ip",)


def get_sdk_tarball_urls(
    version: str,
    bucket: Optional[str] = None,
) -> List[str]:
    """Return URL candidates to download an SDK tarball.

    Args:
        version: The SDK version to download, such as '1970.01.01.314159'.
        bucket: The Google Storage bucket containing the SDK tarball, if not the
            standard SDK bucket.
    """
    extension = {
        "xz": "tar.xz",
        "zst": "tar.zst",
    }
    return [
        cros_sdk_lib.get_sdk_tarball_url(
            version,
            file_extension=extension[compressor],
            override_bucket=bucket,
        )
        for compressor in COMPRESSION_PREFERENCE
    ]


def log_path_holders(path: Path, ignore_pids: Iterable[int] = ()) -> None:
    """Log details about processes holding references to `path`."""
    result = cros_build_lib.dbg_run(
        ["lsof", "-t", "-n", "-f", "--", path],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode:
        return

    pids = [x for x in result.stdout.split() if x not in ignore_pids]
    if not pids:
        return
    result = cros_build_lib.dbg_run(
        ["ps"] + pids,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if not result.returncode:
        logging.warning("Active processes:\n%s", result.stdout.rstrip())


def _SudoCommand():
    """Get the 'sudo' command, along with all needed environment variables."""

    # Pass in the ENVIRONMENT_ALLOWLIST and ENV_PASSTHRU variables so that
    # scripts in the chroot know what variables to pass through.
    cmd = ["sudo"]
    for key in constants.CHROOT_ENVIRONMENT_ALLOWLIST + constants.ENV_PASSTHRU:
        value = os.environ.get(key)
        if value is not None:
            cmd += ["%s=%s" % (key, value)]

    # We keep PATH not for the chroot but for the re-exec & for programs we
    # might run before we chroot into the SDK.  The process that enters the SDK
    # itself will take care of initializing PATH to the right value then.  But
    # we can't override the system's default PATH for root as that will hide
    # /sbin.
    cmd += ["CHROMEOS_SUDO_PATH=%s" % os.environ.get("PATH", "")]

    # Pass along current rlimit settings so we can restore them.
    cmd += [f"CHROMEOS_SUDO_RLIMITS={cros_sdk_lib.ChrootEnteror.get_rlimits()}"]

    return cmd


def _ReportMissing(missing) -> None:
    """Report missing utilities, then exit.

    Args:
        missing: List of missing utilities, as returned by
            osutils.FindMissingBinaries.  If non-empty, will not return.
    """

    if missing:
        raise SystemExit(
            "The tool(s) %s were not found.\n"
            "Please install the appropriate package in your host.\n"
            "Example(ubuntu):\n"
            "  sudo apt-get install <packagename>" % ", ".join(missing)
        )


def _ProxySimSetup(options) -> None:
    """Set up proxy simulator, and return only in the child environment.

    TODO: Ideally, this should support multiple concurrent invocations of
    cros_sdk --proxy-sim; currently, such invocations will conflict with each
    other due to the veth device names and IP addresses.  Either this code would
    need to generate fresh, unused names for all of these before forking, or it
    would need to support multiple concurrent cros_sdk invocations sharing one
    proxy and allowing it to exit when unused (without counting on any local
    service-management infrastructure on the host).
    """

    may_need_mpm = False
    apache_bin = osutils.Which("apache2")
    if apache_bin is None:
        apache_bin = osutils.Which("apache2", PROXY_APACHE_FALLBACK_PATH)
        if apache_bin is None:
            _ReportMissing(("apache2",))
    else:
        may_need_mpm = True

    # Module names and .so names included for ease of grepping.
    apache_modules = [
        ("proxy_module", "mod_proxy.so"),
        ("proxy_connect_module", "mod_proxy_connect.so"),
        ("proxy_http_module", "mod_proxy_http.so"),
        ("proxy_ftp_module", "mod_proxy_ftp.so"),
    ]

    # Find the apache module directory and make sure it has the modules we need.
    module_dirs = {}
    for g in PROXY_APACHE_MODULE_GLOBS:
        for _, so in apache_modules:
            for f in glob.glob(os.path.join(g, so)):
                module_dirs.setdefault(os.path.dirname(f), []).append(so)
    for apache_module_path, modules_found in module_dirs.items():
        if len(modules_found) == len(apache_modules):
            break
    else:
        # Appease cros lint, which doesn't understand that this else block will
        # not fall through to the subsequent code which relies on
        # apache_module_path.
        apache_module_path = None
        raise SystemExit(
            "Could not find apache module path containing all required "
            "modules: %s" % ", ".join(so for mod, so in apache_modules)
        )

    def check_add_module(name):
        so = "mod_%s.so" % name
        if os.access(os.path.join(apache_module_path, so), os.F_OK):
            mod = "%s_module" % name
            apache_modules.append((mod, so))
            return True
        return False

    check_add_module("authz_core")
    if may_need_mpm:
        for mpm in PROXY_APACHE_MPMS:
            if check_add_module("mpm_%s" % mpm):
                break

    veth_host = "%s-host" % PROXY_VETH_PREFIX
    veth_guest = "%s-guest" % PROXY_VETH_PREFIX

    # Set up locks to sync the net namespace setup.  We need the child to create
    # the net ns first, and then have the parent assign the guest end of the
    # veth interface to the child's new network namespace & bring up the proxy.
    # Only then can the child move forward and rely on the network being up.
    ns_create_lock = locking.PipeLock()
    ns_setup_lock = locking.PipeLock()

    pid = os.fork()
    if not pid:
        # Create our new isolated net namespace.
        namespaces.Unshare(namespaces.CLONE_NEWNET)

        # Signal the parent the ns is ready to be configured.
        ns_create_lock.Post()
        del ns_create_lock

        # Wait for the parent to finish setting up the ns/proxy.
        ns_setup_lock.Wait()
        del ns_setup_lock

        # Set up child side of the network.
        commands = (
            ("ip", "link", "set", "up", "lo"),
            (
                "ip",
                "address",
                "add",
                "%s/%u" % (PROXY_GUEST_IP, PROXY_NETMASK),
                "dev",
                veth_guest,
            ),
            ("ip", "link", "set", veth_guest, "up"),
        )
        try:
            for cmd in commands:
                cros_build_lib.dbg_run(cmd)
        except cros_build_lib.RunCommandError as e:
            cros_build_lib.Die("Proxy setup failed!\n%s", e)

        proxy_url = "http://%s:%u" % (PROXY_HOST_IP, PROXY_PORT)
        for proto in ("http", "https", "ftp"):
            os.environ[proto + "_proxy"] = proxy_url
        for v in ("all_proxy", "RSYNC_PROXY", "no_proxy"):
            os.environ.pop(v, None)
        return

    # Set up parent side of the network.
    uid = int(os.environ.get("SUDO_UID", "0"))
    gid = int(os.environ.get("SUDO_GID", "0"))
    if uid == 0 or gid == 0:
        for username in PROXY_APACHE_FALLBACK_USERS:
            try:
                pwnam = pwd.getpwnam(username)
                uid, gid = pwnam.pw_uid, pwnam.pw_gid
                break
            except KeyError:
                continue
        if uid == 0 or gid == 0:
            raise SystemExit("Could not find a non-root user to run Apache as")

    chroot_parent, chroot_base = os.path.split(options.chroot)
    pid_file = os.path.join(chroot_parent, ".%s-apache-proxy.pid" % chroot_base)
    log_file = os.path.join(chroot_parent, ".%s-apache-proxy.log" % chroot_base)

    # Wait for the child to create the net ns.
    ns_create_lock.Wait()
    del ns_create_lock

    apache_directives = [
        "User #%u" % uid,
        "Group #%u" % gid,
        "PidFile %s" % pid_file,
        "ErrorLog %s" % log_file,
        "Listen %s:%u" % (PROXY_HOST_IP, PROXY_PORT),
        "ServerName %s" % PROXY_HOST_IP,
        "ProxyRequests On",
        "AllowCONNECT %s" % " ".join(str(x) for x in PROXY_CONNECT_PORTS),
    ] + [
        "LoadModule %s %s" % (mod, os.path.join(apache_module_path, so))
        for (mod, so) in apache_modules
    ]
    commands = (
        (
            "ip",
            "link",
            "add",
            "name",
            veth_host,
            "type",
            "veth",
            "peer",
            "name",
            veth_guest,
        ),
        (
            "ip",
            "address",
            "add",
            "%s/%u" % (PROXY_HOST_IP, PROXY_NETMASK),
            "dev",
            veth_host,
        ),
        ("ip", "link", "set", veth_host, "up"),
        (
            [apache_bin, "-f", "/dev/null"]
            + [arg for d in apache_directives for arg in ("-C", d)]
        ),
        ("ip", "link", "set", veth_guest, "netns", str(pid)),
    )
    cmd = None  # Make cros lint happy.
    try:
        for cmd in commands:
            cros_build_lib.dbg_run(cmd)
    except cros_build_lib.RunCommandError as e:
        # Clean up existing interfaces, if any.
        cmd_cleanup = ("ip", "link", "del", veth_host)
        try:
            cros_build_lib.run(cmd_cleanup, print_cmd=False)
        except cros_build_lib.RunCommandError:
            logging.error("running %r failed", cmd_cleanup)
        cros_build_lib.Die("Proxy network setup failed!\n%s", e)

    # Signal the child that the net ns/proxy is fully configured now.
    ns_setup_lock.Post()
    del ns_setup_lock

    process_util.ExitAsStatus(os.waitpid(pid, 0)[1])


def _BuildReExecCommand(argv, opts) -> List[str]:
    """Generate new command for self-reexec."""
    # Make sure to preserve the active Python executable in case the version
    # we're running as is not the default one found via the (new) $PATH.
    cmd = _SudoCommand() + ["--"]
    if opts.strace:
        cmd += ["strace"] + shlex.split(opts.strace_arguments) + ["--"]
    return cmd + [sys.executable] + argv


def _ReExecuteIfNeeded(argv, opts) -> None:
    """Re-execute cros_sdk as root.

    Also unshare the mount namespace so as to ensure that processes outside
    the chroot can't mess with our mounts.
    """
    if osutils.IsNonRootUser():
        cmd = _BuildReExecCommand(argv, opts)
        logging.debug(
            "Reexecing self via sudo:\n%s", shell_util.cmd_to_str(cmd)
        )
        os.execvp(cmd[0], cmd)


def CreateParser(
    version_conf: cros_sdk_lib.SdkVersionConfig,
) -> Tuple[argparse.ArgumentParser, argparse._ArgumentGroup]:
    """Generate and return the parser with all the options."""
    usage = (
        "usage: %(prog)s [options] "
        "[VAR1=val1 ... VAR2=val2] [--] [command [args]]"
    )
    parser = commandline.ArgumentParser(
        usage=usage, description=__doc__, caching=True
    )

    # Global options.
    parser.add_argument(
        "--chroot",
        dest="chroot",
        default=None,
        type=Path,
        help=f"SDK chroot dir name [.../{constants.DEFAULT_CHROOT_DIR}]",
    )
    parser.add_argument(
        "--out-dir",
        metavar="DIR",
        default=None,
        type=Path,
        help=(
            "Use DIR for build state and output files "
            f"[.../{constants.DEFAULT_OUT_DIR}]"
        ),
    )
    parser.add_argument(
        "--nouse-image",
        dest="use_image",
        action="store_false",
        default=False,
        deprecated="--[no]use-image is no longer supported (b/266878468).",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--use-image",
        dest="use_image",
        action="store_true",
        default=False,
        deprecated="--[no]use-image is no longer supported (b/266878468).",
        help=argparse.SUPPRESS,
    )

    parser.add_argument(
        "--chrome-root",
        "--chrome_root",
        type="str_path",
        help="Mount this chrome root into the SDK chroot",
    )
    parser.add_argument(
        "--chrome_root_mount",
        type="str_path",
        help="Mount chrome into this path inside SDK chroot",
    )
    parser.add_argument(
        "-u",
        "--url",
        dest="sdk_url",
        help="Use sdk tarball located at this url. Use file:// "
        "for local files.",
    )
    parser.add_argument(
        "--sdk-version",
        default=version_conf.get_default_version(),
        help="Use this sdk version.",
    )
    parser.add_bool_argument(
        "--delete-out-dir",
        default=None,
        enabled_desc="Delete the SDK build state along with the chroot. "
        "Applies to --delete, --replace, or --update.",
        disabled_desc="Don't delete the SDK build state along with the chroot. "
        "Applies to --delete, --replace, or --update. Default for --update.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force delete of the current SDK chroot even if "
        "obtaining the write lock fails. Applies only to --delete or "
        "--replace.",
    )
    parser.add_bool_argument(
        "--read-only",
        default=None,
        enabled_desc="Mount the SDK read-only.",
        disabled_desc="Do not mount the SDK read-only. "
        "This is default, but see also --read-only-sticky.",
    )
    parser.add_bool_argument(
        "--read-only-sticky",
        default=False,
        enabled_desc="Remember the --[no-]read-only setting for future runs.",
        disabled_desc="Leave --[no-]read-only stickiness alone.",
    )

    # Use type=str instead of type='path' to prevent the given path from being
    # transferred to absolute path automatically.
    parser.add_argument(
        "--working-dir",
        type=Path,
        help="Run the command in specific working directory in "
        "chroot.  If the given directory is a relative "
        "path, this program will transfer the path to "
        "the corresponding one inside chroot.",
    )

    parser.add_argument("commands", nargs=argparse.REMAINDER)

    # Commands.
    group = parser.add_argument_group("Commands")
    group.add_argument(
        "--enter",
        action="store_true",
        default=False,
        help="Enter the SDK chroot.  Implies --create.",
    )
    group.add_argument(
        "--create",
        action="store_true",
        default=False,
        help="Create the chroot only if it does not already exist. Downloads "
        "the SDK only if needed, even if --download explicitly passed.",
    )
    group.add_argument(
        "-r",
        "--replace",
        action="store_true",
        default=False,
        help="Replace an existing SDK chroot.  Basically an alias "
        "for --delete --create.",
    )
    group.add_argument(
        "--delete",
        action="store_true",
        default=False,
        help="Delete the current SDK chroot and build state if they exist.",
    )
    group.add_argument(
        "--unmount",
        action="store_true",
        default=False,
        deprecated="loopback-image (--use-image) is no longer supported "
        "(b/266878468). If needed, consider `cros unmount /path/to/chroot`.",
        help=argparse.SUPPRESS,
    )
    group.add_bool_argument(
        "--update",
        default=None,
        enabled_desc="Update the SDK upon entry",
        disabled_desc="Do not update the SDK upon entry",
    )
    group.add_argument(
        "--download",
        action="store_true",
        default=False,
        help="Download the sdk.",
    )
    commands = group

    # Namespace options.
    group = parser.add_argument_group("Namespaces")
    group.add_argument(
        "--proxy-sim",
        action="store_true",
        default=False,
        help="Simulate a restrictive network requiring an outbound" " proxy.",
    )
    for ns, default in (("pid", True), ("net", None)):
        group.add_argument(
            f"--ns-{ns}",
            default=default,
            action="store_true",
            help=f"Create a new {ns} namespace.",
        )
        group.add_argument(
            f"--no-ns-{ns}",
            dest=f"ns_{ns}",
            action="store_false",
            help=f"Do not create a new {ns} namespace.",
        )

    # Debug options.
    group = parser.debug_group
    group.add_argument(
        "--strace",
        action="store_true",
        help="Run cros_sdk through strace after re-exec via sudo",
    )
    group.add_argument(
        "--strace-arguments",
        default="",
        help="Extra strace options (shell quoting permitted)",
    )

    # Internal options.
    group = parser.add_argument_group(
        "Internal Chromium OS Build Team Options",
        "Caution: these are for meant for the Chromium OS build team only",
    )
    group.add_argument(
        "--buildbot-log-version",
        default=False,
        action="store_true",
        help="Log SDK version for buildbot consumption",
    )

    return parser, commands


def _FinalizeOptions(
    parser: argparse.ArgumentParser,
    options: argparse.Namespace,
    commands: argparse._ArgumentGroup,
) -> None:
    """Perform any options tweaking, and prevent further modification."""

    # Expand out the aliases...
    if options.replace:
        options.delete = options.create = True

    # If a command is not given, default to enter.
    # pylint: disable=protected-access
    # This _group_actions access sucks, but upstream decided to not include an
    # alternative to optparse's option_list, and this is what they recommend.
    options.enter |= not any(
        getattr(options, x.dest) for x in commands._group_actions
    )
    # pylint: enable=protected-access
    options.enter |= bool(options.commands)

    if options.delete and not options.create and options.enter:
        parser.error(
            "Trying to enter the chroot when --delete "
            "was specified makes no sense."
        )

    # --update behavior should be disabled when --delete is specified.  Further
    # options like --create might also be in the command, but the --update flag
    # won't actually need be enabled in this case, as we'll build off the latest
    # tarball anyway.
    if options.delete:
        options.update = False

    # We resolve the default for --update after considering --enter default, as
    # "cros_sdk" should enter the SDK, whereas "cros_sdk --update" should update
    # if required, but not actually enter.
    if options.update is None:
        options.update = True

    if options.force and not options.delete:
        parser.error("Specifying --force without --delete does not make sense.")

    # Resolve default output directories.
    chroot_path = (
        constants.DEFAULT_CHROOT_PATH
        if options.chroot is None
        else options.chroot
    )
    out_path = (
        constants.DEFAULT_OUT_PATH
        if options.out_dir is None
        else options.out_dir
    )

    if path_util.is_citc_checkout():
        workspace_path = path_util.get_citc_workspace_path()
        workspace_path.mkdir(parents=True, exist_ok=True)
        chroot_path = path_util.get_citc_chroot_path()
        out_path = path_util.get_citc_out_path()

    options.chroot = osutils.ExpandPath(chroot_path)
    options.out_dir = osutils.ExpandPath(out_path)
    logging.debug("Configuring chroot to %s", options.chroot)
    logging.debug("Configuring output dir to %s", options.out_dir)

    chroot_exists = cros_sdk_lib.IsChrootReady(options.chroot)
    # Finally, flip create if necessary.
    if options.enter:
        options.create |= not chroot_exists

    # Make sure we will download if we plan to create.
    options.download |= options.create

    if options.read_only is None and options.read_only_sticky:
        parser.error(
            "Specifying --read-only-sticky without --read-only or "
            "--no-read-only does not make sense."
        )

    chromite_config.initialize()
    osutils.SafeMakedirsNonRoot(xdg_util.CACHE_HOME)
    ro_cfg = chromite_config.SDK_READONLY_STICKY_CONFIG
    if options.read_only is None:
        # Defer to sticky configuration file only if --read-only/--no-read-only
        # were not provided.
        options.read_only = ro_cfg.exists()

    # Resolve tri-state --delete-out-dir to a boolean.  This argument is
    # default-on for --delete/--replace, but default-off for --update.
    if options.delete_out_dir is None:
        options.delete_out_dir = not options.update

    options.Freeze()

    if options.read_only_sticky:
        # Notify the user when toggling stickiness.
        if options.read_only:
            if not ro_cfg.exists():
                logging.warning("Making cros_sdk --read-only sticky")
            ro_cfg.touch()
        else:
            if ro_cfg.exists():
                logging.warning("Making cros_sdk --no-read-only sticky")
                ro_cfg.unlink()


def main(argv) -> None:
    # Turn on strict sudo checks.
    cros_build_lib.STRICT_SUDO = True

    try:
        version_conf = cros_sdk_lib.SdkVersionConfig.load()
    except FileNotFoundError:
        cros_build_lib.Die(
            "No SDK version was found. "
            "Are you in a Chromium source tree instead of ChromiumOS?\n\n"
            "Please change to a directory inside your ChromiumOS source tree\n"
            "and retry.  If you need to setup a ChromiumOS source tree, see\n"
            "  https://dev.chromium.org/chromium-os/developer-guide"
        )

    parser, commands = CreateParser(version_conf)
    options = parser.parse_args(argv)

    # Some basic checks first, before we ask for sudo credentials.
    cros_build_lib.AssertOutsideChroot()

    host = os.uname()[4]
    if host != "x86_64":
        cros_build_lib.Die(
            "cros_sdk is currently only supported on x86_64; you're running"
            " %s.  Please find a x86_64 machine." % (host,)
        )

    # Merge the outside PATH setting if we re-execed ourselves.
    if "CHROMEOS_SUDO_PATH" in os.environ:
        os.environ["PATH"] = "%s:%s" % (
            os.environ.pop("CHROMEOS_SUDO_PATH"),
            os.environ["PATH"],
        )

    _ReportMissing(osutils.FindMissingBinaries(NEEDED_TOOLS))
    if options.proxy_sim:
        _ReportMissing(osutils.FindMissingBinaries(PROXY_NEEDED_TOOLS))

    _ReExecuteIfNeeded([sys.argv[0]] + argv, options)

    # |options| cannot be modified after this.
    _FinalizeOptions(parser, options, commands)

    chroot = chroot_lib.Chroot(
        path=options.chroot,
        out_path=options.out_dir,
        cache_dir=options.cache_dir,
        chrome_root=options.chrome_root,
    )

    if not chroot.path_is_valid():
        if options.force:
            logging.warning("Proceeding with an invalid chroot due to --force.")
        else:
            cros_build_lib.Die(
                "Your chroot directory (%s) doesn't look like a chroot, nor a "
                "safe place to make one.  If you really want to trash this "
                "directory, pass --force and --delete (or --no-delete-out-dir "
                "if you want to keep the out directory).",
                chroot.path,
            )

    # Most important chroot state bits migrated to the out directory via logic
    # landed on 2023-05-08.  If the user has not entered recently, don't let
    # them unexpectedly loose state bits (since the migration logic is gone).
    # TODO(2025-01-01): Delete this check.
    if not options.delete:
        chroot_version = cros_sdk_lib.GetChrootVersion(chroot.path)
        if chroot_version and chroot_version <= 223:
            cros_build_lib.Die(
                "Your SDK is too old to be entered!  Please copy any state you "
                "need out of your chroot, and run `cros_sdk --replace`.  "
                "(chroot_version=%s)",
                chroot_version,
            )

    if options.buildbot_log_version:
        cbuildbot_alerts.PrintBuildbotStepText(options.sdk_version)

    replace_for_update = False

    if options.update:
        replace_for_update = options.sdk_version != chroot.tarball_version
        if replace_for_update:
            logging.notice(
                "Replacing the chroot for version update %s -> %s",
                chroot.tarball_version,
                options.sdk_version,
            )
        else:
            logging.debug("--update: Replace not required")

    # Anything that needs to manipulate the main chroot mount or communicate
    # with LVM needs to be done here before we enter the new namespaces.

    # Delete is handled in a background process so we can download the
    # SDK tarball in parallel.  Eventually, we may be able to fully
    # background-off deletion and not block on it anywhere.
    delete_proc: Optional[multiprocessing.Process] = None
    if replace_for_update or options.delete:
        delete_proc = multiprocessing.Process(
            target=functools.partial(
                chroot.delete,
                delete_out_dir=options.delete_out_dir,
                force=options.force,
            ),
        )
        delete_proc.start()

    # Based on selections, determine the tarball to fetch.
    urls = []
    if replace_for_update or options.download:
        if options.sdk_url:
            urls = [options.sdk_url]
        else:
            urls = get_sdk_tarball_urls(
                options.sdk_version, bucket=version_conf.bucket
            )

    sdk_cache = Path(chroot.cache_dir) / "sdks"
    if options.download or options.create or replace_for_update:
        sdk_tarball = cros_sdk_lib.fetch_remote_tarballs(sdk_cache, urls)

    if delete_proc:
        delete_proc.join(timeout=15)
        if delete_proc.is_alive():
            logging.warning(
                "Waiting for SDK deletion.  If you have SDK shells open, "
                "please close them."
            )
            log_path_holders(chroot.lock_path, {str(delete_proc.pid)})
            delete_proc.join()
        if delete_proc.exitcode != 0:
            cros_build_lib.Die(
                "SDK deletion failed (exit code=%s)", delete_proc.exitcode
            )

    # Enter a new set of namespaces.  Everything after here cannot directly
    # affect the hosts's mounts or alter LVM volumes.
    namespaces.SimpleUnshare(net=options.ns_net, pid=options.ns_pid)

    with chroot.lock() as lock:
        if options.proxy_sim:
            _ProxySimSetup(options)

        distfiles_cache = os.path.join(chroot.cache_dir, "distfiles")
        osutils.SafeMakedirsNonRoot(chroot.cache_dir)
        osutils.SafeMakedirsNonRoot(distfiles_cache)
        osutils.SafeMakedirsNonRoot(options.out_dir)
        # Create here (in addition to cros_sdk_lib.MountChrootPaths()) because
        # some usages want to create tmp files here even before we've fully
        # mounted the SDK.
        osutils.SafeMakedirsNonRoot(options.out_dir / "tmp", mode=0o1777)

        mounted = False
        if replace_for_update or options.create:
            lock.write_lock()
            # Recheck if the chroot is set up here before creating to make sure
            # we account for whatever the various delete/cleanup steps above
            # have done.
            if cros_sdk_lib.IsChrootReady(chroot.path):
                logging.debug("Chroot already exists.  Skipping creation.")
            else:
                cros_sdk_lib.CreateChroot(
                    chroot,
                    Path(sdk_tarball),
                )
                mounted = True

        if options.enter:
            lock.read_lock()
            if not mounted:
                cros_sdk_lib.MountChrootPaths(chroot)
            ret = cros_sdk_lib.EnterChroot(
                chroot,
                chrome_root_mount=options.chrome_root_mount,
                cwd=options.working_dir,
                cmd=options.commands,
                read_only=options.read_only,
            )
            sys.exit(ret.returncode)
