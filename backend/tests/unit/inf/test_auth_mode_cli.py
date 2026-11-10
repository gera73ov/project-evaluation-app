"""AUTH-019: ``estimator auth-mode local`` — отказ для других режимов, CSV ссылок на stdout."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

import estimator.cli as cli
from estimator.auth.switch_mode import to_local as switch

pytestmark = pytest.mark.spec("FR-AUTH-SW-01")
runner = CliRunner()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class FakeTx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *exc: object) -> None:
            return None

    class FakeRedis:
        async def aclose(self) -> None:
            return None

    async def dispose() -> None:
        return None

    async def to_local(_db: object, _redis: object, **kwargs: Any) -> switch.LocalResult:
        calls.append(kwargs)
        if len(calls) > 1:
            raise switch.SwitchRefused("вход уже идёт через приложение")
        return switch.LocalResult(
            converted=2,
            emailed=0,
            blocked=["gone"],
            smtp=False,
            handouts=[switch.Handout("lead", "Иванов; Иван", "https://x/a")],
        )

    monkeypatch.setattr("estimator.db.session.transaction", lambda: FakeTx())
    monkeypatch.setattr("estimator.db.session.dispose_engine", dispose)
    monkeypatch.setattr("estimator.redis_client.make_redis", lambda _s: FakeRedis())
    monkeypatch.setattr(switch, "to_local", to_local)
    cli.load_commands()
    return calls


def test_local_prints_csv_then_refuses_again(fake: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.app, ["auth-mode", "local"])
    assert result.exit_code == 0, result.output
    csv_lines = [line for line in result.stdout.splitlines() if "cli_command" not in line]
    assert csv_lines == [  # строки JSON-лога в тестах тоже идут в stdout
       "логин;ФИО;одноразовая ссылка",
                                          'lead;"Иванов; Иван";https://x/a']  # fmt: skip
    assert "SMTP не настроен" in result.stderr
    assert fake[0]["dry_run"] is False
    again = runner.invoke(cli.app, ["auth-mode", "local"])
    assert again.exit_code == 1
    assert "Отказ: вход уже идёт через приложение" in again.output


def test_only_local(fake: list[dict[str, Any]]) -> None:
    result = runner.invoke(cli.app, ["auth-mode", "ad"])
    assert result.exit_code == 1
    assert fake == []
