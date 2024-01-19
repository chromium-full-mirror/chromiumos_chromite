# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parse and publish telemetry."""

import dataclasses
import datetime
import enum
import json
import logging
import time
from typing import Any, Callable, Dict, Iterable, List, Optional
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
from chromite.utils.telemetry import detector
from chromite.utils.telemetry import utils


_DEFAULT_ENDPOINT = "https://play.googleapis.com/log"
_DEFAULT_TIMEOUT = 15
_DEAULT_MAX_WAIT_SECS = 60
_DEFAULT_MAX_BATCH_SIZE = 1000
# Preallocated in Clearcut proto to Build.
_LOG_SOURCE = 2044
# Preallocated in Clearcut proto to Python clients.
_CLIENT_TYPE = 33


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
        max_wait_secs: int = _DEAULT_MAX_WAIT_SECS,
        max_batch_size: int = _DEFAULT_MAX_BATCH_SIZE,
        prefilter: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._endpoint = endpoint
        self._timeout = timeout
        self._next_request_dt = datetime.datetime.now()
        self._max_wait_secs = max_wait_secs
        self._queue = []
        self._max_batch_size = max_batch_size
        self._prefilter = prefilter or utils.Anonymizer()

    @property
    def wait_time(self) -> int:
        """Get the wait time until the next publish."""
        wait_delta = self._next_request_dt - datetime.datetime.now()
        wait_time = wait_delta.total_seconds()

        return wait_time if wait_time > 0 else 0

    def publish(self, spans: Optional[Iterable[str]] = None) -> bool:
        """Queue |spans| and publish the full queue."""
        self.queue(spans or [])
        while self._queue:
            if not self._publish_batch():
                return False

        return True

    def queue(self, spans: Iterable[str]) -> None:
        """Add spans to the queue."""
        self._queue.extend([TraceSpan.parse(self._prefilter(x)) for x in spans])

    def _publish_batch(self, timeout: Optional[int] = None) -> bool:
        """Publish one batch of spans to clearcut via http api."""
        spans = self._queue[: self._max_batch_size]
        self._queue = self._queue[self._max_batch_size :]

        while True:
            if self.wait_time > self._max_wait_secs:
                logging.warning("Wait is too long. This should be weird.")
                return False
            elif self.wait_time > 0:
                time.sleep(self.wait_time)
                continue

            log_request = self._prepare_request_body(spans)
            log_response = self._do_publish_request(log_request, timeout)
            if not log_response:
                return False

            now = datetime.datetime.now()
            delta = datetime.timedelta(
                milliseconds=log_response.next_request_wait_millis
            )
            self._next_request_dt = now + delta
            return True

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
    ) -> Optional[clientanalytics_pb2.LogResponse]:
        req = urllib.request.Request(
            self._endpoint,
            data=log_request.SerializeToString(),
            method="POST",
        )
        log_response = clientanalytics_pb2.LogResponse()

        try:
            with urllib.request.urlopen(
                req, timeout=timeout or self._timeout
            ) as f:
                log_response.ParseFromString(f.read())
        except urllib.error.URLError as e:
            # It is expected that child Pids in build_image which call
            # sys.exit do not have network re-enabled in that namespace, so
            # for now, log this error at the debug level.
            logging.debug(e)
            return None
        except proto_msg.DecodeError as e:
            logging.warning("could not decode data into proto: %s", e)
            return None

        return log_response
