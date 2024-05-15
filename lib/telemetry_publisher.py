# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parse and publish telemetry."""

import dataclasses
import datetime
import enum
import functools
import json
import logging
import os
import socket
import time
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    TYPE_CHECKING,
    Union,
)
import urllib.error
import urllib.request

from chromite.third_party.google.protobuf import json_format
from chromite.third_party.google.protobuf import message as proto_msg
from chromite.third_party.opentelemetry.sdk import resources

# Required due to incomplete proto support in chromite. This proto usage is not
# tied to the Build API, so delegating the proto handling to api/ does not make
# sense. When proto is better supported in chromite, the protos could live
# somewhere else instead.
from chromite.api.gen.chromite.telemetry import clientanalytics_pb2
from chromite.api.gen.chromite.telemetry import trace_span_pb2
from chromite.lib import cros_build_lib
from chromite.lib import locking
from chromite.lib import osutils
from chromite.lib import path_util
from chromite.lib.telemetry import trace
from chromite.utils.telemetry import detector
from chromite.utils.telemetry import utils


if TYPE_CHECKING:
    from pathlib import Path

tracer = trace.get_tracer(__name__)

_DEFAULT_ENDPOINT = "https://play.googleapis.com/log"
_DEFAULT_TIMEOUT = 15
_DEAULT_MAX_WAIT_SECS = 20 * 60
_DEFAULT_MAX_BATCH_SIZE = 20000
# Preallocated in Clearcut proto to Build.
_LOG_SOURCE = 2044
# Preallocated in Clearcut proto to Python clients.
_CLIENT_TYPE = 33

# How long to keep telemetry before deleting.
_TELEMETRY_PURGE_AGE = 7 * 24 * 60 * 60


class Error(Exception):
    """Base error class for the module."""


class ParseSpanError(Error):
    """Error parsing a span."""


class PublishError(Error):
    """An error encountered while publishing."""


@functools.lru_cache
def _get_telemetry_dir() -> "Path":
    """Get the base telemetry log directory."""
    return path_util.get_log_dir() / "telemetry"


def _get_other_telemetry_dirs() -> List["Path"]:
    """Get other directories with telemetry and their telemetry_dir mapping."""
    return [
        path_util.get_log_dir() / "portage" / "telemetry",
    ]


@functools.lru_cache
def _get_publisher_file() -> "Path":
    """Get the publisher PID file."""
    return _get_telemetry_dir() / ".telemetry_publisher_pid"


@functools.lru_cache
def _get_next_publish_ts_file() -> "Path":
    """Get the telemetry next publish ts file."""
    return _get_telemetry_dir() / ".telemetry_next_publish_ts"


@functools.lru_cache
def _has_internet() -> bool:
    """Check internet connection."""
    try:
        # Try to connect to a Google DNS server as a quick internet-works check.
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(
            ("8.8.8.8", 53)
        )
        return True
    except socket.error as e:
        logging.debug("No internet detected.")
        logging.exception(e)
        return False


def can_publish():
    """Check if publishing is possible."""
    next_publish = _get_next_publish_ts_file()
    if not next_publish.exists():
        # No timestamp recorded, we can publish if we have internet access.
        # The internet check is mostly meant to avoid attempting to publish when
        # the network is disabled, e.g. the network sandbox used by cros
        # build-image, but generally avoiding trying to publish when it's doomed
        # to fail is nice.
        return _has_internet()

    next_publish_lock = locking.FileLock(next_publish, locktype=locking.FLOCK)
    next_publish_ts = None
    with next_publish_lock.read_lock():
        if next_publish.exists():
            try:
                next_publish_ts = float(next_publish.read_text())
            except Exception as e:
                logging.error(e)

    logging.debug("next_publish_ts: %s", next_publish_ts)
    logging.debug("current time: %s", time.time())
    if next_publish_ts and time.time() < next_publish_ts:
        logging.debug("Too soon to publish again.")
        return False

    # The next publish timestamp has passed, we can publish if we have internet.
    return _has_internet()


