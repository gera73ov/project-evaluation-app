"""``estimator create-superadmin``, ``issue-activation``, ``reset-superadmin`` (AUTH-011).

SPEC FR-SA-01, FR-2FA-03, Q-22, 18.2. Пароль аргументом не принимается: команда печатает
одноразовую ссылку на 60 минут. Логика — :mod:`estimator.auth.superadmin`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import typer
from sqlalchemy.ext.asyncio import AsyncSession

EXIT_REFUSED = 1


def _run(action: Callable[[AsyncSession, str], Awaitable[object]]) -> None:
    from estimator.auth.superadmin import IssuedLink, SuperadminError
    from estimator.cli import _os_user
    from estimator.db.session import dispose_engine, transaction

    async def main() -> object:
        try:
            async with transaction() as db:
                return await action(db, _os_user())
        finally:
            await dispose_engine()

    try:
        issued = asyncio.run(main())
    except SuperadminError as exc:
        typer.echo(f"Отказ: {exc}", err=True)
        raise typer.Exit(EXIT_REFUSED) from exc
    assert isinstance(issued, IssuedLink)  # noqa: S101  # nosec B101 — тип результата действий
    typer.echo(f"Ссылка для «{issued.login}» (действует {issued.expires_minutes} минут):")
    typer.echo(issued.link)


def _base_url() -> str:
    from estimator.config import get_settings

    return get_settings().app_base_url


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    login_opt = typer.Option(..., "--login", help="Логин суперадминистратора.")

    @command(
        "create-superadmin",
        help="Создать суперадминистратора и вывести ссылку установки пароля (60 минут).",
    )
    def create_superadmin(
        login: str = login_opt,
        email: str = typer.Option(..., "--email", help="Email для оповещений."),
    ) -> None:
        from estimator.auth import superadmin

        _run(lambda db, os_user: superadmin.create_superadmin(
            db, login=login, email=email, base_url=_base_url(), os_user=os_user
        ))  # fmt: skip

    @command(
        "issue-activation",
        help="Новая ссылка установки пароля суперадминистратору; прежняя аннулируется.",
    )
    def issue_activation(login: str = login_opt) -> None:
        from estimator.auth import superadmin

        _run(lambda db, os_user: superadmin.issue_activation(
            db, login=login, base_url=_base_url(), os_user=os_user
        ))  # fmt: skip

    @command(
        "reset-superadmin",
        help=(
            "Сбросить пароль и TOTP суперадминистратора: ссылка на 60 минут, все сессии "
            "завершаются (когда доступ потеряли все суперадминистраторы)."
        ),
    )
    def reset_superadmin(login: str = login_opt) -> None:
        from estimator.auth import superadmin
        from estimator.auth.sessions import SessionService
        from estimator.config import get_settings
        from estimator.redis_client import make_redis

        async def action(db: AsyncSession, os_user: str) -> object:
            redis = make_redis(get_settings())
            try:
                return await superadmin.reset_superadmin(
                    db, SessionService(redis), login=login, base_url=_base_url(),
                    os_user=os_user,
                )  # fmt: skip
            finally:
                await redis.aclose()

        _run(action)
