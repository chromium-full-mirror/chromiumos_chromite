# Copyright 2018 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for buildbucket_v2."""

from datetime import date
from typing import Any

from chromite.third_party.google.protobuf import field_mask_pb2
from chromite.third_party.infra_libs.buildbucket.proto import (
    builder_common_pb2,
    builds_service_pb2,
    common_pb2,
)

from chromite.lib import buildbucket_v2
from chromite.lib import cros_test_lib
from chromite.lib.luci.prpc.client import Client
from chromite.lib.luci.prpc.client import new_request


SUCCESS_BUILD = {
    "infra": {
        "swarming": {
            "botDimensions": [
                {"key": "cores", "value": "32"},
                {"key": "cpu", "value": "x86"},
                {"key": "cpu", "value": "x86-64"},
                {"key": "cpu", "value": "x86-64-Haswell_GCE"},
                {"key": "cpu", "value": "x86-64-avx2"},
                {"key": "gce", "value": "1"},
                {"key": "gcp", "value": "chromeos-bot"},
                {"key": "id", "value": "chromeos-ci-test-bot"},
                {
                    "key": "image",
                    "value": "chromeos-bionic-21021400-a1c0533ad76",
                },
                {"key": "machine_type", "value": "e2-standard-32"},
                {"key": "pool", "value": "ChromeOS"},
                {"key": "role", "value": "legacy-release"},
                {"key": "zone", "value": "us-central1-b"},
            ]
        }
    }
}


class BuildbucketV2Test(cros_test_lib.MockTestCase):
    """Tests for buildbucket_v2."""

    # pylint: disable=attribute-defined-outside-init

    def testCreatesClient(self) -> None:
        ret = buildbucket_v2.BuildbucketV2(test_env=True)
        self.assertIsInstance(ret.client, Client)

    def testCreatesBuilderClient(self) -> None:
        ret = buildbucket_v2.BuildbucketV2(test_env=True)
        self.assertIsInstance(ret.builder_client, Client)

    def testBatchGetBuilds(self) -> None:
        fake_field_mask = field_mask_pb2.FieldMask(paths=["properties"])
        fake_batch_request = object()
        bbv2 = buildbucket_v2.BuildbucketV2()
        client = bbv2.client
        self.batch_get_build_request_fn = self.PatchObject(
            builds_service_pb2, "BatchRequest", return_value=fake_batch_request
        )
        self.batch_get_function = self.PatchObject(client, "Batch")
        bbv2.BatchGetBuilds([1234, 1235], "properties")
        fake_builds = [
            builds_service_pb2.BatchRequest.Request(
                get_build=(
                    builds_service_pb2.GetBuildRequest(
                        id=1234, fields=fake_field_mask
                    ),
                ),
            ),
            builds_service_pb2.BatchRequest.Request(
                get_build=(
                    builds_service_pb2.GetBuildRequest(
                        id=1235, fields=fake_field_mask
                    ),
                ),
            ),
        ]
        self.batch_get_build_request_fn.assert_called_with(requests=fake_builds)
        self.batch_get_function.assert_called_with(fake_batch_request)

    def testBatchSearchBuilds(self) -> None:
        fake_batch_request = object()
        bbv2 = buildbucket_v2.BuildbucketV2()
        builder = builder_common_pb2.BuilderID(
            project="chromeos", bucket="general"
        )
        tag = common_pb2.StringPair(
            key="cbb_master_buildbucket_id", value=str(1234)
        )
        build_predicate = builds_service_pb2.BuildPredicate(
            builder=builder, tags=[tag]
        )
        client = bbv2.client
        self.batch_search_build_request_fn = self.PatchObject(
            builds_service_pb2, "BatchRequest", return_value=fake_batch_request
        )
        self.batch_search_function = self.PatchObject(client, "Batch")
        search_request = [
            builds_service_pb2.SearchBuildsRequest(predicate=build_predicate)
        ]
        bbv2.BatchSearchBuilds(search_request)
        fake_builds = [
            builds_service_pb2.BatchRequest.Request(
                search_builds=(
                    builds_service_pb2.SearchBuildsRequest(
                        predicate=build_predicate,
                    ),
                ),
            ),
        ]
        self.batch_search_build_request_fn.assert_called_with(
            requests=fake_builds
        )
        self.batch_search_function.assert_called_with(fake_batch_request)

    def testGetBuildWithMultipleProperties(self) -> None:
        fake_field_mask = field_mask_pb2.FieldMask(
            paths=["output.properties", "id", "status", "summary_markdown"]
        )
        fake_get_build_request = object()
        bbv2 = buildbucket_v2.BuildbucketV2()
        client = bbv2.client
        self.get_build_request_fn = self.PatchObject(
            builds_service_pb2,
            "GetBuildRequest",
            return_value=fake_get_build_request,
        )
        self.get_build_function = self.PatchObject(client, "GetBuild")
        bbv2.GetBuild(
            "some-id", ["output.properties", "id", "status", "summary_markdown"]
        )
        self.get_build_request_fn.assert_called_with(
            id="some-id", fields=fake_field_mask
        )
        self.get_build_function.assert_called_with(fake_get_build_request)

    def testGetBuildWithOneProperty(self) -> None:
        fake_field_mask = field_mask_pb2.FieldMask(paths=["output.properties"])
        fake_get_build_request = object()
        bbv2 = buildbucket_v2.BuildbucketV2()
        client = bbv2.client
        self.get_build_request_fn = self.PatchObject(
            builds_service_pb2,
            "GetBuildRequest",
            return_value=fake_get_build_request,
        )
        self.get_build_function = self.PatchObject(client, "GetBuild")
        bbv2.GetBuild("some-id", "output.properties")
        self.get_build_request_fn.assert_called_with(
            id="some-id", fields=fake_field_mask
        )
        self.get_build_function.assert_called_with(fake_get_build_request)

    def testGetBuildWithoutProperties(self) -> None:
        fake_get_build_request = object()
        bbv2 = buildbucket_v2.BuildbucketV2()
        client = bbv2.client
        self.get_build_request_fn = self.PatchObject(
            builds_service_pb2,
            "GetBuildRequest",
            return_value=fake_get_build_request,
        )
        self.get_build_function = self.PatchObject(client, "GetBuild")
        bbv2.GetBuild("some-id")
        self.get_build_request_fn.assert_called_with(id="some-id", fields=None)
        self.get_build_function.assert_called_with(fake_get_build_request)

    def testSearchBuildExceptionCases(self) -> None:
        """Test scenarios where SearchBuild raises an Exception."""
        bbv2 = buildbucket_v2.BuildbucketV2()
        builder = builder_common_pb2.BuilderID(
            project="chromeos", bucket="general"
        )
        tag = common_pb2.StringPair(
            key="cbb_master_buildbucket_id", value=str(1234)
        )
        build_predicate = builds_service_pb2.BuildPredicate(
            builder=builder, tags=[tag]
        )
        with self.assertRaises(AssertionError):
            bbv2.SearchBuild(None, None, 100)
        with self.assertRaises(AssertionError):
            bbv2.SearchBuild(build_predicate, None, None)
        with self.assertRaises(AssertionError):
            bbv2.SearchBuild(build_predicate, "str_fields", 100)

    def testSearchBuild(self) -> None:
        """Test redirection to the underlying RPC call."""
        bbv2 = buildbucket_v2.BuildbucketV2()
        builder = builder_common_pb2.BuilderID(
            project="chromeos", bucket="general"
        )
        tag = common_pb2.StringPair(
            key="cbb_master_buildbucket_id", value=str(1234)
        )
        build_predicate = builds_service_pb2.BuildPredicate(
            builder=builder, tags=[tag]
        )
        fields = field_mask_pb2.FieldMask()
        search_builds_fn = self.PatchObject(bbv2.client, "SearchBuilds")
        bbv2.SearchBuild(build_predicate, fields=fields, page_size=123)
        search_builds_fn.assert_called_once_with(
            builds_service_pb2.SearchBuildsRequest(
                predicate=build_predicate, fields=fields, page_size=123
            )
        )


