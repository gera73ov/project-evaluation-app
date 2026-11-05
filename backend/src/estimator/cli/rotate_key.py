"""``estimator rotate-key`` и ``estimator generate-key`` (SEC-003; SEC-CRYPT-02, SPEC 18.4).

Запуск пишется в аудит общим хуком CLI (INF-007, SEC-004) с именем пользователя ОС.
Порядок ротации — :mod:`estimator.security.crypto.rotation`.
"""

from __future__ import annotations

import asyncio

import typer

from estimator.security.crypto.keys import KeyConfigError, format_key, generate_key

EXIT_REMAINING = 4


async def _run(*, check: bool) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    from estimator.config import get_settings
    from estimator.security.crypto import Cipher, keyring_from_settings
    from estimator.security.crypto.rotation import rotate

    settings = get_settings()
    cipher = Cipher(keyring_from_settings(settings))
    engine = create_async_engine(settings.database_url.get_secret_value())
    try:
        async with engine.begin() as conn:
            report = await rotate(conn, cipher, dry_run=check)
    finally:
        await engine.dispose()
    typer.echo(f"Текущий ключ: {report.current_kid}")
    for name, rep in report.targets.items():
        line = f"  {name}: всего {rep.total}, на старых ключах {rep.on_old_keys}"
        if not check:
            line += f", перешифровано {rep.reencrypted}"
        if rep.changed_concurrently:
            line += f", изменено приложением во время ротации {rep.changed_concurrently}"
        typer.echo(line)
    for error in report.errors:
        typer.echo(f"Ошибка: {error}", err=True)
    if report.errors:
        return 1
    if check and report.remaining:
        typer.echo(
            "Есть значения на старых ключах: запустите estimator rotate-key, ключи из "
            "ENCRYPTION_KEYS_OLD пока не убирайте.",
            err=True,
        )
        return EXIT_REMAINING
    if check:
        typer.echo("Все значения на текущем ключе: ENCRYPTION_KEYS_OLD можно убрать.")
    return 0


def register(app: typer.Typer) -> None:
    from estimator.cli import command

    @command(
        "rotate-key",
        help=(
            "Перешифровать секреты TOTP, секретные настройки и ключи документов текущим "
            "мастер-ключом (ENCRYPTION_KEY); старые ключи — в ENCRYPTION_KEYS_OLD."
        ),
    )
    def rotate_key(
        check: bool = typer.Option(
            False, "--check", help="Только проверить: сколько значений на старых ключах."
        ),
    ) -> None:
        try:
            code = asyncio.run(_run(check=check))
        except KeyConfigError as exc:
            typer.echo(f"Ключи шифрования: {exc}", err=True)
            raise typer.Exit(2) from exc
        raise typer.Exit(code)

    @command(
        "generate-key",
        help=(
            "Выпустить новый мастер-ключ (256 бит) в формате ENCRYPTION_KEY. Ключ выводится "
            "один раз: сохраните его в хранилище секретов и запечатанную копию — в сейф ИБ."
        ),
    )
    def generate(
        kid: str = typer.Option("", "--id", help="Идентификатор ключа; по умолчанию kГГГГММДД."),
    ) -> None:
        try:
            key = generate_key(kid or None)
        except KeyConfigError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(2) from exc
        typer.echo(format_key(key))