@tracer.start_as_current_span("chromite.lib.telemetry_publisher.publish")
def publish():
    """Parse telemetry from files and publish a batch."""
    publisher_file = _get_publisher_file()
    next_publish = _get_next_publish_ts_file()
    publisher_lock = locking.FileLock(publisher_file, locktype=locking.FLOCK)
    next_publish_lock = locking.FileLock(next_publish, locktype=locking.FLOCK)

    if not can_publish():
        # Short circuit publisher file lock when we can't publish anyway.
        return

    publisher = ClearcutPublisher()

    logging.debug("Acquiring lock.")
    with publisher_lock.write_lock():
        if not can_publish():
            # Double check we weren't waiting on a now-completed publisher.
            return

        # Log our PID.
        publisher_file.write_text(str(os.getpid()))

        logging.debug("Parsing files.")
        pending_files = _parse_files(publisher)

        span = trace.get_current_span()
        span.set_attribute("file_count", len(pending_files))
        span.set_attribute("span_count", publisher.queue_len)
        logging.debug(
            "Publishing %s files containing %s spans.",
            len(pending_files),
            publisher.queue_len,
        )

        # Do the publishing.
        try:
            publisher.publish()
        except PublishError:
            _post_publish_failure_actions(pending_files)
            publisher_file.unlink()
            raise

        # Write out the next publish TS.
        with next_publish_lock.write_lock():
            next_publish.write_text(str(publisher.next_publish_ts))

        logging.debug("Next request: %s", publisher.next_request_dt.isoformat())
        _post_publish_actions(pending_files)

        # Drop the PID file and we're done.
        publisher_file.unlink()

    logging.notice("Publish complete.")


@tracer.start_as_current_span("chromite.lib.telemetry_publisher._parse_files")
def _parse_files(publisher: "ClearcutPublisher") -> List["TelemetryFile"]:
    """Parse relevant files from the telemetry log dir and queue their spans."""
    pending_files = []
    for current in _get_telemetry_files():
        logging.debug("Processing: %s", current)

        if not current.is_publishable:
            continue

        if not current.spans:
            # This should be redundant since is_publishable checks for the
            # in-progress file, but just in case there's a race condition...
            continue

        try:
            queued = publisher.queue(current.spans)
        except ParseSpanError as e:
            logging.warning(e)
            current.parsing_failed()
            continue

        if queued:
            logging.debug(
                "Queued: %s with %s spans", current, len(current.spans)
            )
            pending_files.append(current)
        else:
            break

    return pending_files


@tracer.start_as_current_span(
    "chromite.lib.telemetry_publisher._post_publish_actions"
)
def _post_publish_actions(pending_files: List["TelemetryFile"]):
    """Post-publish actions for all published files."""
    # Mark the just published files as published.
    for file in pending_files:
        file.publishing_succeeded()

    # Clean out old telemetry files.
    # We need to convert it to a list because deletions can cause problems for
    # the rglob iterator.
    for file in list(_get_telemetry_files()):
        file.delete(age=_TELEMETRY_PURGE_AGE)

    # Clean out old publisher logs.
    publisher_logs = _get_telemetry_dir() / ".publisher_logs"
    cutoff = time.time() - _TELEMETRY_PURGE_AGE
    for file in publisher_logs.iterdir():
        if file.stat().st_mtime < cutoff:
            try:
                osutils.SafeUnlink(file, sudo=True)
            except cros_build_lib.RunCommandError as e:
                logging.warning("Error deleting %s: %s", file, e)


def _post_publish_failure_actions(pending_files: Iterable["TelemetryFile"]):
    """Anything that needs to be done on a publishing failure."""
    for file in pending_files:
        file.publishing_failed()


def _get_telemetry_files() -> Iterable["TelemetryFile"]:
    """Get all telemetry files on disk."""
    _move_other_telemetry_files()
    for current in _get_telemetry_dir().rglob("*.otel.traces.json"):
        yield TelemetryFile(current)


