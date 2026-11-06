"""AUTH-011: команды суперадминистратора в CLI — вывод ссылки, отказ, пароль не аргумент."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

import estimator.cli as cli
from estimator.auth import superadmin
from estimator.auth.superadmin import IssuedLink, SuperadminError

pytestmark = pytest.mark.spec("FR-SA-01")
runner = CliRunner()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    class FakeTx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *exc: object) -> None:
            return None

    async def dispose() -> None:
        return None

    def recorder(name: str, *, fail: bool = False) -> Any:
        async def action(_db: object, *_args: object, **kwargs: Any) -> IssuedLink:
            calls.append((name, kwargs))
            if kwargs.get("login") == "bad":
                raise SuperadminError("нельзя")
            return IssuedLink(kwargs["login"], f"https://x/{name}?token=t")

        return action

    monkeypatch.setattr("estimator.db.session.transaction", lambda: FakeTx())
    monkeypatch.setattr("estimator.db.session.dispose_engine", dispose)
    for name in ("create_superadmin", "issue_activation", "reset_superadmin"):
        monkeypatch.setattr(superadmin, name, recorder(name))
    cli.load_commands()
    return calls


def test_create_prints_link(fake: list[tuple[str, dict[str, Any]]]) -> None:
    result = runner.invoke(cli.app, ["create-superadmin", "--login", "root", "--email", "a@b.c"])
    assert result.exit_code == 0, result.output
    assert "действует 60 минут" in result.output
    assert "https://x/create_superadmin?token=t" in result.output
    name, kwargs = fake[0]
    assert (name, kwargs["login"], kwargs["email"]) == ("create_superadmin", "root", "a@b.c")
    assert kwargs["base_url"].startswith("https://")


def test_issue_and_reset(fake: list[tuple[str, dict[str, Any]]]) -> None:
    assert runner.invoke(cli.app, ["issue-activation", "--login", "root"]).exit_code == 0
    assert runner.invoke(cli.app, ["reset-superadmin", "--login", "root"]).exit_code == 0
    assert [c[0] for c in fake] == ["issue_activation", "reset_superadmin"]


def test_refusal_exit_code(fake: list[tuple[str, dict[str, Any]]]) -> None:
    result = runner.invoke(cli.app, ["issue-activation", "--login", "bad"])
    assert result.exit_code == 1
    assert "Отказ: нельзя" in result.output


def test_no_password_option() -> None:
    cli.load_commands()
    result = runner.invoke(cli.app, ["create-superadmin", "--login", "r", "--email", "e",
                                     "--password", "x"])  # fmt: skip
    assert result.exit_code != 0
