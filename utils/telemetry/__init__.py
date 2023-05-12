# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The tracing library that provides the Tracer."""

from opentelemetry import trace as otel_trace_api
from opentelemetry.sdk import resources as otel_resources
from opentelemetry.sdk import trace as otel_trace
from opentelemetry.sdk.trace import export as otel_export

from chromite.lib import chromite_config
from chromite.lib import cros_build_lib
from chromite.utils.telemetry import config
from chromite.utils.telemetry import detector
from chromite.utils.telemetry import exporter


NOTICE = """
To help improve the quality of this product, we collect de-identified usage data
and stacktraces when crashes are encountered. You may choose to opt out of this
collection at any time by setting the flag `trace.enabled = False` in

                ~/.config/chromite/telemetry.cfg"""


def initialize():
    """Initialize opentelemetry library."""

    chromite_config.initialize()
    cfg = config.Config(chromite_config.TELEMETRY_CONFIG)

    if cfg.trace_config.enabled and cfg.root_config.notice_count > 0:
        print(NOTICE)
        cfg.root_config.update(notice_count=cfg.root_config.notice_count - 1)
        cfg.flush()

    if cfg.trace_config.enabled:
        resource = otel_resources.get_aggregated_resources(
            [
                otel_resources.ProcessResourceDetector(),
                otel_resources.OTELResourceDetector(),
                detector.ProcessDetector(),
                detector.SystemDetector(),
            ]
        )
        otel_trace_api.set_tracer_provider(
            otel_trace.TracerProvider(resource=resource)
        )
        otel_trace_api.get_tracer_provider().add_span_processor(
            otel_export.BatchSpanProcessor(exporter.ClearcutSpanExporter())
        )


def export_to_console():
    """Add a span exporter to print spans to console."""

    cfg = config.Config(chromite_config.TELEMETRY_CONFIG)

    if cfg.trace_config.enabled:
        otel_trace_api.get_tracer_provider().add_span_processor(
            otel_export.BatchSpanProcessor(otel_export.ConsoleSpanExporter())
        )
