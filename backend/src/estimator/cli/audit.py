"""``estimator audit verify`` — проверка хэш-цепочки журнала аудита (SEC-004; SEC-AUD-03).

Код выхода 0 — цепочка цела, 1 — найдено нарушение (и отправлено оповещение ИБ).
"""

from __future__ import annotations

import asyncio

import typer

audit_app = typer.Typer(help="Журнал аудита (SEC-AUD-03, SEC-AUD-04).", no_args_is_help=True)


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    app.add_typer(audit_app, name="audit")

    @command(
        "verify",
        group=audit_app,
        group_name="audit",
        help="Проверить хэш-цепочку журнала аудита; результат — в аудит и «Состояние системы».",
    )
    def verify() -> None:
        from estimator.cli import _os_user
        from estimator.security.audit.runs import verify_and_record

        result = asyncio.run(verify_and_record(actor="cli", os_user=_os_user()))
        if result.ok:
            typer.echo(f"Цепочка цела: проверено записей {result.checked}.")
            return
        what = "запись изменена" if result.reason == "modified" else "разрыв цепочки"
        typer.echo(
            f"НАРУШЕНИЕ ЦЕПОЧКИ: {what}, id {result.first_broken_id}; "
            f"до неё проверено {result.checked}. Оповещение ИБ отправлено.",
            err=True,
        )
        raise typer.Exit(1)
