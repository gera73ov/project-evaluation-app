"""Запуски проверки цепочки и запись запусков консольных команд в аудит (SEC-004).

* :func:`verify_and_record` — ``estimator audit verify`` и ежедневная задача 04:00: проверка,
  событие ``system.audit_chain.verified`` (при сбое — оповещение ИБ, SEC-AUTH-07) и результат
  в Redis для индикатора «Состояния системы» (18.4).
* :class:`AuditCliHook` — хук CLI INF-007: каждый запуск команды из перечня контракта —
  событие ``system.cli.executed`` с пользователем ОС (SEC-AUD-01, FR-SA-01).
"""

from __future__ import annotations

import asyncio
import socket
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from estimator.config import Settings, get_settings
from estimator.logging import get_logger
from estimator.security import audit
from estimator.security.audit.verify import (
    LAST_RESULT_KEY,
    VerifyResult,
    result_json,
    verify_chain,
)

log = get_logger(__name__)

#: Команды из перечня ``system.cli.executed.details.command`` (contracts/audit-events.yaml).
AUDITED_COMMANDS = frozenset(
    {
        "migrate",
        "create-superadmin",
        "issue-activation",
        "reset-superadmin",
        "auth-mode",
        "rotate-key",
        "audit verify",
        "audit purge",
        "project purge",
        "seed-demo",
    }
)

__all__ = ["AUDITED_COMMANDS", "AuditCliHook", "verify_and_record"]


async def verify_and_record(
    settings: Settings | None = None,
    *,
    actor: str = "system",
    os_user: str | None = None,
) -> VerifyResult:
    from redis.asyncio import Redis

    from estimator.db.session import create_engine

    settings = settings or get_settings()
    engine = create_engine(settings)
    try:
        async with engine.connect() as conn:
            result = await verify_chain(conn)
        await audit.write_standalone(
            "system.audit_chain.verified",
            "success" if result.ok else "failure",
            sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
            object_type="audit_log",
            details=result.details(),
            actor=actor,
            os_user=os_user,
            alert=not result.ok,
        )
    finally:
        await engine.dispose()
    redis = Redis.from_url(settings.redis_url.get_secret_value())
    try:
        await redis.set(LAST_RESULT_KEY, result_json(result))
    except Exception:  # индикатор не важнее самой проверки и записи в аудит
        log.exception("audit_verify_indicator_failed")
    finally:
        await redis.aclose()
    log.log(
        20 if result.ok else 40,
        "audit_chain_verified",
        ok=result.ok,
        checked=result.checked,
        first_broken_id=result.first_broken_id,
    )
    return result


class AuditCliHook:
    """Записать запуск консольной команды в аудит (отдельной транзакцией, после команды)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def before(self, run: Any) -> None:
        return None

    def after(self, run: Any, outcome: str, error: BaseException | None) -> None:
        if run.name not in AUDITED_COMMANDS:
            return
        exit_code = 0 if outcome == "ok" else getattr(error, "exit_code", 1) or 1
        try:
            asyncio.run(self._write(run, outcome, int(exit_code)))
        except Exception:  # нет БД (первая миграция) — команда не должна падать из-за аудита
            log.exception("cli_audit_failed", command=run.name)

    async def _write(self, run: Any, outcome: str, exit_code: int) -> None:
        from estimator.db.session import create_engine

        engine = create_engine(self._settings or get_settings())
        try:
            await audit.write_standalone(
                "system.cli.executed",
                {"ok": "success", "refused": "denied"}.get(outcome, "failure"),
                sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
                object_type="cli_command",
                object_id=run.name,
                details={
                    "command": run.name,
                    "host": socket.gethostname(),
                    "args": {k: run.public_args.get(k) for k in run.argument_names},
                    "exit_code": exit_code,
                },
                actor="cli",
                os_user=run.os_user,
            )
        finally:
            await engine.dispose()
