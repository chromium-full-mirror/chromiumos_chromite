# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for telemetry_publisher."""

import json

from chromite.api.gen.chromite.telemetry import clientanalytics_pb2
from chromite.api.gen.chromite.telemetry import trace_span_pb2
from chromite.lib import osutils
from chromite.lib import telemetry_publisher


_SPAN = """\
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


def test_from_json_to_proto() -> None:
    """Test parsing a json span and populating a proto."""
    trace_span = telemetry_publisher.TraceSpan()
    trace_span.from_json(_SPAN)

    data = json.loads(_SPAN)

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


def test_prepare_request_body() -> None:
    """Test LogRequest population."""
    spans = [telemetry_publisher.TraceSpan.parse(_SPAN)]

    publisher = telemetry_publisher.ClearcutPublisher(max_batch_size=1)
    # pylint: disable-next=protected-access
    request = publisher._prepare_request_body(spans)

    # Verify the payload in the request matches the span's proto.
    expected = trace_span_pb2.TraceSpan()
    telemetry_publisher.TraceSpan.parse(_SPAN).to_proto(expected)

    parsed = trace_span_pb2.TraceSpan()
    parsed.ParseFromString(request.log_event[0].source_extension)

    assert expected == parsed


def test_max_batch_size(monkeypatch) -> None:
    """Verify max_batch_size is respected."""
    monkeypatch.setattr(
        telemetry_publisher.ClearcutPublisher,
        "_do_publish_request",
        lambda *args, **kwargs: clientanalytics_pb2.LogResponse(
            next_request_wait_millis=10000
        ),
    )

    publisher = telemetry_publisher.ClearcutPublisher(max_batch_size=2)
    assert not publisher.queue([_SPAN, _SPAN, _SPAN])
    assert publisher.queue([_SPAN, _SPAN])

    publisher.publish()
    assert not publisher.queue_len


def test_next_request_wait(monkeypatch) -> None:
    """Verify response's next_request_wait_millis is respected."""
    # Force a 24-hour wait time.
    response = clientanalytics_pb2.LogResponse(
        next_request_wait_millis=1000 * 60 * 60 * 24
    )
    monkeypatch.setattr(
        telemetry_publisher.ClearcutPublisher,
        "_do_publish_request",
        lambda *args, **kwargs: response,
    )

    publisher = telemetry_publisher.ClearcutPublisher()
    # Shouldn't be a wait time for a freshly initialized instance.
    assert not publisher.wait_time
    # Should publish successfully.
    assert publisher.queue([_SPAN])
    publisher.publish()
    # Verify new wait time is close to the 24 hours.
    # If this test takes more than 6 minutes to run we've got issues.
    assert publisher.wait_time > int(60 * 60 * 23.9)


def test_extract_from_files(monkeypatch, tmp_path) -> None:
    """Test extracting spans from files."""
    monkeypatch.setattr(
        telemetry_publisher, "_get_telemetry_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        telemetry_publisher, "_get_other_telemetry_dirs", lambda: []
    )

    trace_file = tmp_path / "foo.otel.traces.json"
    span = json.loads(_SPAN)
    trace_file.write_text(json.dumps(span))

    expected = [telemetry_publisher.TraceSpan.parse(_SPAN)]

    publisher = telemetry_publisher.ClearcutPublisher()
    # pylint: disable=protected-access
    telemetry_publisher._parse_files(publisher)

    assert expected == publisher._queue


def test_telemetry_file_publishing_succeeded(tmp_path) -> None:
    """Test TelemetryFile.publishing_succeeded."""
    f = tmp_path / "foo.otel.traces.json"
    f.touch()

    telemetry_file = telemetry_publisher.TelemetryFile(f)

    # Precondition checks.
    assert f.exists()
    assert telemetry_file.is_publishable
    assert not telemetry_file.is_published

    # "Publish".
    telemetry_file.publishing_succeeded()

    # Postcondition checks.
    assert telemetry_file.is_published
    assert not telemetry_file.is_publishable
    # pylint: disable=protected-access
    assert telemetry_file._published_file.exists()
    assert telemetry_file._published_file.parent == tmp_path

    telemetry_file.delete(age=0)

    # Delete postcondition checks.
    assert not f.exists()
    assert not telemetry_file._published_file.exists()


