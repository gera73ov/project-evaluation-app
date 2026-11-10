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

    @command(
        "purge",
        group=audit_app,
        group_name="audit",
        help=(
            "Удалить записи аудита старше срока хранения (retention, не меньше 6 мес.) от роли "
            "estimator_audit_purge; хэш последней удалённой — якорь цепочки."
        ),
    )
    def purge(
        dry_run: bool = typer.Option(
            False, "--dry-run", help="Только посчитать записи к удалению, ничего не удалять."
        ),
    ) -> None:
        from estimator.cli import _os_user
        from estimator.security.audit.purge import PurgeError, run

        try:
            result = asyncio.run(run(dry_run=dry_run, os_user=_os_user()))
        except PurgeError as exc:
            typer.echo(f"Ошибка: {exc}.", err=True)
            raise typer.Exit(2) from exc
        when = f"старше {result.before.isoformat()} (срок {result.months} мес.)"
        if dry_run:
            typer.echo(f"Будет удалено записей {when}: {result.deleted}. Ничего не удалено.")
            return
        typer.echo(f"Удалено записей {when}: {result.deleted}.")
        if result.anchor_hash:
            typer.echo(f"Якорь цепочки: {result.anchor_hash}.")