class StaticFunctionsTest(cros_test_lib.MockTestCase):
    """Test static functions in lib/buildbucket_v2.py."""

    # pylint: disable=attribute-defined-outside-init

    def testDateToTimeRangeNoneInput(self) -> None:
        self.assertIsNone(buildbucket_v2.DateToTimeRange(None))

    def testDateToTimeRangeStartDate(self) -> None:
        date_example = date(2019, 4, 15)
        result = buildbucket_v2.DateToTimeRange(start_date=date_example)
        self.assertEqual(result.start_time.seconds, 1555286400)
        self.assertEqual(result.end_time.seconds, 0)

    def testDateToTimeRangeEndDate(self) -> None:
        date_example = date(2019, 4, 15)
        result = buildbucket_v2.DateToTimeRange(end_date=date_example)
        self.assertEqual(result.end_time.seconds, 1555372740)
        self.assertEqual(result.start_time.seconds, 0)

    def testGetStringPairValue(self) -> None:
        bot_id = buildbucket_v2.GetStringPairValue(
            SUCCESS_BUILD, ["infra", "swarming", "botDimensions"], "id"
        )
        self.assertEqual(bot_id, "chromeos-ci-test-bot")
        pool = buildbucket_v2.GetStringPairValue(
            SUCCESS_BUILD, ["infra", "swarming", "botDimensions"], "pool"
        )
        self.assertEqual(pool, "ChromeOS")
        role = buildbucket_v2.GetStringPairValue(
            SUCCESS_BUILD, ["infra", "swarming", "botDimensions"], "role"
        )
        self.assertEqual(role, "legacy-release")

    def testGetBotId(self) -> None:
        bot_id = buildbucket_v2.GetBotId(SUCCESS_BUILD)
        self.assertEqual(bot_id, "chromeos-ci-test-bot")

    def testCredentials(self) -> None:
        fake_get_build_request = object()
        bbv2 = buildbucket_v2.BuildbucketV2(
            access_token_retriever=lambda: "some-token"
        )
        client = bbv2.client
        self.PatchObject(
            builds_service_pb2,
            "GetBuildRequest",
            return_value=fake_get_build_request,
        )
        get_build_function = self.PatchObject(client, "GetBuild")
        bbv2.GetBuild("some-id")

        class DisableAuthFn:
            """An object that can be compared to a function"""

            def __eq__(self, fn: Any) -> bool:
                request = new_request("a", "b", "c", "d", "e")
                return not fn(request).include_auth

        get_build_function.assert_called_with(
            fake_get_build_request,
            metadata={"Authorization": "Bearer some-token"},
            credentials=DisableAuthFn(),
        )
