# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Chromite's Span class and related functionality."""

import signal
import subprocess
import types
from typing import Any, Dict, Optional, Union

from chromite.third_party.opentelemetry import trace as otel_trace_api
from chromite.third_party.opentelemetry.sdk import trace as otel_trace_sdk
from chromite.third_party.opentelemetry.util import types as otel_types


class ChromiteSpan(otel_trace_api.Span):
    """Chromite specific otel span implementation."""

    def __init__(self, inner: otel_trace_sdk.Span) -> None:
        self._inner = inner

    def end(self, end_time: Optional[int] = None) -> None:
        self._inner.end(end_time=end_time)

    def get_span_context(self) -> otel_trace_api.SpanContext:
        return self._inner.get_span_context()

    def set_attributes(
        self, attributes: Dict[str, otel_types.AttributeValue]
    ) -> None:
        self._inner.set_attributes(attributes)

    def set_attribute(self, key: str, value: otel_types.AttributeValue) -> None:
        self._inner.set_attribute(key, value)

    def add_event(
        self,
        name: str,
        attributes: otel_types.Attributes = None,
        timestamp: Optional[int] = None,
    ) -> None:
        self._inner.add_event(name, attributes=attributes, timestamp=timestamp)

    def update_name(self, name: str) -> None:
        self._inner.update_name(name)

    def is_recording(self) -> bool:
        return self._inner.is_recording()

    def set_status(
        self,
        status: Union[otel_trace_api.Status, otel_trace_api.StatusCode],
        description: Optional[str] = None,
    ) -> None:
        self._inner.set_status(status, description)

    def record_exception(
        self,
        exception: Exception,
        attributes: otel_types.Attributes = None,
        timestamp: Optional[int] = None,
        escaped: bool = False,
    ) -> None:
        # Record STATUS_COKE_OK for sys.exit(0).
        if isinstance(exception, SystemExit) and exception.code == 0:
            self.set_status(status=otel_trace_api.StatusCode.OK)

        # Create a mutable dict from the passed attributes or create a new dict
        # if empty or null. This ensures that the passed dict is not mutated.
        attributes = dict(attributes or {})
        attributes.update(self._record_failed_packages_error(exception))
        attributes.update(self._record_called_process_error(exception))

        self._inner.record_exception(
            exception,
            attributes=attributes,
            timestamp=timestamp,
            escaped=escaped,
        )

    def _record_failed_packages_error(self, exception: Exception) -> Dict:
        """Generate attributes for a PackageInstallError or similar."""
        attributes = {}

        failed_packages = getattr(exception, "failed_packages", None)
        if isinstance(failed_packages, (list, tuple)):
            attributes["failed_packages"] = [str(f) for f in failed_packages]

        return attributes

    def _record_called_process_error(self, exception: Exception) -> Dict:
        """Generate attributes for a CalledProcessError."""
        attributes = {}
        if not isinstance(exception, subprocess.CalledProcessError):
            # Not a CalledProcessError.
            return attributes

        if exception.returncode and exception.returncode < 0:
            # Died with a signal (probably), record signal info.
            attributes["signal_number"] = -exception.returncode
            try:
                signal_name = signal.Signals(-exception.returncode).name
            except ValueError:
                signal_name = "Unknown"
            attributes["signal_name"] = signal_name

        return attributes

    def __enter__(self) -> "ChromiteSpan":
        return self

    def __exit__(
        self,
        exc_type: Optional[BaseException],
        exc_val: Optional[BaseException],
        exc_tb: Optional[types.TracebackType],
    ) -> None:
        if exc_val and self.is_recording():
            if self._inner._record_exception:
                self.record_exception(exception=exc_val, escaped=True)

            if self._inner._set_status_on_exception:
                self.set_status(
                    otel_trace_api.Status(
                        status_code=otel_trace_api.StatusCode.ERROR,
                        description=f"{exc_type.__name__}: {exc_val}",
                    )
                )

        super().__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name: str) -> Any:
        """Method allows to delegate method calls."""
        return getattr(self._inner, name)
