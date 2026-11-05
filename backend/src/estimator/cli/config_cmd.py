"""``estimator config-env`` — таблица переменных окружения (INF-002, NFR-MNT-03)."""

from __future__ import annotations

import typer

from estimator.config import env_table


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    @command("config-env", help="Вывести таблицу переменных окружения в Markdown для README.")
    def config_env() -> None:
        typer.echo(env_table(), nl=False)
