"""INF-002: конфигурация через окружение (NFR-MNT-03, SEC-CRYPT-01)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from estimator.config import AppEnv, Settings, env_table, get_settings

pytestmark = pytest.mark.spec("NFR-MNT-03")


def test_defaults_are_dev() -> None:
    s = Settings()
    assert s.app_env is AppEnv.DEV
    assert not s.is_prod
    assert s.app_timezone == "Europe/Moscow"


def test_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("TRUSTED_HOSTS", "est.example.local, localhost")
    s = get_settings()
    assert s.is_prod
    assert s.log_level == "DEBUG"
    assert s.trusted_hosts == ["est.example.local", "localhost"]


def test_list_value_passes_through() -> None:
    assert Settings(trusted_hosts=["a"]).trusted_hosts == ["a"]


@pytest.mark.parametrize(
    ("name", "value"),
    [("LOG_LEVEL", "LOUD"), ("APP_TIMEZONE", "Mars/Olympus"), ("APP_ENV", "qa")],
)
def test_rejects_invalid(monkeypatch: pytest.MonkeyPatch, name: str, value: str) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.spec("SEC-CRYPT-01")
def test_secrets_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:hunter2@db/x")
    s = Settings()
    assert "hunter2" not in repr(s)
    assert "hunter2" in s.database_url.get_secret_value()


def test_env_table_lists_every_variable() -> None:
    table = env_table()
    for name in Settings.model_fields:
        assert f"`{name.upper()}`" in table
    assert "| `APP_ENV` |" in table
    assert "`dev`" in table
