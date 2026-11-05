"""Консольная утилита ``estimator`` (INF-007).

SPEC 18.2: команды выполняет служба эксплуатации; каждый запуск — в журнал аудита с именем
пользователя ОС (SEC-AUD-01). Каркас даёт:

* реестр подкоманд: трек-владелец кладёт команду в ``cli/<команда>.py`` с функцией
  ``register(app)`` и добавляет модуль в :data:`COMMAND_MODULES`;
* общий хук «до/после команды» (:func:`add_hook`): запись аудита подключает SEC-004;
* метку «только для стендов» (``stand_only=True``): на ``APP_ENV=prod`` такая команда
  отказывается работать (например, ``seed-demo``, SPEC 17.4).
"""

from __future__ import annotations

import functools
import getpass
import importlib
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

import typer

from estimator.config import get_settings
from estimator.logging import configure_logging, get_logger

#: Модули с командами; порядок = порядок в ``estimator --help``.
COMMAND_MODULES: tuple[str, ...] = (
    "estimator.cli.migrate",
    "estimator.cli.config_cmd",
    "estimator.cli.rotate_key",
)

#: Код выхода, когда команда запрещена в текущем окружении.
EXIT_FORBIDDEN_ENV = 3

F = TypeVar("F", bound=Callable[..., Any])
log = get_logger(__name__)

app = typer.Typer(
    name="estimator",
    help="Консольные команды приложения оценки проектов (SPEC 18.2).",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


@dataclass
class CommandRun:
    """Сведения о запуске команды для хуков (без значений аргументов — в них бывают секреты)."""

    name: str
    os_user: str
    app_env: str
    argument_names: list[str]
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class CommandHook(Protocol):
    """Хук вокруг каждой команды. ``outcome``: ``ok``, ``error`` или ``refused``."""

    def before(self, run: CommandRun) -> None: ...

    def after(self, run: CommandRun, outcome: str, error: BaseException | None) -> None: ...


_hooks: list[CommandHook] = []


def add_hook(hook: CommandHook) -> None:
    """Подключить хук (SEC-004 подключает запись аудита)."""
    _hooks.append(hook)


def remove_hook(hook: CommandHook) -> None:
    _hooks.remove(hook)


class LogHook:
    """Хук по умолчанию: строка в JSON-лог о начале и конце команды."""

    def before(self, run: CommandRun) -> None:
        log.info("cli_command_started", command=run.name, os_user=run.os_user)

    def after(self, run: CommandRun, outcome: str, error: BaseException | None) -> None:
        log.info(
            "cli_command_finished",
            command=run.name,
            os_user=run.os_user,
            outcome=outcome,
            error_type=type(error).__name__ if error else None,
            duration_ms=round((datetime.now(UTC) - run.started_at).total_seconds() * 1000, 1),
        )


add_hook(LogHook())


def _os_user() -> str:
    try:
        return getpass.getuser()
    except (KeyError, OSError):  # пользователь без записи в /etc/passwd (контейнер)
        return "unknown"


def command(name: str, *, stand_only: bool = False, **typer_kwargs: Any) -> Callable[[F], F]:
    """Зарегистрировать подкоманду с хуками и проверкой окружения."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            settings = get_settings()
            run = CommandRun(
                name=name,
                os_user=_os_user(),
                app_env=settings.app_env.value,
                argument_names=sorted(kwargs),
            )
            for hook in _hooks:
                hook.before(run)
            if stand_only and settings.is_prod:
                typer.echo(
                    f"Команда «{name}» только для тестовых стендов и на prod не запускается.",
                    err=True,
                )
                for hook in _hooks:
                    hook.after(run, "refused", None)
                raise typer.Exit(EXIT_FORBIDDEN_ENV)
            try:
                result = func(*args, **kwargs)
            except typer.Exit as exc:
                outcome = "ok" if exc.exit_code == 0 else "error"
                for hook in _hooks:
                    hook.after(run, outcome, None if outcome == "ok" else exc)
                raise
            except BaseException as exc:
                for hook in _hooks:
                    hook.after(run, "error", exc)
                raise
            for hook in _hooks:
                hook.after(run, "ok", None)
            return result

        wrapper.stand_only = stand_only  # type: ignore[attr-defined]
        app.command(name=name, **typer_kwargs)(wrapper)
        return func

    return decorator


_loaded = False


def load_commands() -> None:
    """Импортировать модули команд из реестра (один раз)."""
    global _loaded
    if _loaded:
        return
    for module in COMMAND_MODULES:
        importlib.import_module(module).register(app)
    _loaded = True


def main() -> None:
    """Точка входа ``estimator`` (pyproject ``[project.scripts]``)."""
    configure_logging(get_settings().log_level, stream="stderr")
    load_commands()
    started = time.perf_counter()
    try:
        app()
    finally:
        log.debug("cli_exit", duration_ms=round((time.perf_counter() - started) * 1000, 1))
