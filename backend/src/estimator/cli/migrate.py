"""``estimator migrate`` — применить миграции БД (INF-007; SPEC 18.2, 18.3 шаг 3).

Обёртка над ``alembic upgrade head``. Сами миграции и ``alembic.ini`` ведёт трек DB (DB-002).
"""

from __future__ import annotations

import os
from pathlib import Path

import typer

#: Путь к ``alembic.ini``; в образе ``api`` рабочий каталог — ``/app``.
ALEMBIC_CONFIG_ENV = "ALEMBIC_CONFIG"


def _config_path() -> Path:
    return Path(os.environ.get(ALEMBIC_CONFIG_ENV, "alembic.ini"))


def upgrade_head(config_path: Path) -> None:
    """Выполнить ``alembic upgrade head`` с указанным конфигом."""
    from alembic import command as alembic_command
    from alembic.config import Config

    alembic_command.upgrade(Config(str(config_path)), "head")


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    @command("migrate", help="Применить миграции БД до последней версии (alembic upgrade head).")
    def migrate() -> None:
        path = _config_path()
        if not path.is_file():
            typer.echo(
                f"Не найден {path}: миграции ещё не созданы (DB-002) или неверен "
                f"{ALEMBIC_CONFIG_ENV}.",
                err=True,
            )
            raise typer.Exit(2)
        upgrade_head(path)
        typer.echo("Миграции применены.")
