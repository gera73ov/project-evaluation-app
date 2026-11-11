"""RT-009 · метрики WebSocket (SPEC 18.4): активные соединения и задержка доставки событий.

* ``estimator_ws_connections`` — открытые соединения экземпляра API; по стенду —
  ``sum(estimator_ws_connections)``;
* ``estimator_ws_delivery_seconds`` — гистограмма «событие собрано → кадр отправлен клиенту»
  по виду канала (``project``, ``money``, ``notes``, ``user``). Начало отсчёта — поле ``ts``
  события: оно ставится в транзакции изменения, перед commit, поэтому задержка включает
  commit, шину Redis и очередь соединения. p95 —
  ``histogram_quantile(0.95, sum by (le) (rate(estimator_ws_delivery_seconds_bucket[5m])))``,
  цель NFR-PERF-04 — не больше 1 с.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from estimator.metrics import gauge, histogram
from estimator.realtime.bus.contract import EventContractError, channel_kind

DELIVERY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 2.0, 5.0, 10.0)

CONNECTIONS = gauge(
    "estimator_ws_connections", "Открытые соединения WebSocket экземпляра API (SPEC 18.4)"
)
DELIVERY = histogram(
    "estimator_ws_delivery_seconds",
    "Задержка «событие → отправка клиенту» по WebSocket, секунды (SPEC 18.4, NFR-PERF-04)",
    ("channel",),
    buckets=DELIVERY_BUCKETS,
)


def _parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def observe_sent(message: Any, now: dt.datetime | None = None) -> None:
    """Учесть отправленный кадр: только события (``type: event``) с ``ts`` и каналом."""
    if not isinstance(message, dict) or message.get("type") != "event":
        return
    moment = _parse_ts(message.get("ts"))
    channel = message.get("channel")
    if moment is None or not isinstance(channel, str):
        return
    try:
        kind = channel_kind(channel)
    except EventContractError:
        return
    delay = ((now or dt.datetime.now(dt.UTC)) - moment).total_seconds()
    DELIVERY.labels(channel=kind).observe(max(delay, 0.0))
