"""INF-007: каркас CLI ``estimator`` (SPEC 18.2, SEC-AUD-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

import estimator.cli as cli
from estimator.cli import EXIT_FORBIDDEN_ENV, CommandRun, add_hook, command, remove_hook

runner = CliRunner()


@command("test-stand-only", stand_only=True, hidden=True)
def _stand_only() -> None:
    typer.echo("seeded")


@command("test-fails", hidden=True)
def _fails() -> None:
    raise RuntimeError("boom")


@command("test-exit", hidden=True)
def _exit(code: int = 0) -> None:
    raise typer.Exit(code)


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, str | None]] = []

    def before(self, run: CommandRun) -> None:
        self.events.append(("before", run.name, run.os_user))

    def after(self, run: CommandRun, outcome: str, error: BaseException | None) -> None:
        self.events.append(("after", run.name, outcome))


@pytest.fixture
def recorder():
    rec = Recorder()
    add_hook(rec)
    yield rec
    remove_hook(rec)


@pytest.fixture(autouse=True)
def _commands() -> None:
    cli.load_commands()
    cli.load_commands()  # повторный вызов ничего не ломает


def test_help_lists_registered_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "migrate" in result.output
    assert "config-env" in result.output
    assert "test-stand-only" not in result.output  # скрытые не показываются


@pytest.mark.spec("SEC-AUD-01")
def test_hook_runs_for_every_command(recorder: Recorder) -> None:
    runner.invoke(cli.app, ["config-env"])
    runner.invoke(cli.app, ["test-fails"])
    names = [(e[0], e[1]) for e in recorder.events]
    assert names == [
        ("before", "config-env"),
        ("after", "config-env"),
        ("before", "test-fails"),
        ("after", "test-fails"),
    ]
    assert recorder.events[1][2] == "ok"
    assert recorder.events[3][2] == "error"
    assert recorder.events[0][2]  # имя пользователя ОС записано


def test_exit_codes_map_to_outcome(recorder: Recorder) -> None:
    assert runner.invoke(cli.app, ["test-exit"]).exit_code == 0
    assert runner.invoke(cli.app, ["test-exit", "--code", "4"]).exit_code == 4
    outcomes = [e[2] for e in recorder.events if e[0] == "after"]
    assert outcomes == ["ok", "error"]


@pytest.mark.spec("SPEC-17.4")
def test_stand_only_refuses_on_prod(monkeypatch: pytest.MonkeyPatch, recorder: Recorder) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    result = runner.invoke(cli.app, ["test-stand-only"])
    assert result.exit_code == EXIT_FORBIDDEN_ENV
    assert "seeded" not in result.output
    assert recorder.events[-1] == ("after", "test-stand-only", "refused")


@pytest.mark.parametrize("env", ["dev", "test", "stage"])
def test_stand_only_runs_on_stands(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    result = runner.invoke(cli.app, ["test-stand-only"])
    assert result.exit_code == 0
    assert "seeded" in result.output


def test_config_env_prints_table() -> None:
    result = runner.invoke(cli.app, ["config-env"])
    assert result.exit_code == 0
    assert "| `DATABASE_URL` |" in result.output


def test_migrate_without_alembic_ini(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ALEMBIC_CONFIG", str(tmp_path / "missing.ini"))
    result = runner.invoke(cli.app, ["migrate"])
    assert result.exit_code == 2
    assert "DB-002" in result.output


def test_migrate_calls_alembic(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ini = tmp_path / "alembic.ini"
    ini.write_text("[alembic]\n")
    calls: list[tuple[str, str]] = []

    def fake_upgrade(config, revision):
        calls.append((config.config_file_name, revision))

    monkeypatch.setenv("ALEMBIC_CONFIG", str(ini))
    monkeypatch.setattr("alembic.command.upgrade", fake_upgrade)
    result = runner.invoke(cli.app, ["migrate"])
    assert result.exit_code == 0, result.output
    assert calls == [(str(ini), "head")]

    downgrades: list[str] = []
    monkeypatch.setattr("alembic.command.downgrade", lambda _c, rev: downgrades.append(rev))
    result = runner.invoke(cli.app, ["migrate", "--downgrade", "0010_x"])
    assert result.exit_code == 0, result.output
    assert downgrades == ["0010_x"]


def test_main_entrypoint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.argv", ["estimator", "config-env"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("| Переменная")  # логи не смешаны с выводом
    assert "cli_command_finished" in captured.err


def test_os_user_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_user() -> str:
        raise KeyError("uid")

    monkeypatch.setattr("getpass.getuser", no_user)
    assert cli._os_user() == "unknown"


@pytest.mark.spec("17.4")
def test_seed_demo_refuses_on_prod(monkeypatch: pytest.MonkeyPatch) -> None:
    cli.load_commands()
    monkeypatch.setenv("APP_ENV", "prod")
    result = runner.invoke(cli.app, ["seed-demo", "--password", "x"])
    assert result.exit_code == EXIT_FORBIDDEN_ENV
