# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The tracing library that provides the Tracer."""

import os

from chromite.third_party.opentelemetry import trace as otel_trace_api
from chromite.third_party.opentelemetry.sdk import resources as otel_resources
from chromite.third_party.opentelemetry.sdk import trace as otel_trace
from chromite.third_party.opentelemetry.sdk.trace import export as otel_export

from chromite.utils.telemetry import config
from chromite.utils.telemetry import detector
from chromite.utils.telemetry import exporter
from chromite.utils.telemetry import utils


NOTICE = """
To help improve the quality of this product, we collect de-identified usage data
and stacktraces when crashes are encountered. You may choose to opt out of this
collection at any time by setting the flag `enabled = False` under [trace] section
in

                ~/.config/chromite/telemetry.cfg

The tracing will be auto enabled after the notice has been displayed for 10 times.
"""


def initialize(config_file: os.PathLike):
    """Initialize opentelemetry library."""

    # TODO(b/266131531): remove when ready for launch.
    # To test locally, revert the associated commit or manually remove this
    # line.
    return
    # pylint: disable=unreachable

    if not utils.is_google_host():
        return

    cfg = config.Config(config_file)

    if not cfg.trace_config.hasEnabled():
        if cfg.root_config.notice_countdown > 0:
            print(NOTICE)
            cfg.root_config.update(
                notice_countdown=cfg.root_config.notice_countdown - 1
            )
            cfg.flush()
            return
        else:
            cfg.trace_config.update(enabled=True, reason="AUTO")
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


def export_to_console(config_file: os.PathLike):
    """Add a span exporter to print spans to console."""

    # TODO(b/266131531): remove when ready for launch.
    # To test locally, revert the associated commit or manually remove this
    # line.
    return
    # pylint: disable=unreachable

    cfg = config.Config(config_file)

    if cfg.trace_config.enabled:
        otel_trace_api.get_tracer_provider().add_span_processor(
            otel_export.BatchSpanProcessor(otel_export.ConsoleSpanExporter())
        )
