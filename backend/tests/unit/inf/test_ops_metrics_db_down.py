"""INF-013: при недоступной БД индикатор db красный, и оповещение «компонент красный» срабатывает.

Найдено имитацией сбоев на стенде (deploy/monitoring/simulate-alerts.sh): шаг «components»
целиком падал на открытии транзакции, и датчик db оставался 1.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from estimator import metrics, ops_metrics
from estimator.config import Settings

pytestmark = pytest.mark.spec("18.4")


class _DeadDb:
    def begin_nested(self) -> Any:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("db down"))


class _Redis:
    async def get(self, key: str) -> None:
        return None

    async def hgetall(self, key: str) -> dict[str, str]:
        return {}


async def test_db_down_turns_db_indicator_red() -> None:
    ops_metrics.COMPONENT_UP.labels("db").set(1)
    settings = Settings(clamav_host="127.0.0.1", clamav_port=1)
    await ops_metrics.refresh_once(_DeadDb(), _Redis(), settings)  # type: ignore[arg-type]
    value = metrics.REGISTRY.get_sample_value("estimator_component_up", {"component": "db"})
    assert value == 0
