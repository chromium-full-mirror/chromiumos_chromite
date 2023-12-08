# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Metrics for general consumption.

See infra/proto/metrics.proto for a description of the type of record that this
module will be creating.
"""

from typing import Iterable, Optional

from chromite.lib import metrics_lib


def deserialize_metrics_log(
    output_events, prefix: Optional[str] = None
) -> None:
    """Read the current metrics events, adding to output_events.

    This layer facilitates converting between the internal
    chromite.utils.metrics representation of metric events and the
    infra/proto/src/chromiumos/metrics.proto output type.

    Args:
        output_events: A chromiumos.MetricEvent protobuf message.
        prefix: A string to prepend to all metric event names.
    """
    populate_metrics(output_events, metrics_lib.deserialize_metrics_log(prefix))


def populate_metrics(
    output_events, metrics: Iterable[metrics_lib.METRIC_TYPE]
) -> None:
    """Populate a metrics message with the given metrics."""
    for entry in metrics:
        event = output_events.add()
        event.name = entry.name
        event.timestamp_milliseconds = entry.timestamp_epoch_millis
        if isinstance(entry, metrics_lib.TimerMetric):
            event.duration_milliseconds = entry.value
        elif isinstance(entry, metrics_lib.Metric):
            event.gauge = entry.value
