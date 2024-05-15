# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The trace package for chromite telemetry."""

import contextlib
import datetime
import functools
import os
import sys
from typing import Any, Dict, Iterator, Mapping, Optional, TYPE_CHECKING, Union
import uuid


if TYPE_CHECKING:
    from chromite.third_party.opentelemetry import trace
    from chromite.third_party.opentelemetry.trace import span


_TRACING_INITIALIZED = False
TRACEPARENT_ENVVAR = "traceparent"


@functools.lru_cache
def _get_trace_dir():
    from chromite.lib import osutils
    from chromite.lib import path_util

    path = path_util.get_log_dir() / "telemetry"

    now = datetime.datetime.now()
    date = now.strftime("%Y-%m-%d")
    time = now.strftime("%H_%M_%S")
    pid = os.getpid()
    script = os.path.basename(sys.argv[0])
    # Identify (most) cros commands to facilitate manual browsing.
    if (
        script == "cros"
        and len(sys.argv) > 1
        and not sys.argv[1].startswith("-")
    ):
        script = f"{script}-{os.path.basename(sys.argv[1])}"

    path /= date
    path /= f"{time}--{script}--{pid}"

    osutils.SafeMakedirsNonRoot(path)

    return path


@functools.lru_cache
def _get_trace_path():
    from chromite.lib import osutils
    from chromite.utils import os_util

    path = _get_trace_dir() / f"{uuid.uuid4()}.otel.traces.json"

    path.touch()
    if os_util.is_root_user() and os_util.get_non_root_user():
        osutils.Chown(path, os_util.get_non_root_user())

    return path


def initialize(
    enabled: bool = False,
    development_mode: bool = False,
    user_uuid: str = "",
) -> None:
    """Initialize opentelemetry tracing.

    For most use cases, `telemetry.initialize` should be used since that also
    takes case of any consent and other auxiliary logic related to telemetry.

    Args:
        enabled: Indicates is the traces should be enabled.
        development_mode: Mark the telemetry as in development, so it can be
            easily identified as such later, e.g. filtered out of queries.
        user_uuid: The user's UUID.
    """

    # The opentelemetry imports are moved inside this function to reduce the
    # package load time. This is especially helpful in scenarios where spans
    # are added to some common library and telemetry is not initialized in all
    # the cases. Nesting these imports would shave off almost 400ms from the
    # import overhead in such cases.
    from chromite.third_party.opentelemetry import context as context_api
    from chromite.third_party.opentelemetry import trace as otel_trace_api
    from chromite.third_party.opentelemetry.sdk import (
        resources as otel_resources,
    )
    from chromite.third_party.opentelemetry.sdk import trace as otel_trace_sdk
    from chromite.third_party.opentelemetry.sdk.trace import (
        export as otel_export,
    )
    from chromite.third_party.opentelemetry.trace.propagation import (
        tracecontext,
    )

    from chromite.lib import telemetry
    from chromite.lib.telemetry import cros_detector
    from chromite.lib.telemetry import exporter
    from chromite.lib.telemetry.trace import chromite_tracer
    from chromite.utils import hostname_util
    from chromite.utils.telemetry import detector

    # Need this to globally mark telemetry initialized to enable real imports.
    # pylint: disable=global-statement
    global _TRACING_INITIALIZED

    if not hostname_util.is_google_host():
        return

    default_resource = otel_resources.Resource.create(
        {
            otel_resources.SERVICE_NAME: telemetry.SERVICE_NAME,
            "telemetry.version": telemetry.TELEMETRY_VERSION,
        }
    )

    detected_resource = otel_resources.get_aggregated_resources(
        # pylint: disable=line-too-long
        [
            otel_resources.ProcessResourceDetector(),  # type: ignore[no-untyped-call]
            otel_resources.OTELResourceDetector(),  # type: ignore[no-untyped-call]
            detector.ProcessDetector(),
            cros_detector.SDKSourceDetector(),  # type: ignore[no-untyped-call]
            detector.SystemDetector(),  # type: ignore[no-untyped-call]
            cros_detector.DevelopmentDetector(force_dev=development_mode),
            cros_detector.UserDetector(user_uuid=user_uuid),
        ]
    )

    resource = detected_resource.merge(default_resource)
    tracer_provider = chromite_tracer.ChromiteTracerProvider(
        otel_trace_sdk.TracerProvider(resource=resource)
    )
    otel_trace_api.set_tracer_provider(tracer_provider)

    if enabled:
        path = _get_trace_path()
        tracer_provider.add_span_processor(
            otel_export.SimpleSpanProcessor(exporter.ChromiteFileExporter(path))
        )

    if TRACEPARENT_ENVVAR in os.environ:
        ctx = tracecontext.TraceContextTextMapPropagator().extract(os.environ)
        context_api.attach(ctx)

    _TRACING_INITIALIZED = True


