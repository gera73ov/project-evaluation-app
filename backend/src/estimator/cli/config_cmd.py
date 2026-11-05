"""``estimator config-env`` — таблица переменных окружения (INF-002, DOC-001, NFR-MNT-03).

Без аргументов печатает таблицу в Markdown. С ``--write README.md`` заменяет таблицу между
метками :data:`BEGIN` и :data:`END`, с ``--check README.md`` только сверяет её (для CI).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from estimator.config import env_table

BEGIN = "<!-- env-table:begin (estimator config-env --write README.md) -->"
END = "<!-- env-table:end -->"

#: Код выхода, когда таблица в README устарела.
EXIT_STALE = 1


def replace_table(text: str, table: str) -> str:
    """Подставить таблицу между метками. Без меток — ``ValueError``."""
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < start:
        raise ValueError(f"в файле нет меток {BEGIN!r} … {END!r}")
    return text[: start + len(BEGIN)] + "\n" + table + text[end:]


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    @command("config-env", help="Таблица переменных окружения в Markdown для README.")
    def config_env(
        write: Annotated[
            Path | None, typer.Option(help="Обновить таблицу в этом файле (README.md).")
        ] = None,
        check: Annotated[
            Path | None, typer.Option(help="Проверить, что таблица в файле актуальна.")
        ] = None,
    ) -> None:
        table = env_table()
        target = write or check
        if target is None:
            typer.echo(table, nl=False)
            return
        current = target.read_text(encoding="utf-8")
        expected = replace_table(current, table)
        if write is not None:
            target.write_text(expected, encoding="utf-8")
            typer.echo(f"таблица переменных обновлена в {target}")
        elif current != expected:
            typer.echo(
                f"таблица переменных в {target} устарела: "
                "запустите `uv --directory backend run estimator config-env --write ../README.md`",
                err=True,
            )
            raise typer.Exit(EXIT_STALE)