def _move_other_telemetry_files():
    """Move other telemetry files into the standard telemetry directory."""
    # Make a copy of each file in our telemetry directory, and then delete from
    # the source location to make sure we don't re-copy them since we don't need
    # them at the source location anymore. We can't use osutils.MoveDirContents
    # since there may be in-progress files we don't want to disrupt.
    # Note: These semantics were selected because the portage emerge telemetry
    # use case was the only use case when written. Portage copies the directory
    # structure we use in the standard telemetry directory, but under
    # /var/log/portage/telemetry, and always writes the files as root.
    for source in _get_other_telemetry_dirs():
        for f in source.rglob("*.otel.traces.json"):
            # Write the file to the same relative location.
            dest = _get_telemetry_dir() / f.relative_to(source)
            osutils.SafeMakedirsNonRoot(dest.parent)
            osutils.WriteFile(
                dest,
                osutils.ReadFile(f, encoding="utf-8", sudo=True),
                encoding="utf-8",
            )
            osutils.Chown(dest, user=True)
            osutils.SafeUnlink(f, sudo=True)


class TelemetryFile:
    """Telemetry file class."""

    def __init__(self, path: "Path"):
        self._path = path

    def __str__(self):
        return str(self._path)

    @functools.cached_property
    def spans(self):
        """Get the spans from the file."""
        return [
            x.strip() for x in self._path.read_text().splitlines() if x.strip()
        ]

    # Metadata file properties used to track the status of the telemetry.
    def _metadata_file(self, metadata_type):
        return self._path.with_name(f".{self._path.name}.{metadata_type}")

    @property
    def _published_file(self):
        return self._metadata_file("published")

    @property
    def _publish_failed_file(self):
        return self._metadata_file("publish-failed")

    @property
    def _parse_failed_file(self):
        return self._metadata_file("parse-failed")

    @property
    def _in_progress_file(self):
        return self._metadata_file("in-progress")

    # Telemetry status properties.
    @property
    def is_published(self):
        return self._published_file.exists()

    @property
    def is_failed_publishing(self):
        return self._publish_failed_file.exists()

    @property
    def is_failed_parsing(self):
        return self._parse_failed_file.exists()

    @property
    def is_pending(self):
        return self._in_progress_file.exists()

    @property
    def is_publishable(self) -> bool:
        return self._path.exists() and not (
            self.is_published
            or self.is_pending
            or self.is_failed_publishing
            or self.is_failed_parsing
        )

    # Actions performed on the various results.
    def parsing_failed(self) -> None:
        """To be called when the file could not be parsed."""
        self._parse_failed_file.touch()

    def publishing_failed(self) -> None:
        """To be called on failing to publish."""
        # TODO: Add retry mechanism to accommodate external failures: network
        #  flakes, clearcut outages, etc.
        self._publish_failed_file.touch()

    def publishing_succeeded(self) -> None:
        """To be called on successfully being published."""
        self._published_file.touch()

    def _is_younger_than(self, age: int) -> bool:
        return (time.time() - self._path.stat().st_mtime) < age

    def delete(self, age: int):
        """Delete the telemetry and relevant metadata if older than |age|.

        Args:
            age: The age in seconds to serve as the cutoff for keeping the file.
        """
        if age and self._is_younger_than(age):
            return

        def _delete(f: "Path"):
            if not f.exists():
                return
            try:
                osutils.SafeUnlink(f, sudo=True)
            except cros_build_lib.RunCommandError as e:
                # Doesn't exist for some reason.
                logging.warning("Unable to delete %s:", f)
                logging.warning(e)

        # Delete the file itself plus all metadata files.
        _delete(self._path)
        _delete(self._publish_failed_file)
        _delete(self._published_file)
        _delete(self._parse_failed_file)
        _delete(self._in_progress_file)

        # Try to clear out empty parent directories.
        for parent in self._path.parents:
            if _get_telemetry_dir() not in parent.parents:
                # At or above telemetry dir.
                break

            try:
                parent.rmdir()
            except OSError:
                # It's not empty.
                break


