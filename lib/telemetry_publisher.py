# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parse and publish telemetry."""

import dataclasses
import datetime
import enum
import json
from typing import Any, Dict, List, Optional

from chromite.third_party.google.protobuf import json_format
from chromite.third_party.opentelemetry.sdk import resources

from chromite.utils.telemetry import detector


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
