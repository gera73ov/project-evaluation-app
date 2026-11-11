"""RT-009: учёт задержки доставки только для событий с меткой времени и известным каналом."""

from __future__ import annotations

import datetime as dt
import uuid

from estimator import metrics
from estimator.realtime import metrics as ws_metrics


def _count(channel: str) -> float:
    return (
        metrics.REGISTRY.get_sample_value(
            "estimator_ws_delivery_seconds_count", {"channel": channel}
        )
        or 0.0
    )


def test_observe_sent() -> None:
    now = dt.datetime(2026, 11, 11, 10, 0, 0, tzinfo=dt.UTC)
    channel = f"project:{uuid.uuid4()}:money"
    before = _count("money")
    event = {"type": "event", "channel": channel, "ts": "2026-11-11T09:59:59.700Z"}
    ws_metrics.observe_sent(event, now)
    assert _count("money") == before + 1
    # не события, без ts, с неверным ts или каналом — не считаются
    for message in (
        {"type": "ack", "channel": channel, "ts": event["ts"]},
        {"type": "event", "channel": channel},
        {"type": "event", "channel": channel, "ts": "вчера"},
        {"type": "event", "channel": channel, "ts": "2026-11-11T09:59:59"},
        {"type": "event", "channel": "other", "ts": event["ts"]},
        "text",
    ):
        ws_metrics.observe_sent(message, now)
    assert _count("money") == before + 1