class TraceSpanDataclassMixin:
    """Mixin to facilitate translating from otel span json to TraceSpan proto.

    This is a one way translation from opentelemetry's json-encoded spans to our
    TraceSpan proto, but the reverse case isn't supported (or needed).
    For example, `x.from_json(data).to_json() == data` CANNOT be asserted.
    """

    def _field_mapping(self) -> Dict[str, str]:
        """Get the {otel: TraceSpan} field name mapping.

        Used to map a field from the otel representation to the dataclass field.
        This needs only be populated for fields where the names differ.
        """
        return {}

    def to_dict(self):
        """Convert to a dict."""

        def _dict_factory(values):
            """Dict factory to convert enums to their value."""
            return {
                k: v.value if isinstance(v, enum.Enum) else v for k, v in values
            }

        return dataclasses.asdict(self, dict_factory=_dict_factory)

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        """Populate from an otel span dict.

        Args:
            mapping: The relevant portion of the parsed otel span data.
                NOTE: There are no guaranteed post conditions for the contents
                of |mapping|, so pass a copy if you want the original data
                intact.

        Returns:
            A dict containing the unused portion of |mapping|.
        """
        field_mapping = self._field_mapping()
        remaining = {}
        for k, v in mapping.items():
            k_attr = field_mapping.get(k, k)
            if not hasattr(self, k_attr):
                # Return unconsumed fields.
                remaining[k] = v
                continue

            current = getattr(self, k_attr)
            current_type = type(current)
            if current_type == type(v):
                # All the scalars.
                setattr(self, k_attr, v)
            elif hasattr(current_type, "from_span_value"):
                # Enums, create a new instance with the value.
                setattr(self, k_attr, current_type.from_span_value(v))
            elif isinstance(current, TraceSpanDataclassMixin):
                # A nested class.
                current.from_dict(v)

        return remaining

    def to_json(self, indent: Optional[int] = None):
        """Dump to json."""
        return json.dumps(self.to_dict(), indent=indent)

    def from_json(self, content: str):
        """Parse an otel span json string."""
        self.from_dict(json.loads(content))

    def to_proto(self, message: "proto_msg.Message"):
        """Populate a proto."""
        json_format.ParseDict(
            self.to_dict(), message, ignore_unknown_fields=True
        )


@dataclasses.dataclass
class TelemetrySdk(TraceSpanDataclassMixin):
    """Telemetry SDK dataclass."""

    name: str = ""
    version: str = ""
    language: str = ""

    def _field_mapping(self) -> Dict[str, str]:
        return {
            resources.TELEMETRY_SDK_NAME: "name",
            resources.TELEMETRY_SDK_VERSION: "version",
            resources.TELEMETRY_SDK_LANGUAGE: "language",
        }


@dataclasses.dataclass
class System(TraceSpanDataclassMixin):
    """System information."""

    os_name: str = ""
    os_version: str = ""
    os_type: str = ""
    cpu: str = ""
    host_architecture: str = ""

    def _field_mapping(self) -> Dict[str, str]:
        return {
            detector.OS_NAME: "os_name",
            resources.OS_DESCRIPTION: "os_version",
            resources.OS_TYPE: "os_type",
            detector.CPU_NAME: "cpu",
            detector.CPU_ARCHITECTURE: "host_architecture",
        }


