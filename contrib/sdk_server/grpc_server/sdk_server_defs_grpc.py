# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Defines classes and functions used in implementation of sdk server.

    TODO: modify error handling for failed BAPI called to that of build_image
"""
import asyncio
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from pickle import EMPTY_DICT
import subprocess
import tempfile
import time
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    TYPE_CHECKING,
    Union,
)

from chromite.third_party.google.protobuf import json_format

from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2
from chromite.contrib.sdk_server.grpc_server import sdk_server_pb2_grpc
from chromite.contrib.sdk_server.grpc_server.chromite.api import image_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sdk_pb2
from chromite.contrib.sdk_server.grpc_server.chromite.api import sysroot_pb2
from chromite.contrib.sdk_server.grpc_server.chromiumos import common_pb2
from chromite.lib import chroot_lib
from chromite.lib import constants
from chromite.lib import cros_build_lib
from chromite.lib import osutils
from chromite.lib import sysroot_lib


STRICT_SUDO = False
EMPTY_OUTPUT_ERROR = "ERROR: output json is empty"


def IsInsideChroot():
    """Returns True if we are inside chroot.

    See: from cros_build_lib.py
    """
    return os.path.exists("/etc/cros_chroot_version")


def AsyncRun(
    cmd,
    cwd=None,
    env=None,
    shell=True,
    extra_env=None,
    enter_chroot=False,
    chroot_args=None,
    stdout=None,
    stderr=None,
    debug_level=logging.INFO,
):
    # Taken from cros_build_lib.run

    # Quick check the command.  This helps when RunCommand is deep in the call
    # chain, but the command itself was constructed along the way.
    if isinstance(cmd, (str, bytes)):
        if not shell:
            raise ValueError("Cannot run a string command without a shell")
        cmd = ["/bin/bash", "-c", cmd]
        shell = False
    elif shell:
        raise ValueError("Cannot run an array command with a shell")
    elif not cmd:
        raise ValueError("Missing command to run")

    env = env.copy() if env is not None else os.environ.copy()
    env["LC_MESSAGES"] = "C"
    env.update(extra_env if extra_env else {})
    if enter_chroot and not IsInsideChroot():
        wrapper = ["cros_sdk"]
        if cwd:
            # If the current working directory is set, try to find cros_sdk
            # relative to cwd. Generally cwd will be the buildroot therefore we
            # want to use {cwd}/chromite/bin/cros_sdk. For more info PTAL at
            # crbug.com/432620
            path = cwd / constants.CHROMITE_BIN_SUBDIR / "cros_sdk"
            if os.path.exists(path):
                wrapper = [path]

        if chroot_args:
            wrapper += chroot_args

        if extra_env:
            wrapper.extend("%s=%s" % (k, v) for k, v in extra_env.items())

        cmd = wrapper + ["--"] + cmd

    log = ""
    log += "run: %s" % ("".join(cmd),)
    if cwd:
        log += " in %s" % (cwd,)
    logging.log(debug_level, "%s", log)

    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=stdout,
            stderr=stderr,
            shell=False,
            env=env,
            close_fds=True,
        )
        return proc
    except:
        raise Exception("Popen failed")


class SdkImage:
    """Chroot Image class"""

    def __init__(self, path: Union[str, os.PathLike]):
        self.path = path
        self.name = os.path.split(str(path).rstrip("/"))[1]
        self.last_modified = time.ctime(os.path.getmtime(path))
        self.date_created = time.ctime(os.path.getctime(path))
        self.packages = []

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name


class SdkSysroot(sysroot_lib.Sysroot):
    """Wrapper for sysroot_lib.Sysroot class."""

    def __init__(self, path: Union[str, os.PathLike]):
        super().__init__(path)
        self.name = os.path.split(str(path).rstrip("/"))[1]
        self.images = []
        self.packages = []
        self.get_images()

    def __str__(self):
        return self.name

    def __repr__(self):
        return self.name

    def get_images(self):
        path = (
            f"{constants.HOME_DIRECTORY}"
            f"/chromiumos/src/build/images/{self.name}"
        )
        images = os.listdir(path)
        self.images = []
        for image in images:
            image_path = f"{path}/{image}"
            image_obj = SdkImage(image_path)
            self.images.append(image_obj)

    def get_all_packages(self):
        script = f"cros_workon " f"--board={self.name} " "--all list;"
        result = cros_build_lib.run(
            script, shell=True, stdout=subprocess.PIPE, enter_chroot=True
        )
        packages = result.stdout.splitlines()
        result.stdout.close()
        self.packages = packages
        return packages


class SdkChroot(
    chroot_lib.Chroot, sdk_server_pb2_grpc.sdk_server_serviceServicer
):
    """Wrapper for chroot_lib Chroot class."""

    def __init__(self, path: Union[str, os.PathLike] = None):
        chroot_lib.Chroot.__init__(self, path)
        self.sysroots = []
        self.version = None
        self.logger = logging.getLogger()
        if not os.path.exists("logs/"):
            os.makedirs("logs/")
        self.handler = TimedRotatingFileHandler(
            filename="logs/log", when="midnight"
        )
        self.handler.suffix = "%Y-%m-%d"
        self.logger.addHandler(self.handler)

    def current_boards(self, request, context):
        self.logger.info("REQUEST: current boards")
        if self.has_path("/build"):
            path = self.full_path("/build/")
            sysroots = os.listdir(path)
            self.sysroots = []
            for sysroot in sysroots:
                sysroot_path = self.full_path(f"/build/{sysroot}")
                sysroot_obj = SdkSysroot(sysroot_path)
                self.sysroots.append(sysroot_obj)

            boards = [common_pb2.BuildTarget(name=board) for board in sysroots]
            response = sdk_server_pb2.CurrentBoardsResponse(build_target=boards)
            return response

        # "/build" does not exist i.e. chroot has no boards
        return sdk_server_pb2.CurrentBoardsResponse()

    def query_boards(self, request, context):
        self.logger.info("REQUEST: query boards")
        script = "cros query boards"
        result = cros_build_lib.run(
            script,
            shell=True,
            enter_chroot=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        output = result.stdout.splitlines()
        boards = [common_pb2.BuildTarget(name=board) for board in output]
        response = sdk_server_pb2.QueryBoardsResponse(build_target=boards)
        return response

    def repo_sync(self, request, context):
        self.logger.info("REQUEST: repo sync")
        script = "repo sync"
        result = cros_build_lib.run(script, shell=True, stdout=subprocess.PIPE)
        output = result.stdout.decode()
        response = sdk_server_pb2.RepoSyncResponse(info=output)
        return response

    def repo_status(self, request, context):
        self.logger.info("REQUEST: repo status")
        script = "repo status"
        result = cros_build_lib.run(script, shell=True, stdout=subprocess.PIPE)
        output = result.stdout.decode().splitlines()
        response = sdk_server_pb2.RepoStatusResponse(info=output)
        return response

    def update_chroot(self, request, context):
        self.logger.info("REQUEST: update_chroot\n")

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = "{}"
                json_format.Parse(input_content, request.request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.SdkService/Update"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )
                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.UpdateChrootResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.UpdateChrootResponse()
                internal_resp = sdk_pb2.UpdateResponse()

                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.response.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def cros_workon_info(self, request, context):
        """run cros workon info for given package

        if build_target not specified will run with --host enabled
        """
        self.logger.info("REQUEST: cros_workon info")
        package = request.package_info.package_name

        target = (
            f"--board={request.build_target.name}"
            if request.build_target
            else "--host"
        )

        script = f"cros workon {target} info {package}"
        result = cros_build_lib.run(
            script, shell=True, enter_chroot=True, stdout=subprocess.PIPE
        )
        output = result.stdout.decode()
        return sdk_server_pb2.WorkonInfoResponse(info=output)

    def cros_workon_start(self, request, context):
        """run cros workon start for given package

        if build_target not specified will run with --host enabled
        """
        self.logger.info("REQUEST: cros_workon start")
        package = request.package_info.package_name
        target = (
            f"--board={request.build_target.name}"
            if request.build_target
            else "--host"
        )

        script = f"cros workon {target} start {package}"
        result = cros_build_lib.run(
            script, shell=True, enter_chroot=True, stdout=subprocess.PIPE
        )
        output = result.stdout.decode()
        return sdk_server_pb2.WorkonStartResponse(info=output)

    def cros_workon_stop(self, request, context):
        """run cros workon stop for given package

        if build_target not specified will run with --host enabled
        """
        self.logger.info("REQUEST: cros_workon stop")
        package = request.package_info.package_name
        target = (
            f"--board={request.build_target.name}"
            if request.build_target
            else "--host"
        )

        script = f"cros workon {target} stop {package}"
        result = cros_build_lib.run(
            script, shell=True, enter_chroot=True, stdout=subprocess.PIPE
        )
        output = result.stdout.decode()
        return sdk_server_pb2.WorkonStopResponse(info=output)

    def cros_workon_list(self, request, context):
        """run cros workon list

        if build_target not specified will run with --host enabled
        """
        self.logger.info("REQUEST: cros_workon list")
        target = (
            f"--board={request.build_target.name}"
            if request.build_target
            else "--host"
        )

        script = f"cros workon list {target}"
        result = cros_build_lib.run(
            script, shell=True, enter_chroot=True, stdout=subprocess.PIPE
        )
        output = result.stdout.splitlines()
        packages = [
            common_pb2.PackageInfo(package_name=package) for package in output
        ]
        response = sdk_server_pb2.WorkonListResponse(package_info=packages)
        return response

    def chroot_path(self, request, context):
        self.logger.info("REQUEST: chroot path")
        response = sdk_server_pb2.ChrootPathResponse(path=self.path)
        return response

    def all_packages(self, request, context):
        self.logger.info("REQUEST: all packages")
        target = (
            f"--board={request.build_target.name}"
            if request.build_target
            else "--host"
        )

        script = f"cros workon " f"{target} " "--all list"

        result = cros_build_lib.run(
            script,
            shell=True,
            enter_chroot=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = result.stdout.splitlines()
        packages = [
            common_pb2.PackageInfo(package_name=package) for package in output
        ]
        response = sdk_server_pb2.AllPackagesResponse(package_info=packages)
        return response

    def _run_endpoint(self, endpoint, inputfile, outputfile):
        """calls a BAPI endpoint"""
        script = (
            f"{constants.HOME_DIRECTORY}"
            "/chromiumos/chromite/bin/build_api "
            f"{endpoint} "
            f"--input-json {inputfile} "
            f"--output-json {outputfile} "
            "--debug"
        )

        process = AsyncRun(
            script, stderr=subprocess.STDOUT, stdout=subprocess.PIPE
        )
        return process

    def create_sdk(self, request, context):
        self.logger.info("REQUEST: cros_sdk create")
        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request.request)
                json.dump(input_content, tempinput)
                logging.info(input_content)
                tempinput.seek(0)

                endpoint = "chromite.api.SdkService/Create"
                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.CreateSdkResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.CreateSdkResponse()
                internal_resp = sdk_pb2.CreateResponse()

                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.response.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def replace_sdk(self, request, context):
        self.logger.info("REQUEST: cros_sdk replace")

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request.request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.SdkService/Create"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.ReplaceSdkResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.ReplaceSdkResponse()
                internal_resp = sdk_pb2.CreateResponse()

                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.response.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def delete_sdk(self, request, context):
        self.logger.info("REQUEST: cros_sdk delete")

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request.request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.SdkService/Delete"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.DeleteSdkResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.DeleteSdkResponse()
                internal_resp = sdk_pb2.DeleteResponse()
                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.response.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def build_packages(self, request, context):
        self.logger.info("REQUEST: build packages")
        create_req = request.create_req
        toolchain_req = request.toolchain_req
        packages_req = request.packages_req
        error = False
        self.logger.info("Calling Sysroot_create")
        for response in self._sysroot_create(create_req):
            if response.logging_info == EMPTY_OUTPUT_ERROR:
                error = True
            yield response

        self.logger.info("Calling Sysroot_install_toolchain")
        if not error:
            for response in self._install_toolchain(toolchain_req):
                if response.logging_info == EMPTY_OUTPUT_ERROR:
                    error = True
                yield response

        self.logger.info("Calling Sysroot_install_packages")
        if not error:
            for response in self._install_packages(packages_req):
                yield response

    def _sysroot_create(self, request):
        """Call BAPI sysroot_create endpoint"""

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.SysrootService/Create"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.BuildPackagesResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.BuildPackagesResponse()
                internal_resp = sysroot_pb2.SysrootCreateResponse()
                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.create_resp.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def _install_toolchain(self, request):
        """Call BAPI install_toolchain endpoint"""

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.SysrootService/InstallToolchain"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.BuildPackagesResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.BuildPackagesResponse()
                internal_resp = sysroot_pb2.InstallToolchainResponse()

                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.toolchain_resp.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def _install_packages(self, request):
        """Call BAPI install_toolchain endpoint"""

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.SysrootService/InstallPackages"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.BuildPackagesResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.BuildPackagesResponse()
                internal_resp = sysroot_pb2.InstallPackagesResponse()

                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.packages_resp.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response

    def build_image(self, request, context):
        self.logger.info("REQUEST: build image")

        with tempfile.NamedTemporaryFile(mode="w+") as tempinput:
            with tempfile.NamedTemporaryFile(mode="w+") as tempoutput:
                input_content = json_format.MessageToDict(request.request)
                json.dump(input_content, tempinput)
                tempinput.seek(0)

                endpoint = "chromite.api.ImageService/Create"

                process = self._run_endpoint(
                    endpoint, tempinput.name, tempoutput.name
                )

                for c in iter(lambda: process.stdout.readline(), b""):
                    self.logger.info(c.decode())
                    response = sdk_server_pb2.BuildImageResponse(
                        logging_info=c.decode()
                    )
                    yield response

                contents = osutils.ReadFile(tempoutput.name)
                response = sdk_server_pb2.BuildImageResponse()
                internal_resp = image_pb2.CreateImageResult()
                if os.path.getsize(tempoutput.name) > 2:
                    json_format.Parse(contents, internal_resp)
                    response.response.CopyFrom(internal_resp)
                    process.stdout.close()
                    yield response
                else:
                    response.logging_info = EMPTY_OUTPUT_ERROR
                    yield response
