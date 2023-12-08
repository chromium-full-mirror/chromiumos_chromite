# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the lib/metrics_lib module."""

import os
from unittest import mock

from chromite.lib import constants
from chromite.lib import cros_test_lib
from chromite.lib import metrics_lib


class MetricsTest(cros_test_lib.MockTestCase):
    """Tests for metrics_lib."""

    def testEndToEnd(self) -> None:
        """Test the normal usage pattern, end-to-end."""
        # We should start in a clean, unmeasured state.
        env = os.environ.copy()
        env.pop(constants.CROS_METRICS_DIR_ENVVAR, None)
        self.PatchObject(os, "environ", new=env)

        with mock.patch(
            "chromite.lib.metrics_lib.current_milli_time"
        ) as mock_time:
            mock_time.side_effect = [128000, 256000, 512300]

            events = []

            # Create a fake usage site of the metrics.
            @metrics_lib.collect_metrics
            def measure_things() -> None:
                # Now, in here, we should have set up this env-var. This is a
                # bit of invasive white-box testing.
                self.assertTrue(
                    os.environ.get(constants.CROS_METRICS_DIR_ENVVAR)
                )

                # Now, with our pretend timer, let's record some events.
                with metrics_lib.timer("test.timer"):
                    metrics_lib.event("test.named_event")

                for event in metrics_lib.read_metrics_events():
                    events.append(event)

            # Run the fake scenario.
            measure_things()

            self.assertEqual(len(events), 3)
            self.assertEqual(events[0].timestamp_epoch_millis, 128000)
            self.assertEqual(events[0].op, metrics_lib.OP_START_TIMER)
            self.assertEqual(events[0].name, "test.timer")

            self.assertEqual(events[1].timestamp_epoch_millis, 256000)
            self.assertEqual(events[1].op, metrics_lib.OP_NAMED_EVENT)
            self.assertEqual(events[1].name, "test.named_event")

            self.assertEqual(events[2].timestamp_epoch_millis, 512300)
            self.assertEqual(events[2].op, metrics_lib.OP_STOP_TIMER)
            self.assertEqual(events[2].name, "test.timer")


def test_deserialize_timer(monkeypatch) -> None:
    """Test timer math and deserialization into proto objects."""
    mock_events = [
        metrics_lib.MetricEvent(
            600, "a.b", metrics_lib.OP_START_TIMER, arg="100"
        ),
        metrics_lib.MetricEvent(
            1000, "a.b", metrics_lib.OP_STOP_TIMER, arg="100"
        ),
    ]
    monkeypatch.setattr(metrics_lib, "read_metrics_events", lambda: mock_events)
    result = metrics_lib.deserialize_metrics_log()
    assert len(result) == 1
    assert result[0].name == "a.b"
    assert result[0].timestamp_epoch_millis == 1000
    assert result[0].value == 400


def test_deserialize_named_event(monkeypatch) -> None:
    """Test deserialization of a named event."""
    mock_events = [
        metrics_lib.MetricEvent(
            1000, "a.named_event", metrics_lib.OP_NAMED_EVENT, arg=None
        ),
    ]
    monkeypatch.setattr(metrics_lib, "read_metrics_events", lambda: mock_events)

    result = metrics_lib.deserialize_metrics_log(prefix="prefix")
    assert len(result) == 1
    assert result[0].name == "prefix.a.named_event"
    assert result[0].timestamp_epoch_millis == 1000


def test_deserialize_gauge(monkeypatch) -> None:
    """Test deserialization of a gauge."""
    mock_events = [
        metrics_lib.MetricEvent(1000, "a.gauge", metrics_lib.OP_GAUGE, arg=17),
    ]
    monkeypatch.setattr(metrics_lib, "read_metrics_events", lambda: mock_events)

    result = metrics_lib.deserialize_metrics_log()
    assert len(result) == 1
    assert result[0].name == "a.gauge"
    assert result[0].timestamp_epoch_millis == 1000
    assert result[0].value == 17


def test_deserialize_counter(monkeypatch) -> None:
    """Test deserialization of a counter."""
    mock_events = [
        metrics_lib.MetricEvent(
            1000, "a.counter", metrics_lib.OP_INCREMENT_COUNTER, arg=1
        ),
        metrics_lib.MetricEvent(
            1001, "a.counter", metrics_lib.OP_INCREMENT_COUNTER, arg=2
        ),
        metrics_lib.MetricEvent(
            1002, "a.counter", metrics_lib.OP_INCREMENT_COUNTER, arg=3
        ),
        metrics_lib.MetricEvent(
            1003, "a.counter", metrics_lib.OP_DECREMENT_COUNTER, arg=4
        ),
    ]
    monkeypatch.setattr(metrics_lib, "read_metrics_events", lambda: mock_events)

    result = metrics_lib.deserialize_metrics_log()
    assert len(result) == 1
    assert result[0].name == "a.counter"
    assert result[0].timestamp_epoch_millis == 1003
    assert result[0].value == 2