@dataclasses.dataclass
class Process(TraceSpanDataclassMixin):
    """Process dataclass."""

    pid: str = ""
    executable_name: str = ""
    executable_path: str = ""
    command: str = ""
    command_args: List[str] = dataclasses.field(default_factory=list)
    owner_is_root: bool = False
    runtime_name: str = ""
    runtime_version: str = ""
    runtime_description: str = ""
    api_version: str = ""
    env: Dict[str, str] = dataclasses.field(default_factory=dict)

    def _field_mapping(self) -> Dict[str, str]:
        return {
            resources.PROCESS_EXECUTABLE_NAME: "executable_name",
            resources.PROCESS_EXECUTABLE_PATH: "executable_path",
            resources.PROCESS_COMMAND: "command",
            resources.PROCESS_COMMAND_ARGS: "command_args",
            resources.PROCESS_RUNTIME_NAME: "runtime_name",
            resources.PROCESS_RUNTIME_VERSION: "runtime_version",
            resources.PROCESS_RUNTIME_DESCRIPTION: "runtime_description",
            detector.PROCESS_RUNTIME_API_VERSION: "api_version",
        }

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        self.pid = str(mapping.pop(resources.PROCESS_PID, ""))
        self.owner_is_root = mapping.pop(resources.PROCESS_OWNER, 1) == 0
        env_keys = [k for k in mapping if k.startswith("process.env.")]
        self.env = {k[len("process.env.") :]: mapping.pop(k) for k in env_keys}
        return TraceSpanDataclassMixin.from_dict(self, mapping)


@dataclasses.dataclass
class Resource(TraceSpanDataclassMixin):
    """Resource dataclass."""

    process: Process = dataclasses.field(default_factory=Process)
    system: System = dataclasses.field(default_factory=System)
    attributes: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        attrs = self.process.from_dict(mapping)
        attrs = self.system.from_dict(attrs)
        # Everything not already consumed.
        self.attributes = {**attrs}
        return {}


@dataclasses.dataclass
class InstrumentationScope(TraceSpanDataclassMixin):
    """InstrumentationScope dataclass."""

    name: str = ""
    version: str = ""


class SpanKind(enum.Enum):
    """Span type."""

    SPAN_KIND_UNSPECIFIED = 0
    SPAN_KIND_INTERNAL = 1
    SPAN_KIND_SERVER = 2
    SPAN_KIND_CLIENT = 3

    @classmethod
    def from_span_value(cls, value):
        """Create an enum from the value from the json span value."""
        # The otel implementation uses str(self.kind), where self.kind is
        # an otel SpanKind enum, resulting in `Enum.ValueName` strings.
        if value == "SpanKind.INTERNAL":
            return cls.SPAN_KIND_INTERNAL
        elif value == "SpanKind.SERVER":
            return cls.SPAN_KIND_SERVER
        elif value == "SpanKind.CLIENT":
            return cls.SPAN_KIND_CLIENT
        else:
            return cls.SPAN_KIND_UNSPECIFIED


