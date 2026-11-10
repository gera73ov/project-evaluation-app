"""``estimator auth-mode local`` — переход «AD → Приложение» (AUTH-019; FR-AUTH-SW-01, 18.2).

Обратный переход в интерфейсе запрещён (Q-20), его выполняет служба эксплуатации ИТ. Команда
печатает итог, а ссылки тех, кому письмо не ушло (SMTP не настроен или нет email), — в CSV
«логин; ФИО; одноразовая ссылка» на stdout; сводка — в stderr, чтобы CSV можно было перенаправить
в файл. ``--dry-run`` только считает. Логика — :mod:`estimator.auth.switch_mode.to_local`.
"""

from __future__ import annotations

import asyncio
import csv
import io

import typer

EXIT_REFUSED = 1


def handout_csv(rows: list[tuple[str, str, str]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(("логин", "ФИО", "одноразовая ссылка"))
    writer.writerows(rows)
    return out.getvalue()


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    @command(
        "auth-mode",
        help=(
            "Перейти со входа через AD на вход через приложение: все становятся локальными, "
            "ссылки установки пароля на 72 часа, все сессии завершаются."
        ),
    )
    def auth_mode(
        mode: str = typer.Argument(..., help="Новый режим: только «local»."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Только посчитать."),
    ) -> None:
        from estimator.auth.switch_mode import to_local as switch
        from estimator.cli import _os_user
        from estimator.config import get_settings
        from estimator.db.session import dispose_engine, transaction
        from estimator.redis_client import make_redis

        if mode != "local":
            typer.echo("Отказ: из консоли возможен только переход «local»; переход на AD — "
                       "в интерфейсе суперадминистратора.", err=True)  # fmt: skip
            raise typer.Exit(EXIT_REFUSED)

        async def main() -> switch.LocalResult:
            redis = make_redis(get_settings())
            try:
                async with transaction() as db:
                    return await switch.to_local(db, redis, os_user=_os_user(), dry_run=dry_run)
            finally:
                await redis.aclose()
                await dispose_engine()

        try:
            result = asyncio.run(main())
        except switch.SwitchRefused as exc:
            typer.echo(f"Отказ: {exc}", err=True)
            raise typer.Exit(EXIT_REFUSED) from exc
        verb = "Будет переведено" if result.dry_run else "Переведено"
        typer.echo(f"{verb} в локальные: {result.converted}; письмом: {result.emailed}; "
                   f"заблокированы, без ссылки: {len(result.blocked)}.", err=True)  # fmt: skip
        if not result.smtp:
            typer.echo("SMTP не настроен: ссылки выдайте пользователям сами.", err=True)
        if result.dry_run:
            return
        typer.echo(f"Роли из групп AD стали ручными: {result.roles_made_manual}; "
                   f"завершено сессий: {result.sessions_ended}.", err=True)  # fmt: skip
        if result.handouts:
            typer.echo(handout_csv([(h.login, h.full_name, h.link) for h in result.handouts]),
                       nl=False)  # fmt: skip
