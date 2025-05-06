# Copyright 2011 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Methods and classes to interact with a devserver instance."""

import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib.xbuddy import build_artifact
from chromite.lib.xbuddy import devserver_constants
from chromite.lib.xbuddy import xbuddy


DEFAULT_STATIC_DIR = path_util.FromChrootPath(
    os.path.join(constants.CHROOT_SOURCE_ROOT, "devserver", "static")
)


class ImagePathError(Exception):
    """Raised when the provided path can't be resolved to an image."""


class ArtifactDownloadError(Exception):
    """Raised when the artifact could not be downloaded."""


def GetXbuddyPath(path):
    """A helper function to parse an xbuddy path.

    Args:
        path: Either an xbuddy path, gs path, or a path with no scheme.

    Returns:
        path/for/xbuddy if |path| is xbuddy://path/for/xbuddy;
        path/for/gs if |path| is gs://chromeos-image-archive/path/for/gs/;
        otherwise, |path|.

    Raises:
        ValueError: if |path| is an unrecognized scheme, or is a gs path with
            an unrecognized bucket.
    """
    parsed = urllib.parse.urlparse(path)

    if parsed.scheme == "xbuddy":
        return "%s%s" % (parsed.netloc, parsed.path)
    elif parsed.scheme == "":
        logging.debug('Assuming "%s" is an xbuddy path.', path)
        return path
    elif parsed.scheme == "gs":
        if parsed.netloc != devserver_constants.GS_IMAGE_BUCKET:
            raise ValueError(
                'Unsupported gs bucket "%s". Only bucket "%s" is supported.'
                % (parsed.netloc, devserver_constants.GS_IMAGE_BUCKET)
            )
        return "%s%s" % (xbuddy.REMOTE, parsed.path)
    else:
        raise ValueError('Unsupported scheme "%s".' % (parsed.scheme,))


def GetImagePathWithXbuddy(
    path, board, version, static_dir=DEFAULT_STATIC_DIR, silent=False
):
    """Gets image path and resolved XBuddy path using xbuddy.

    Ask xbuddy to translate |path|, and if necessary, download and stage the
    image, then return a translated path to the image. Also returns the resolved
    XBuddy path, which may be useful for subsequent calls in case the argument
    is an alias.

    Args:
        path: The xbuddy path.
        board: The default board to use if board is not specified in |path|.
        version: The default version to use if one is not specified in |path|.
        static_dir: Static directory to stage the image in.
        silent: Suppress error messages.

    Returns:
        A tuple consisting of the build id and full path to the image.
    """
    # Since xbuddy often wants to use gsutil from $PATH, make sure our local
    # copy shows up first.
    upath = os.environ["PATH"].split(os.pathsep)
    upath.insert(0, str(constants.CHROMITE_SCRIPTS_DIR))
    os.environ["PATH"] = os.pathsep.join(upath)

    xb = xbuddy.XBuddy(board=board, version=version, static_dir=static_dir)
    path_list = GetXbuddyPath(path).rsplit(os.path.sep)
    try:
        return xb.Get(path_list)
    except xbuddy.XBuddyException as e:
        if not silent:
            logging.error(
                'Locating image "%s" failed. The path might not be valid '
                "or the image might not exist.",
                path,
            )
        raise ImagePathError("Cannot locate image %s: %s" % (path, e))
    except build_artifact.ArtifactDownloadError as e:
        if not silent:
            logging.error('Downloading image "%s" failed.', path)
        raise ArtifactDownloadError("Cannot download image %s: %s" % (path, e))


def GetIPv4Address(dev=None, global_ip=True):
    """Returns any global/host IP address or the IP address of the given device.

    socket.gethostname() is insufficient for machines where the host files are
    not set up "correctly."  Since some of our builders may have this issue,
    this method gives you a generic way to get the address so you are reachable
    either via a VM or remote machine on the same network.

    Args:
        dev: Get the IP address of the device (e.g. 'eth0').
        global_ip: If set True, returns a globally valid IP address. Otherwise,
        returns a local IP address (default: True).
    """
    cmd = ["ip", "addr", "show"]
    cmd += ["scope", "global" if global_ip else "host"]
    cmd += [] if dev is None else ["dev", dev]

    result = cros_build_lib.run(
        cmd, print_cmd=False, capture_output=True, encoding="utf-8"
    )
    matches = re.findall(r"\binet (\d+\.\d+\.\d+\.\d+).*", result.stdout)
    if matches:
        return matches[0]
    logging.warning("Failed to find ip address in %r", result.stdout)
    return None


def CreateStaticDirectory(static_dir: str = DEFAULT_STATIC_DIR) -> None:
    """Creates |static_dir|.

    Args:
        static_dir: path to the static directory of the devserver instance.
    """
    osutils.SafeMakedirsNonRoot(static_dir)


def WipeStaticDirectory(static_dir: str = DEFAULT_STATIC_DIR) -> None:
    """Cleans up |static_dir|.

    Args:
        static_dir: path to the static directory of the devserver instance.
    """
    logging.info("Clearing cache directory %s", static_dir)
    osutils.RmDir(static_dir, ignore_missing=True, sudo=True)
