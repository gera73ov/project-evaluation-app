"""Конфигурация процесса через переменные окружения (INF-002).

NFR-MNT-03: конфигурация 12-factor, список переменных с описанием и значениями по умолчанию
выгружается командой ``estimator config env`` для README и `.env.example`.
SEC-CRYPT-01: секреты приходят из окружения или из файлов Docker secrets (``/run/secrets``),
в репозитории и образах их нет; в логах и выводе ``repr`` они скрыты (``SecretStr``).

Здесь только параметры запуска процесса. Настройки, которые меняет суперадминистратор
(``auth.*``, ``smtp.*``, ``siem.*``, ``app.timezone`` и др.), живут в таблице ``system_settings``
(контракт ``contracts/settings.schema.json``, трек ADM).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

SECRETS_DIR = Path("/run/secrets")


class AppEnv(StrEnum):
    """Окружение (SPEC 18.1). На ``prod`` команды «только для стендов» не запускаются."""

    DEV = "dev"
    TEST = "test"
    STAGE = "stage"
    PROD = "prod"


class Settings(BaseSettings):
    """Параметры процесса. Имя переменной окружения = имя поля в верхнем регистре."""

    model_config = SettingsConfigDict(
        env_file=None,
        secrets_dir=str(SECRETS_DIR) if SECRETS_DIR.is_dir() else None,
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = Field(
        default=AppEnv.DEV,
        description="Окружение: dev, test, stage, prod (SPEC 18.1)",
    )
    app_version: str = Field(
        default="0.1.0",
        description="Версия приложения для «Состояния системы» и логов; задаётся при сборке образа",
    )
    log_level: str = Field(
        default="INFO",
        description="Уровень логов: DEBUG, INFO, WARNING, ERROR",
    )
    database_url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://estimator@postgres:5432/estimator"),
        description=(
            "Строка подключения к PostgreSQL 16 (драйвер asyncpg); секрет — пароль внутри строки "
            "(Docker secret `database_url`)"
        ),
    )
    redis_url: SecretStr = Field(
        default=SecretStr("redis://redis:6379/0"),
        description="Redis 7: сессии, pub/sub, блокировки ячеек (Docker secret `redis_url`)",
    )
    celery_broker_url: SecretStr = Field(
        default=SecretStr("redis://redis:6379/1"),
        description="Брокер Celery в Redis (Docker secret `celery_broker_url`)",
    )
    app_timezone: str = Field(
        default="Europe/Moscow",
        description=(
            "Часовой пояс приложения IANA до первичной настройки: по нему считаются ночные "
            "задачи (FR-UI-02). После мастера настройки действует `app.timezone`"
        ),
    )
    health_timeout_seconds: float = Field(
        default=2.0,
        gt=0,
        description="Таймаут одной проверки `/health/ready`, секунды",
    )
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["*"],
        description=(
            "Разрешённые значения заголовка Host через запятую; на stage и prod — имя сервера"
        ),
    )

    @field_validator("log_level")
    @classmethod
    def _check_level(cls, value: str) -> str:
        level = value.upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"неизвестный уровень логов: {value}")
        return level

    @field_validator("app_timezone")
    @classmethod
    def _check_tz(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"неизвестный часовой пояс IANA: {value}") from exc
        return value

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return [h.strip() for h in value.split(",") if h.strip()]
        return value

    @property
    def is_prod(self) -> bool:
        return self.app_env is AppEnv.PROD


@lru_cache
def get_settings() -> Settings:
    """Настройки процесса (читаются один раз)."""
    return Settings()


def env_table() -> str:
    """Таблица переменных окружения в Markdown для README (NFR-MNT-03)."""
    rows = [
        "| Переменная | Описание | По умолчанию |",
        "|---|---|---|",
    ]
    for name, field in Settings.model_fields.items():
        default = field.get_default(call_default_factory=True)
        if isinstance(default, SecretStr):
            default = default.get_secret_value()
        if isinstance(default, list):
            default = ",".join(default)
        if isinstance(default, StrEnum):
            default = default.value
        rows.append(f"| `{name.upper()}` | {field.description} | `{default}` |")
    return "\n".join(rows) + "\n"
