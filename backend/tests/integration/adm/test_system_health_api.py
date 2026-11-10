"""ADM-003: «Состояние системы» — каждый индикатор зелёный и красный при имитации сбоя (FR-SA-07,
SEC-AUD-03, SEC-AUD-04, SEC-AUD-05, SEC-AUTH-07)."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin import health
from estimator.config import get_settings
from estimator.db.enums import SystemRole
from estimator.security import audit
from estimator.security.alerts import notify
from estimator.security.audit.verify import LAST_RESULT_KEY
from estimator.security.siem import shipper
from tests.integration.auth.conftest import set_setting
from tests.integration.core.conftest import World

pytestmark = [pytest.mark.integration, pytest.mark.spec("FR-SA-07")]

SMTP = {"host": "smtp.corp", "port": 25, "security": "none", "username": None,
        "from_address": "robot@corp.ru", "from_name": "Оценка", "timeout_seconds": 5}  # fmt: skip


@pytest.fixture
def reachable(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """Хосты, которые «отвечают» на TCP; остальные недоступны."""
    hosts: set[str] = set()

    async def fake(host: str, port: int) -> bool:
        return host in hosts

    monkeypatch.setattr(health, "tcp_reachable", fake)
    monkeypatch.setattr(health, "queue_lengths", lambda settings: {"default": 2, "mail": 1})
    return hosts


@pytest.fixture
def marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "last-success"
    monkeypatch.setenv("BACKUP_MARKER_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _remove(path: Path) -> None:
    path.unlink()


async def _health(world: World) -> dict[str, dict[str, Any]]:
    root = await world.actor(SystemRole.SUPERADMIN)
    response = await root.get("/system/health")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["app_version"]
    assert body["schema_version"]
    return {c["name"]: c for c in body["components"]}


async def test_all_green(
    world: World, db_session: AsyncSession, redis_client: Redis,
    reachable: set[str], marker: Path,
) -> None:  # fmt: skip
    await set_setting(db_session, "smtp.server", SMTP)
    reachable.add("smtp.corp")
    _write(marker, dt.datetime.now(dt.UTC).isoformat() + "\n")
    await redis_client.set(LAST_RESULT_KEY, json.dumps(
        {"ok": True, "checked": 10, "first_broken_id": None, "finished_at": "2026-11-10T04:00:00Z"}
    ))  # fmt: skip
    await redis_client.delete(notify.UNDELIVERED_KEY, shipper.STATE_KEY)
    found = await _health(world)
    assert list(found) == ["db", "redis", "smtp", "ldap", "siem", "queue", "backup",
                           "audit_chain", "audit_purge"]  # fmt: skip
    assert {n: c["ok"] for n, c in found.items() if not c["ok"]} == {}
    assert found["queue"]["detail"] == "Задач в очереди: 3"
    assert found["ldap"]["detail"].startswith("Режим «Приложение»")
    assert found["audit_chain"]["checked_at"] == "2026-11-10T04:00:00Z"


@pytest.mark.spec("SEC-AUD-03")
@pytest.mark.spec("SEC-AUD-04")
@pytest.mark.spec("SEC-AUD-05")
@pytest.mark.spec("SEC-AUTH-07")
async def test_each_failure_turns_red(
    world: World, db_session: AsyncSession, redis_client: Redis,
    reachable: set[str], marker: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:  # fmt: skip
    # SMTP настроен, но сервер не отвечает
    await set_setting(db_session, "smtp.server", SMTP)
    # AD: контроллеры не отвечают
    await set_setting(db_session, "auth.mode", "ad")
    await set_setting(
        db_session, "auth.ad.connection", {"controllers": [{"host": "dc1", "port": 636}]}
    )
    # SIEM: очередь переполнялась
    await redis_client.set(shipper.STATE_KEY, json.dumps({
        "enabled": True, "ok": True, "error": None, "backlog": 0,
        "checked_at": "2026-11-10T08:00:00Z",
        "last_sent_at": None, "overflow_at": "2026-11-09T08:00:00Z", "dropped": 5,
    }))  # fmt: skip

    # очередь Celery: брокер недоступен
    def broken(settings: Any) -> dict[str, int]:
        raise ConnectionError("broker")

    monkeypatch.setattr(health, "queue_lengths", broken)
    # бэкап старше 26 часов
    _write(marker, (dt.datetime.now(dt.UTC) - dt.timedelta(hours=27)).isoformat())
    # цепочка аудита нарушена
    await redis_client.set(LAST_RESULT_KEY, json.dumps(
        {"ok": False, "checked": 10, "first_broken_id": "42", "finished_at": "2026-11-10T04:00:00Z"}
    ))  # fmt: skip
    # удаление аудита просрочено: срок «уже прошёл» для любой записи
    await set_setting(db_session, "retention.periods", {
        "audit_months": 6, "app_logs_days": 90, "trash_days": 30, "export_files_hours": 24,
        "notifications_days": 365, "change_log_days": 7,
    })  # fmt: skip
    monkeypatch.setattr(health, "PURGE_GRACE_MONTHS", -7)
    await audit.write(db_session, "system.setup.finished", actor="system")

    found = await _health(world)
    red = {n for n, c in found.items() if not c["ok"]}
    assert red == {"smtp", "ldap", "siem", "queue", "backup", "audit_chain", "audit_purge"}
    assert "недоступен" in found["smtp"]["detail"]
    assert found["siem"]["detail"].startswith("Очередь SIEM переполнялась")
    assert found["queue"]["detail"] == "Недоступно"
    assert "старше 26 часов" in found["backup"]["detail"]
    assert "42" in found["audit_chain"]["detail"]
    assert "просрочено" in found["audit_purge"]["detail"]

    # SMTP отвечает, но оповещение ИБ не доставлено; контроллер AD ожил
    reachable.update({"smtp.corp", "dc1"})
    await redis_client.set(notify.UNDELIVERED_KEY, json.dumps(
        {"alert_type": "smtp_changed", "channel": "old_smtp", "at": "2026-11-10T07:00:00+00:00"}
    ))  # fmt: skip
    _remove(marker)
    await redis_client.delete(LAST_RESULT_KEY)
    found = await _health(world)
    assert found["smtp"]["detail"].startswith("Оповещение ИБ не доставлено")
    assert found["ldap"]["ok"] is True
    assert (found["backup"]["ok"], found["backup"]["detail"]) == (
        False,
        "Нет данных о резервной копии",
    )
    assert found["audit_chain"]["ok"] is False
    await redis_client.delete(notify.UNDELIVERED_KEY, shipper.STATE_KEY)


async def test_unconfigured_smtp_and_permissions(world: World, reachable: set[str]) -> None:
    found = await _health(world)
    assert (found["smtp"]["ok"], found["smtp"]["detail"]) == (
        False, "SMTP не настроен: ссылки выдаются на экран",
    )  # fmt: skip
    admin = await world.actor(SystemRole.ADMIN)
    assert (await admin.get("/system/health")).status_code == 403
