# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Build graph dependency creation service.

This service handles the creation of the portage build dependency graphs and the
graphs mapping from portage packages to the dependency source.
"""

from chromite.api import api_config
from chromite.api import faux
from chromite.api import validate
from chromite.api.controller import controller_util
from chromite.api.gen.chromite.api import depgraph_pb2

# TODO(crbug/1081828): stop using build_target and drop it from the proto.
from chromite.lib import build_target_lib
from chromite.lib.parser import package_info
from chromite.service import dependency


def AugmentDepGraphProtoFromJsonMap(json_map, graph) -> None:
    """Augment package deps from |json_map| to graph object.

    Args:
        json_map: the json object that stores the portage package. This is
            generated from chromite.lib.service.dependency.GetBuildDependency()
        graph: the proto object that represents the dependency graph (see
            DepGraph message in chromite/api/depgraph.proto)
    """
    graph.sysroot.build_target.name = json_map["target_board"]
    graph.sysroot.path = json_map["sysroot_path"]
    # TODO(crbug/1081828): Drop this when no longer used.
    graph.build_target.name = json_map["target_board"]

    for data in json_map["package_deps"].values():
        package_dep_info = graph.package_deps.add()
        package_info_msg = package_dep_info.package_info
        package_info_msg.package_name = data["name"]
        package_info_msg.category = data["category"]
        package_info_msg.version = data["version"]
        for dep in data["deps"]:
            cpv = package_info.parse(dep)
            dep_package = package_dep_info.dependency_packages.add()
            controller_util.serialize_package_info(cpv, dep_package)

        package_CPV = controller_util.PackageInfoToString(package_info_msg)
        for path in json_map["source_path_mapping"][package_CPV]:
            source_path = package_dep_info.dependency_source_paths.add()
            source_path.path = path


def _GetBuildDependencyGraphResponse(_request, response, _config) -> None:
    """Add fake dep_graph data to a successful response."""
    response.dep_graph.build_target.name = "target_board"


@faux.success(_GetBuildDependencyGraphResponse)
@faux.empty_error
@validate.require_each("packages", ["category", "package_name"])
@validate.validation_complete
def GetBuildDependencyGraph(
    request: depgraph_pb2.GetBuildDependencyGraphRequest,
    response: depgraph_pb2.GetBuildDependencyGraphResponse,
    _config: api_config.ApiConfig,
) -> None:
    """Create the build dependency graph.

    Args:
        request: The input arguments message.
        response: The empty output message.
        _config: The API call config.
    """
    if request.HasField("sysroot"):
        board = request.sysroot.build_target.name
        sysroot_path = request.sysroot.path
    else:
        # TODO(crbug/1081828): stop using build_target & drop it from the proto.
        board = request.build_target.name
        sysroot_path = build_target_lib.get_default_sysroot_path(board or None)

    packages = tuple(
        controller_util.deserialize_package_info(x) for x in request.packages
    )

    json_map, sdk_json_map = dependency.GetBuildDependency(
        sysroot_path, board, packages
    )
    AugmentDepGraphProtoFromJsonMap(json_map, response.dep_graph)
    AugmentDepGraphProtoFromJsonMap(sdk_json_map, response.sdk_dep_graph)


def _ListResponse(_request, response, _config) -> None:
    """Add fake dependency data to a successful response."""
    package_dep = response.package_deps.add()
    package_dep.category = "category"
    package_dep.package_name = "name"


@faux.success(_ListResponse)
@faux.empty_error
@validate.exists("sysroot.path")
@validate.require_each("src_paths", ["path"])
@validate.require_each("packages", ["category", "package_name"])
@validate.validation_complete
def List(
    request: depgraph_pb2.ListRequest,
    response: depgraph_pb2.ListResponse,
    _config: api_config.ApiConfig,
) -> None:
    """Get a list of package dependencies.

    Args:
        request: The input arguments message.
        response: The empty output message.
        _config: The API call config.
    """
    sysroot_path = request.sysroot.path
    src_paths = [src_path.path for src_path in request.src_paths]
    package_deps = dependency.GetDependencies(
        sysroot_path,
        src_paths=src_paths,
        packages=[
            controller_util.deserialize_package_info(package)
            for package in request.packages
        ],
        include_affected_pkgs=request.include_rev_deps,
    )
    for package in package_deps:
        pkg_info_msg = response.package_deps.add()
        controller_util.serialize_package_info(package, pkg_info_msg)


def _StubGetToolchainPathsResponse(_request, response, _config) -> None:
    """Create a fake successful response for GetToolchainPaths."""
    stub_entry = response.paths.add()
    stub_entry.path = "src/third_party/stub-package"


@faux.success(_StubGetToolchainPathsResponse)
@faux.empty_error
@validate.validation_complete
def GetToolchainPaths(_request, response, _config) -> None:
    """Get a list of paths that affect the toolchain."""
    toolchain_paths = dependency.DetermineToolchainSourcePaths()
    for p in toolchain_paths:
        source_path = response.paths.add()
        source_path.path = p