def get_tracer(name: str, version: Optional[str] = None) -> "ProxyTracer":
    """Returns a `ProxyTracer` for the module name and version."""
    return ProxyTracer(name, version)


def extract_tracecontext() -> Mapping[str, str]:
    """Extract the current tracecontext into a dict."""
    carrier: Dict[str, str] = {}

    if _TRACING_INITIALIZED:
        from chromite.third_party.opentelemetry.trace.propagation import (
            tracecontext,
        )

        tracecontext.TraceContextTextMapPropagator().inject(carrier)
    return carrier


def get_current_span() -> Union["span.Span", "NoOpSpan"]:
    """Get the currently active span."""
    if _TRACING_INITIALIZED:
        from chromite.third_party.opentelemetry import trace

        return trace.get_current_span()

    return NoOpSpan()


class ProxyTracer:
    """Duck typed equivalent for opentelemetry.trace.Tracer"""

    def __init__(self, name: str, version: Optional[str] = None) -> None:
        self._name = name
        self._version = version
        self._inner: Optional[Union["trace.Tracer", "NoOpTracer"]] = None
        self._noop_tracer = NoOpTracer()

    @property
    def _tracer(self) -> Union["trace.Tracer", "NoOpTracer"]:
        if self._inner:
            return self._inner

        if _TRACING_INITIALIZED:
            # Importing here to minimize the overhead for cases
            # where telemetry is not initialized.
            from chromite.third_party.opentelemetry import trace

            self._inner = trace.get_tracer(self._name, self._version)
            return self._inner

        return self._noop_tracer

    @contextlib.contextmanager
    def start_as_current_span(
        self, *args: Any, **kwargs: Any
    ) -> Union[Iterator["span.Span"], Iterator["NoOpSpan"]]:
        with self._tracer.start_as_current_span(*args, **kwargs) as s:
            yield s

    def start_span(
        self, *args: Any, **kwargs: Any
    ) -> Union["span.Span", "NoOpSpan"]:
        return self._tracer.start_span(*args, **kwargs)


class NoOpTracer:
    """Duck typed no-op impl for opentelemetry Tracer."""

    # pylint: disable=unused-argument
    def start_span(self, *args: Any, **kwargs: Any) -> "NoOpSpan":
        return NoOpSpan()

    @contextlib.contextmanager
    # pylint: disable=unused-argument
    def start_as_current_span(
        self, *args: Any, **kwargs: Any
    ) -> Iterator["NoOpSpan"]:
        yield NoOpSpan()


class NoOpSpan:
    """Duck typed no-op impl for opentelemetry Span."""

    # pylint: disable=unused-argument
    def end(self, end_time: Optional[int] = None) -> None:
        pass

    def get_span_context(self) -> None:
        return None

    # pylint: disable=unused-argument
    def set_attributes(self, *args: Any, **kwargs: Any) -> None:
        pass

    # pylint: disable=unused-argument
    def set_attribute(self, *args: Any, **kwargs: Any) -> None:
        pass

    # pylint: disable=unused-argument
    def add_event(self, *args: Any, **kwargs: Any) -> None:
        pass

    # pylint: disable=unused-argument
    def update_name(self, name: str) -> None:
        pass

    # pylint: disable=unused-argument
    def is_recording(self) -> bool:
        return False

    # pylint: disable=unused-argument
    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    # pylint: disable=unused-argument
    def record_exception(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> "NoOpSpan":
        return self

    # pylint: disable=unused-argument
    def __exit__(self, *args: Any, **kwargs: Any) -> None:
        self.end()
