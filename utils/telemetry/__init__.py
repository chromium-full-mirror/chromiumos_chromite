# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""The tracing library that provides the Tracer."""

import os
from typing import Optional

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
and stacktraces (when crashes are encountered). You may choose to opt out of this
collection at any time by running the following command

                cros telemetry --disable

In order to opt-in, please run `cros telemetry --enable`. The telemetry will be
automatically enabled after the notice has been displayed for 10 times.
"""


_DEFAULT_RESOURCE = otel_resources.Resource.create(
    {otel_resources.SERVICE_NAME: "chromite"}
)


def initialize(
    config_file: os.PathLike, debug: bool = False, enable: Optional[bool] = None
):
    """Initialize opentelemetry library.

    The function initialized the opentelemetry library for trace collection. It
    collects the resource information, initializes the TraceProvider and based
    on enrollment and host enables or disables publishing of traces.

    Examples:
        from chromite.lib import chromite_config

        opts = parse_args(argv)
        chromite_config.initialize()
        telemetry.initialize(chromite_config.TELEMETRY_CONFIG, opts.debug)

    Args:
        config_file: The path to the telemetry cfg to load for initializing
        the telemetry.
        debug: Indicates if the traces should be exported to console.
        enable: Indicates if the traces should be enabled.
    """

    detected_resource = otel_resources.get_aggregated_resources(
        [
            otel_resources.ProcessResourceDetector(),
            otel_resources.OTELResourceDetector(),
            detector.ProcessDetector(),
            detector.SystemDetector(),
        ]
    )

    resource = detected_resource.merge(_DEFAULT_RESOURCE)
    otel_trace_api.set_tracer_provider(
        otel_trace.TracerProvider(resource=resource)
    )

    if debug:
        otel_trace_api.get_tracer_provider().add_span_processor(
            otel_export.BatchSpanProcessor(otel_export.ConsoleSpanExporter())
        )

    if not utils.is_google_host():
        return

    cfg = config.Config(config_file)
    if enable is not None:
        cfg.trace_config.update(enabled=enable, reason="USER")
        cfg.flush()

    if not cfg.trace_config.has_enabled():
        if cfg.root_config.notice_countdown > -1:
            print(NOTICE)
            cfg.root_config.update(
                notice_countdown=cfg.root_config.notice_countdown - 1
            )
        else:
            cfg.trace_config.update(enabled=True, reason="AUTO")

        cfg.flush()

    if cfg.trace_config.enabled:
        otel_trace_api.get_tracer_provider().add_span_processor(
            otel_export.BatchSpanProcessor(exporter.ClearcutSpanExporter())
        )
