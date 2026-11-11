"""Конфигурация процесса через переменные окружения (INF-002).

NFR-MNT-03: конфигурация 12-factor, список переменных с описанием и значениями по умолчанию
выгружается командой ``estimator config-env`` для README и `.env.example`.
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


class DbSslMode(StrEnum):
    """Режим TLS до PostgreSQL (DB-011, SEC-WEB-05)."""

    DISABLE = "disable"
    VERIFY_FULL = "verify-full"


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
    database_sslmode: DbSslMode = Field(
        default=DbSslMode.DISABLE,
        description=(
            "TLS до PostgreSQL: `disable` (dev, одна сеть Docker) или `verify-full` "
            "(stage, prod: проверка сертификата и имени сервера, DB-011)"
        ),
    )
    database_sslrootcert: str = Field(
        default="",
        description="Файл корневого сертификата УЦ для `verify-full`; пусто — системные УЦ",
    )
    redis_url: SecretStr = Field(
        default=SecretStr("redis://redis:6379/0"),
        description="Redis 7: сессии, pub/sub, блокировки ячеек (Docker secret `redis_url`)",
    )
    celery_broker_url: SecretStr = Field(
        default=SecretStr("redis://redis:6379/1"),
        description="Брокер Celery в Redis (Docker secret `celery_broker_url`)",
    )
    encryption_key: SecretStr | None = Field(
        default=None,
        description=(
            "Мастер-ключ шифрования AES-256-GCM в виде `<id>:<base64url 32 байта>` "
            "(SEC-CRYPT-01/02; Docker secret `encryption_key`). Новый ключ: "
            "`estimator generate-key`"
        ),
    )
    encryption_keys_old: SecretStr | None = Field(
        default=None,
        description=(
            "Прежние мастер-ключи через запятую в том же формате — только на время "
            "`estimator rotate-key` (SEC-CRYPT-02, SPEC 18.4); после ротации убрать"
        ),
    )
    app_base_url: str = Field(
        default="https://localhost",
        description=(
            "Адрес приложения для ссылок в письмах до первичной настройки (`https://…`, без `/` "
            "в конце). После мастера настройки действует `app.base_url`"
        ),
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
    backup_marker_path: str = Field(
        default="/var/lib/estimator/backup/last-success",
        description=(
            "Файл-метка последней успешной резервной копии (время ISO 8601 или время изменения "
            "файла) для «Состояния системы» (FR-SA-07); пишет скрипт бэкапа"
        ),
    )
    app_tls_cert_path: str = Field(
        default="",
        description=(
            "Сертификат TLS приложения (PEM, тот же, что у Nginx) — для метрики срока действия и "
            "оповещения «истекает < 30 дней» (18.4); пусто — не проверять"
        ),
    )
    exports_dir: str = Field(
        default="/data/exports",
        description="Каталог файлов выгрузок (том `exports`, файлы живут 24 часа, FR-EXP-05)",
    )
    documents_dir: str = Field(
        default="/data/documents",
        description="Каталог зашифрованных документов заказчика (том `documents`, SEC-CRYPT-06)",
    )
    clamav_host: str = Field(
        default="clamav",
        description="Адрес `clamd` для проверки документов заказчика (SEC-WEB-10)",
    )
    clamav_port: int = Field(default=3310, ge=1, le=65535, description="TCP-порт `clamd`")
    clamav_timeout_seconds: float = Field(
        default=60.0, gt=0, description="Таймаут проверки одного документа в `clamd`, секунды"
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

    @field_validator("app_base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("APP_BASE_URL должен начинаться с https://")
        return value.rstrip("/")

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
        if default is None:
            default = ""
        if isinstance(default, list):
            default = ",".join(default)
        if isinstance(default, StrEnum):
            default = default.value
        rows.append(f"| `{name.upper()}` | {field.description} | `{default}` |")
    return "\n".join(rows) + "\n"
