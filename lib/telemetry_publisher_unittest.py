# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for telemetry_publisher."""

import json

from chromite.api.gen.chromite.telemetry import trace_span_pb2
from chromite.lib import telemetry_publisher


def test_from_json_to_proto():
    """Test parsing a json span."""
    span = """\
{
    "name": "test",
    "context": {
        "trace_id": "0x5a4549df2c5474f889afa60af04e4e7d",
        "span_id": "0x5f6d5a1881c753c5",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": null,
    "start_time": "1970-01-01T00:00:01.000000Z",
    "end_time": "1970-01-01T00:00:10.000000Z",
    "status": {
        "status_code": "UNSET"
    },
    "attributes": {},
    "events": [
        {
            "name": "mid-sleep-event",
            "timestamp": "1970-01-01T00:00:02.345678Z",
            "attributes": {
                "attr": "val"
            }
        }
    ],
    "links": [],
    "resource": {
        "attributes": {
            "telemetry.sdk.language": "python",
            "telemetry.sdk.name": "opentelemetry",
            "telemetry.sdk.version": "1.17.0/0.40b0.dev",
            "service.name": "chromite",
            "process.runtime.description": "3.11.6 (main, Oct  8 2023, 05:06:43) [GCC 13.2.0]",
            "process.runtime.name": "cpython",
            "process.runtime.version": "3.11.6",
            "process.cwd": "/usr/local/google/home/ldap/chromiumos/chromite",
            "process.runtime.apiversion": 1013,
            "process.pid": 1200640,
            "process.owner": 572860,
            "process.executable.name": "python3",
            "process.executable.path": "/usr/bin/python3",
            "process.command": "./scripts/telemetry_poc",
            "process.command_args": [
                "--log-telemetry"
            ],
            "manifest_branch": "stable",
            "manifest_commit_date": "2024-01-12T04:37:57-08:00",
            "manifest_change_id": "I47fb27e77336bc34eeccf98e931758d537deedde",
            "manifest_commit_sha": "1bb5ee91c0cbce212546a62adacadd527b5262ca",
            "manifest_sync_date": "2024-01-12T16:41:40.913779+00:00",
            "workon_simple-fake-board": [
                "build-test/workon-pkg"
            ],
            "cpu.architecture": "x86_64",
            "cpu.count": 128,
            "cpu.name": "",
            "host.type": "Google Compute Engine",
            "memory.swap.total": 431509991424,
            "memory.total": 541005463552,
            "os.name": "posix",
            "os.type": "Linux",
            "os.description": "Linux-6.5.13-1rodete1-amd64-x86_64-with-glibc2.37",
            "development.ignore_span": true,
            "development.tag": "",
            "user.uuid": "d9556f6a-66aa-4c70-83af-919fbb1acb5a",
            "telemetry.version": "3"
        },
        "schema_url": ""
    }
}"""

    trace_span = telemetry_publisher.TraceSpan()
    trace_span.from_json(span)

    data = json.loads(span)

    message = trace_span_pb2.TraceSpan()
    trace_span.to_proto(message)

    # Basic data checks.
    assert data["name"] and data["name"] == trace_span.name == message.name
    assert trace_span.start_time_millis == message.start_time_millis == 1000
    assert trace_span.end_time_millis == message.end_time_millis == 10000

    # Context parsing checks.
    assert (
        data["context"]["span_id"]
        and data["context"]["span_id"]
        == trace_span.context.span_id
        == message.context.span_id
    )

    # Status parsing checks.
    assert data["status"]["status_code"] == "UNSET"
    assert (
        trace_span.status.status_code
        is telemetry_publisher.StatusCode.STATUS_CODE_OK
    )
    assert (
        message.status.status_code
        == trace_span_pb2.TraceSpan.Status.STATUS_CODE_OK
    )

    # Event parsing checks.
    event = data["events"][0]
    trace_event = trace_span.events[0]
    msg_event = message.events[0]

    assert event["name"] and event["name"] == trace_event.name == msg_event.name
    assert (
        event["attributes"]["attr"]
        and event["attributes"]["attr"]
        == trace_event.attributes["attr"]
        == msg_event.attributes["attr"]
    )
    assert trace_event.event_time_millis == msg_event.event_time_millis == 2345

    # Resource parsing checks.
    res_attrs = data["resource"]["attributes"]
    # Resource attribute to resource attribute.
    assert (
        res_attrs["development.ignore_span"]
        and res_attrs["development.ignore_span"]
        == trace_span.resource.attributes["development.ignore_span"]
        == message.resource.attributes["development.ignore_span"]
    )

    # Resource attribute to Telemetry SDK field.
    assert (
        res_attrs["telemetry.sdk.version"]
        and res_attrs["telemetry.sdk.version"]
        == trace_span.telemetry_sdk.version
        == message.telemetry_sdk.version
    )
    # Make sure the attribute is consumed.
    assert "telemetry.sdk.version" not in trace_span.resource.attributes
    assert "telemetry.sdk.version" not in message.resource.attributes

    # Resource attribute to Resource.Process field.
    assert (
        res_attrs["process.pid"]
        and str(res_attrs["process.pid"])
        == trace_span.resource.process.pid
        == message.resource.process.pid
    )
    # Make sure the attribute is consumed.
    assert "process.pid" not in trace_span.resource.attributes
    assert "process.pid" not in message.resource.attributes

    # A list/repeated field.
    assert (
        res_attrs["process.command_args"]
        and isinstance(res_attrs["process.command_args"], list)
        and res_attrs["process.command_args"]
        == trace_span.resource.process.command_args
        == message.resource.process.command_args
    )
    assert (
        res_attrs["process.runtime.name"]
        and res_attrs["process.runtime.name"]
        == trace_span.resource.process.runtime_name
        == message.resource.process.runtime_name
    )
    assert not trace_span.resource.process.owner_is_root
    assert not message.resource.process.owner_is_root
    # Resource attribute to Resource.System field.
    assert (
        res_attrs["os.name"]
        == trace_span.resource.system.os_name
        == message.resource.system.os_name
    )
    assert "os.name" not in trace_span.resource.attributes
    assert "os.name" not in message.resource.attributes