@dataclasses.dataclass
class Event(TraceSpanDataclassMixin):
    """Event dataclass."""

    event_time_millis: int = 0
    name: str = ""
    attributes: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        # TODO(python3.11): Use fromisoformat instead of strptime and replace.
        start = datetime.datetime.strptime(
            mapping.pop("timestamp"), "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=datetime.timezone.utc)
        self.event_time_millis = int(start.timestamp() * 1000)
        return TraceSpanDataclassMixin.from_dict(self, mapping)


@dataclasses.dataclass
class StackFrame(TraceSpanDataclassMixin):
    """StackFrame dataclass."""

    function_name: str = ""
    file_name: str = ""
    line_number: int = 0
    column_number: int = 0


@dataclasses.dataclass
class StackTrace(TraceSpanDataclassMixin):
    """StackTrace dataclass."""

    stack_frames: List[StackFrame] = dataclasses.field(default_factory=list)
    dropped_frames_count: int = 0
    stacktrace_hash: str = ""

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        for frame in mapping.pop("stack_frames", []):
            stack_frame = StackFrame()
            stack_frame.from_dict(frame)
            self.stack_frames.append(stack_frame)

        return TraceSpanDataclassMixin.from_dict(self, mapping)


class StatusCode(enum.Enum):
    """Status code."""

    STATUS_CODE_UNSET = 0
    STATUS_CODE_OK = 1
    STATUS_CODE_ERROR = 2

    @classmethod
    def from_span_value(cls, value):
        """Create an enum from the value from the json span value."""
        # The otel implementation uses str(self.status_code.name), where
        # self.status_code is an otel StatusCode enum, resulting in simple
        # `ValueName` strings.
        if value == "ERROR":
            return cls.STATUS_CODE_ERROR
        else:
            return cls.STATUS_CODE_OK


@dataclasses.dataclass
class Status(TraceSpanDataclassMixin):
    """Status dataclass."""

    status_code: StatusCode = StatusCode.STATUS_CODE_UNSET
    message: str = ""
    stack_trace: StackTrace = dataclasses.field(default_factory=StackTrace)

    def _field_mapping(self) -> Dict[str, str]:
        return {
            "description": "message",
        }


@dataclasses.dataclass
class Context(TraceSpanDataclassMixin):
    """Context dataclass."""

    trace_id: str = ""
    span_id: str = ""
    trace_state: str = ""


@dataclasses.dataclass
class Link(TraceSpanDataclassMixin):
    """Link dataclass."""

    context: Context = dataclasses.field(default_factory=Context)
    attributes: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        attrs = self.context.from_dict(mapping)
        self.attributes = {**attrs}
        return {}


@dataclasses.dataclass
class TraceSpan(TraceSpanDataclassMixin):
    """Trace span dataclass."""

    name: str = ""
    context: Context = dataclasses.field(default_factory=Context)
    parent_span_id: str = ""
    span_kind: SpanKind = SpanKind.SPAN_KIND_UNSPECIFIED
    start_time_millis: int = 0
    end_time_millis: int = 0
    attributes: Dict[str, Any] = dataclasses.field(default_factory=dict)
    events: List[Event] = dataclasses.field(default_factory=list)
    links: List[Link] = dataclasses.field(default_factory=list)
    status: Status = dataclasses.field(default_factory=Status)
    resource: Resource = dataclasses.field(default_factory=Resource)
    # TODO: Verify whether InstrumentationScope is ever added to the json.
    instrumentation_scope: InstrumentationScope = dataclasses.field(
        default_factory=InstrumentationScope
    )
    telemetry_sdk: TelemetrySdk = dataclasses.field(
        default_factory=TelemetrySdk
    )

    def _field_mapping(self) -> Dict[str, str]:
        return {
            "kind": "span_kind",
        }

    def from_dict(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        # Force empty string when we get None.
        self.parent_span_id = mapping.pop("parent_id", "") or ""

        # TODO(python3.11): Use fromisoformat instead of strptime and replace.
        start = datetime.datetime.strptime(
            mapping.pop("start_time"), "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=datetime.timezone.utc)
        end = datetime.datetime.strptime(
            mapping.pop("end_time"), "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=datetime.timezone.utc)
        self.start_time_millis = int(start.timestamp() * 1000)
        self.end_time_millis = int(end.timestamp() * 1000)

        for event_data in mapping.pop("events", []):
            event = Event()
            event.from_dict(event_data)
            self.events.append(event)

        for link_data in mapping.pop("links", []):
            link = Link()
            link.from_dict(link_data)
            self.links.append(link)

        # TelemetrySdk populates from the resource attributes, so make sure we
        # allow it to consume those entries before populating the resource data.
        resource_attrs = mapping.pop("resource", {}).get("attributes", {})
        resource_attrs = self.telemetry_sdk.from_dict(resource_attrs)
        self.resource.from_dict(resource_attrs)

        TraceSpanDataclassMixin.from_dict(self, mapping)
        return {}

    @classmethod
    def parse(cls, span: str) -> "TraceSpan":
        """Create an instance from the json encoded string."""
        instance = cls()
        instance.from_json(span)
        return instance


class ClearcutPublisher:
    """Publish span to google http endpoint."""

    def __init__(
        self,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: int = _DEFAULT_TIMEOUT,
        max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE,
        next_request_ts: Optional[Union[int, float]] = None,
        prefilter: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._next_request_dt = (
            datetime.datetime.fromtimestamp(next_request_ts)
            if next_request_ts
            else datetime.datetime.now()
        )
        self._queue = []
        self._max_batch_size = max_batch_size
        self._prefilter = prefilter or utils.Anonymizer()

    @property
    def wait_time(self) -> int:
        """Get the wait time until the next publish."""
        wait_delta = self.next_request_dt - datetime.datetime.now()
        wait_time = wait_delta.total_seconds()

        return wait_time if wait_time > 0 else 0

    @property
    def next_request_dt(self) -> datetime.datetime:
        """Get the next request datetime."""
        return self._next_request_dt

    @property
    def next_publish_ts(self) -> float:
        """Get the timestamp the next publish can be made."""
        return self.next_request_dt.timestamp()

    @property
    def queue_len(self) -> int:
        """Get the number of items in the queue."""
        return len(self._queue)

    @tracer.start_as_current_span(
        "chromite.lib.telemetry_publisher.ClearcutPublisher.publish"
    )
    def publish(self, timeout: Optional[int] = None) -> None:
        """Publish a batch."""
        spans = self._queue[: self._max_batch_size]
        self._queue = self._queue[self._max_batch_size :]

        if not spans:
            # Skip publishing nothing.
            self._next_request_dt = datetime.datetime.now()
            return

        log_request = self._prepare_request_body(spans)
        log_response = self._do_publish_request(log_request, timeout)

        now = datetime.datetime.now()
        delta = datetime.timedelta(
            milliseconds=log_response.next_request_wait_millis
        )
        self._next_request_dt = now + delta

    def queue(self, spans: Iterable[str]) -> bool:
        """Add spans to the queue if not above max batch size."""
        try:
            parsed = [TraceSpan.parse(self._prefilter(x)) for x in spans]
        except Exception as e:  # pylint: disable=broad-except
            # We don't want a single malformed file to interrupt the publishing
            # process, so catch Exception and raise a ParseError instead.
            logging.warning("Error parsing a span:")
            logging.warning(spans)
            raise ParseSpanError(
                "Unable to parse a span, see logs for details."
            ) from e

        if self._can_queue(len(parsed)):
            self._queue.extend(parsed)
            return True

        return False

    def _can_queue(self, count: int) -> bool:
        """Check if |count| spans can be published in the batch."""
        return self._max_batch_size - self.queue_len >= count

    def _prepare_request_body(
        self, spans: Iterable[TraceSpan]
    ) -> clientanalytics_pb2.LogRequest:
        log_request = clientanalytics_pb2.LogRequest()
        log_request.request_time_ms = int(time.time() * 1000)
        log_request.client_info.client_type = _CLIENT_TYPE
        log_request.log_source = _LOG_SOURCE

        for span in spans:
            trace_span = trace_span_pb2.TraceSpan()
            span.to_proto(trace_span)
            log_event = log_request.log_event.add()
            log_event.event_time_ms = int(time.time() * 1000)
            log_event.source_extension = trace_span.SerializeToString()

        return log_request

    def _do_publish_request(
        self,
        log_request: clientanalytics_pb2.LogRequest,
        timeout: Optional[int] = None,
    ) -> clientanalytics_pb2.LogResponse:
        req = urllib.request.Request(
            self._endpoint,
            data=log_request.SerializeToString(),
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                req, timeout=timeout or self._timeout
            ) as f:
                response = f.read()
        except (urllib.error.URLError, socket.timeout) as e:
            logging.exception(e)
            raise PublishError(
                f"Encountered an error while publishing: {e}"
            ) from e

        logging.debug("Response:")
        logging.debug(response)

        log_response = clientanalytics_pb2.LogResponse()
        try:
            log_response.ParseFromString(response)
        except proto_msg.DecodeError as e:
            logging.warning("could not decode data into proto: %s", e)
            raise PublishError(f"Unable to decode proto: {e}") from e

        return log_response
