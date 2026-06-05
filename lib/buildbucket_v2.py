# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite Buildbucket V2 client wrapper and helpers.

The client constructor and methods here are tailored to Chromite's
usecases. Other users should, instead, prefer to copy the Python
client out of lib/luci/prpc and third_party/infra_libs/buildbucket.
"""

import http.client
import socket
from ssl import SSLError
from typing import Callable, Optional

from chromite.third_party.google.protobuf import field_mask_pb2
from chromite.third_party.infra_libs.buildbucket.proto import (
    builder_service_pb2,
    builder_service_prpc_pb2,
    builds_service_pb2,
    builds_service_prpc_pb2,
    common_pb2,
)

from chromite.lib import retry_util
from chromite.lib.luci import utils
from chromite.lib.luci.prpc.client import Client


BBV2_URL_ENDPOINT_PROD = "cr-buildbucket.appspot.com"
BBV2_URL_ENDPOINT_TEST = "cr-buildbucket-test.appspot.com"


class BuildbucketResponseException(Exception):
    """Exception got from Buildbucket Response."""


class NoBuildbucketBucketFoundException(Exception):
    """Failed to found the corresponding buildbucket bucket."""


class NoBuildbucketClientException(Exception):
    """No Buildbucket client exception."""


def GetStringPairValue(content, path, key, default=None):
    """Get the value of a repeated StringValue pair.

    Get the (nested) value from a nested dict.

    Args:
        content: A dict of (nested) attributes.
        path: String list presenting the (nested) attribute to get.
        key: String representing which key to find.
        default: Default value to return if the attribute doesn't exist.

    Returns:
        The corresponding value if the attribute exists; else, default.
    """
    assert isinstance(path, list), "nested_attr must be a list."

    if content is None:
        return default

    assert isinstance(content, dict), "content must be a dict."

    value = None
    path_value = content
    for attr in path:
        assert isinstance(attr, str), "attribute name must be a string."

        if not isinstance(path_value, dict):
            return default

        path_value = path_value.get(attr, default)

    for sp in path_value:
        dimensions_kv = list(sp.items())
        for i, (k, v) in enumerate(dimensions_kv):
            dimensions_kv[i] = (
                k,
                [
                    v,
                ],
            )
            if v == key:
                if len(dimensions_kv) >= i + 1:
                    return dimensions_kv[i + 1][i + 1]
    return value


def DateToTimeRange(start_date=None, end_date=None):
    """Convert two datetime.date objects into a TimeRange instance.

    Args:
        start_date: datetime.date instance to mark the start of the TimeRange.
        end_date: datetime.date instance to mark the end of the TimeRange.

    Returns:
        A TimeRange object corresponding to the time interval
        (start_date, end_date).
    """
    if not (start_date or end_date):
        return None
    if start_date:
        start_timestamp = utils.DatetimeToTimestamp(start_date)
    else:
        start_timestamp = None
    if end_date:
        end_timestamp = utils.DatetimeToTimestamp(end_date, end_of_day=True)
    else:
        end_timestamp = None
    return common_pb2.TimeRange(
        start_time=start_timestamp, end_time=end_timestamp
    )


def GetBotId(build):
    """Return the bot id that ran a build, or None.

    Args:
        build: BuildbucketV2 build

    Returns:
        hostname: Swarming hostname
    """
    # This produces a list of bot_ids for each build (or None).
    # I don't think there can ever be more than one entry in the list, but
    # could be zero.
    bot_id = GetStringPairValue(
        build, ["infra", "swarming", "botDimensions"], "id"
    )
    if not bot_id:
        return None

    return bot_id


class BuildbucketV2:
    """Connection to Buildbucket V2 database."""

    def __init__(
        self,
        test_env=False,
        access_token_retriever: Optional[Callable[[], str]] = None,
    ) -> None:
        """Constructor for Buildbucket V2 Build client.

        Args:
            test_env: Whether to have the client connect to test URL endpoint
                on GAE.
            access_token_retriever: An optional callable that returns an access
                token.
        """
        if test_env:
            self.client = Client(
                BBV2_URL_ENDPOINT_TEST,
                builds_service_prpc_pb2.BuildsServiceDescription,
            )
            self.builder_client = Client(
                BBV2_URL_ENDPOINT_TEST,
                builder_service_prpc_pb2.BuildersServiceDescription,
            )
        else:
            self.client = Client(
                BBV2_URL_ENDPOINT_PROD,
                builds_service_prpc_pb2.BuildsServiceDescription,
            )
            self.builder_client = Client(
                BBV2_URL_ENDPOINT_PROD,
                builder_service_prpc_pb2.BuildersServiceDescription,
            )

        self._access_token_retriever = access_token_retriever

    # TODO(crbug/1006818): Need to handle ResponseNotReady given by luci prpc.
    @retry_util.WithRetry(max_retry=5, sleep=20.0, exception=SSLError)
    @retry_util.WithRetry(max_retry=5, sleep=20.0, exception=socket.error)
    @retry_util.WithRetry(
        max_retry=5, sleep=20.0, exception=http.client.ResponseNotReady
    )
    def BatchGetBuilds(self, buildbucket_ids, properties=None):
        """BatchGetBuild repeated GetBuild request with provided ids.

        Args:
            buildbucket_ids: list of ids of the builds in buildbucket.
            properties: fields to include in the response.

        Returns:
            The corresponding BatchResponse message. See here:
            https://chromium.googlesource.com/infra/luci/luci-go/+/HEAD/buildbucket/proto/builds_service.proto
        """
        batch_requests = []
        for buildbucket_id in buildbucket_ids:
            batch_requests.append(
                builds_service_pb2.BatchRequest.Request(
                    get_build=(
                        builds_service_pb2.GetBuildRequest(
                            id=buildbucket_id,
                            fields=(
                                field_mask_pb2.FieldMask(paths=[properties])
                                if properties
                                else None
                            ),
                        )
                    )
                )
            )
        return self.client.Batch(
            builds_service_pb2.BatchRequest(requests=batch_requests),
            **self._client_kwargs,
        )

    # TODO(crbug/1006818): Need to handle ResponseNotReady given by luci prpc.
    @retry_util.WithRetry(max_retry=5, sleep=60.0, exception=SSLError)
    @retry_util.WithRetry(max_retry=5, sleep=60.0, exception=socket.error)
    @retry_util.WithRetry(max_retry=5, sleep=60.0, exception=socket.timeout)
    @retry_util.WithRetry(
        max_retry=5, sleep=60.0, exception=http.client.ResponseNotReady
    )
    def BatchSearchBuilds(self, search_requests):
        """SearchBuild RPC call wrapping function.

        Args:
            search_requests: List of SearchBuildRequests

        Returns:
            The corresponding BatchResponse message. See here:
            https://chromium.googlesource.com/infra/luci/luci-go/+/HEAD/buildbucket/proto/builds_service.proto
        """
        requests = []
        for request in search_requests:
            requests.append(
                builds_service_pb2.BatchRequest.Request(search_builds=request)
            )
        return self.client.Batch(
            builds_service_pb2.BatchRequest(requests=requests),
            **self._client_kwargs,
        )

    # TODO(crbug/1006818): Need to handle ResponseNotReady given by luci prpc.
    @retry_util.WithRetry(max_retry=5, sleep=20.0, exception=SSLError)
    @retry_util.WithRetry(max_retry=5, sleep=20.0, exception=socket.error)
    @retry_util.WithRetry(
        max_retry=5, sleep=20.0, exception=http.client.ResponseNotReady
    )
    def GetBuild(self, buildbucket_id, properties=None):
        """GetBuild call of a specific build with buildbucket_id.

        Args:
            buildbucket_id: id of the build in buildbucket.
            properties: list or string of fields to include in the response.

        Returns:
            The corresponding Build proto. See here:
            https://chromium.googlesource.com/infra/luci/luci-go/+/HEAD/buildbucket/proto/build.proto
        """
        field_mask = []
        if isinstance(properties, list):
            field_mask = properties
        elif properties:
            field_mask.append(properties)
        get_build_request = builds_service_pb2.GetBuildRequest(
            id=buildbucket_id,
            fields=(
                field_mask_pb2.FieldMask(paths=field_mask)
                if field_mask
                else None
            ),
        )
        return self.client.GetBuild(get_build_request, **self._client_kwargs)

    @retry_util.WithRetry(max_retry=3, sleep=0.2, exception=SSLError)
    @retry_util.WithRetry(max_retry=3, sleep=0.2, exception=socket.error)
    def SearchBuild(self, build_predicate, fields=None, page_size=100):
        """SearchBuild RPC call wrapping function.

        Args:
            build_predicate: Message containing builder, gerrit_changes and/or
            git_commits among other things.
            fields: A FieldMask instance to dictate the format of the response.
            page_size: Number of builds to return.

        Returns:
            A SearchBuildResponse instance corresponding to the query.
        """
        assert isinstance(build_predicate, builds_service_pb2.BuildPredicate)
        if fields is not None:
            assert isinstance(fields, field_mask_pb2.FieldMask)
        assert isinstance(page_size, int)
        if fields is None:
            search_build_request = builds_service_pb2.SearchBuildsRequest(
                predicate=build_predicate, page_size=page_size
            )
        else:
            search_build_request = builds_service_pb2.SearchBuildsRequest(
                predicate=build_predicate, fields=fields, page_size=page_size
            )

        return self.client.SearchBuilds(
            search_build_request, **self._client_kwargs
        )

    @retry_util.WithRetry(max_retry=3, sleep=0.2, exception=SSLError)
    @retry_util.WithRetry(max_retry=3, sleep=0.2, exception=socket.error)
    def ListBuilders(
        self,
        project: str,
        bucket: str,
        page_size: int = 100,
        page_token: str = "",
    ) -> builder_service_pb2.ListBuildersResponse:
        """ListBuilders RPC call wrapping function.

        Args:
            project: The name of the builder project (e.g. chromeos)
            bucket: The name of the builder bucket (e.g. release)
            page_size: How many results to return (default: 100)
            page_token: A page token, received from a previous `ListBuilders`
            call. Provide this to retrieve the subsequent page.

        Returns:
            A ListBuildersResponse instance corresponding to the query.
        """
        list_builders_request = builder_service_pb2.ListBuildersRequest(
            project=project,
            bucket=bucket,
            page_size=page_size,
            page_token=page_token,
        )

        return self.builder_client.ListBuilders(
            list_builders_request, **self._client_kwargs
        )

    @property
    def _client_kwargs(self):
        """Returns kwargs to be added to every rpc in the client.

        The client accepts the following arguments to its requests:
        timeout: int
        metadata: Dict[str, Any]
        credentials: Callable[[luci.prpc.client.Request],
            luci.prpc.client.Request]
        """
        kwargs = {}
        if self._access_token_retriever is not None:
            token = self._access_token_retriever()
            kwargs["metadata"] = {"Authorization": f"Bearer {token}"}
            kwargs["credentials"] = lambda req: req._replace(include_auth=False)
        return kwargs