def test_telemetry_file_parsing_failed(tmp_path) -> None:
    """Test TelemetryFile.parsing_failed."""
    f = tmp_path / "foo.otel.traces.json"
    f.touch()

    telemetry_file = telemetry_publisher.TelemetryFile(f)

    # Precondition checks.
    assert f.exists()
    assert telemetry_file.is_publishable
    assert not telemetry_file.is_failed_parsing

    # "Fail parsing".
    telemetry_file.parsing_failed()

    # Postcondition checks.
    assert not telemetry_file.is_publishable
    assert telemetry_file.is_failed_parsing
    # pylint: disable=protected-access
    assert telemetry_file._parse_failed_file.exists()
    assert telemetry_file._parse_failed_file.parent == tmp_path

    telemetry_file.delete(age=0)

    # Delete postcondition checks.
    assert not f.exists()
    assert not telemetry_file._parse_failed_file.exists()


def test_telemetry_file_publishing_failed(tmp_path) -> None:
    """Test TelemetryFile.publishing_failed."""
    f = tmp_path / "foo.otel.traces.json"
    f.touch()

    telemetry_file = telemetry_publisher.TelemetryFile(f)

    # Precondition checks.
    assert f.exists()
    assert telemetry_file.is_publishable
    assert not telemetry_file.is_failed_publishing

    # "Fail publishing".
    telemetry_file.publishing_failed()

    # Postcondition checks.
    assert not telemetry_file.is_publishable
    assert telemetry_file.is_failed_publishing
    # pylint: disable=protected-access
    assert telemetry_file._publish_failed_file.exists()
    assert telemetry_file._publish_failed_file.parent == tmp_path

    telemetry_file.delete(age=0)

    # Delete postcondition checks.
    assert not f.exists()
    assert not telemetry_file._publish_failed_file.exists()


def test_telemetry_file_in_progress(tmp_path) -> None:
    """Test the in-progress file from the exporter."""
    f = tmp_path / "foo.otel.traces.json"
    f.touch()
    in_progress = f.with_name(f".{f.name}.in-progress")

    telemetry_file = telemetry_publisher.TelemetryFile(f)

    # Precondition checks.
    assert f.exists()
    assert not in_progress.exists()
    assert telemetry_file.is_publishable

    in_progress.touch()
    assert in_progress.exists()
    assert not telemetry_file.is_publishable

    telemetry_file.delete(age=0)

    # Delete postcondition checks.
    assert not f.exists()
    assert not in_progress.exists()


def test_telemetry_file_spans(tmp_path) -> None:
    """Test TelemetryFile.spans."""
    f = tmp_path / "foo.otel.traces.json"
    f.touch()

    telemetry_file = telemetry_publisher.TelemetryFile(f)
    assert not telemetry_file.spans

    # TelemetryFile currently doesn't do any validation/parsing of the span
    # contents, so we can write arbitrary data to test the splitting.
    f.write_text("a\nb\nc\nd\n \n\t\n", encoding="utf-8")
    # spans is a cached property to avoid extraneous reads. This can be changed,
    # just have a test to make sure changes to it are tested.
    assert not telemetry_file.spans
    # Make a new one to test the "spans" we wrote.
    telemetry_file = telemetry_publisher.TelemetryFile(f)
    assert len(telemetry_file.spans) == 4


def test_other_telemetry_dirs(tmp_path, monkeypatch) -> None:
    """Test other telemetry data handling."""
    other = tmp_path / "other"
    f = other / "nested" / "foo.otel.traces.json"
    telemetry_dir = tmp_path / "telemetry"
    expected_file = telemetry_dir / f.relative_to(other)

    osutils.SafeMakedirs(f.parent, sudo=True)
    osutils.WriteFile(f, _SPAN, sudo=True)
    osutils.SafeMakedirsNonRoot(telemetry_dir)

    monkeypatch.setattr(
        telemetry_publisher, "_get_telemetry_dir", lambda: telemetry_dir
    )
    monkeypatch.setattr(
        telemetry_publisher, "_get_other_telemetry_dirs", lambda: [other]
    )
    # pylint: disable-next=protected-access
    telemetry_publisher._move_other_telemetry_files()

    assert not f.exists()
    assert expected_file.exists()
    assert expected_file.read_text(encoding="utf-8") == _SPAN
    assert expected_file.stat().st_uid
