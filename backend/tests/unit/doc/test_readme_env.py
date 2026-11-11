"""DOC-001: README и `.env.example` совпадают с конфигом приложения (NFR-MNT-03)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

import estimator.cli as cli
from estimator.cli.config_cmd import BEGIN, END, EXIT_STALE, replace_table
from estimator.config import Settings, env_table

ROOT = Path(__file__).resolve().parents[4]
README = ROOT / "README.md"
ENV_EXAMPLE = ROOT / ".env.example"

pytestmark = pytest.mark.spec("NFR-MNT-03")
runner = CliRunner()


def test_readme_table_matches_config() -> None:
    text = README.read_text(encoding="utf-8")
    assert replace_table(text, env_table()) == text, (
        "таблица в README устарела: uv --directory backend run estimator config-env "
        "--write ../README.md"
    )


def test_readme_has_required_sections() -> None:
    text = README.read_text(encoding="utf-8")
    for heading in (
        "## Как поднять dev-стенд",
        "## Как запускать тесты",
        "## Переменные окружения",
    ):
        assert heading in text
    assert "docs/spec/SPEC.md" in text
    assert "PLAN.md" in text


def test_env_example_mentions_every_setting() -> None:
    """Каждая переменная конфига есть в `.env.example`: значением или комментарием."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    missing = [
        name.upper()
        for name in Settings.model_fields
        if not re.search(rf"\b{name.upper()}\b", text)
    ]
    assert missing == []


def test_env_example_has_no_real_secrets() -> None:
    """Пароли в `.env.example` — только заглушки, которые `make env` заменит (SEC-CRYPT-01)."""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.endswith("_PASSWORD"):
            assert value.lower().startswith("change-me"), key


def test_replace_table_requires_markers() -> None:
    with pytest.raises(ValueError, match="нет меток"):
        replace_table("README без меток", "| t |\n")
    assert replace_table(f"a\n{BEGIN}\nold\n{END}\nb", "new\n") == f"a\n{BEGIN}\nnew\n{END}\nb"


def test_cli_write_and_check(tmp_path: Path) -> None:
    cli.load_commands()
    target = tmp_path / "README.md"
    target.write_text(f"# t\n{BEGIN}\nстарое\n{END}\n", encoding="utf-8")

    stale = runner.invoke(cli.app, ["config-env", "--check", str(target)])
    assert stale.exit_code == EXIT_STALE

    written = runner.invoke(cli.app, ["config-env", "--write", str(target)])
    assert written.exit_code == 0
    assert env_table() in target.read_text(encoding="utf-8")

    fresh = runner.invoke(cli.app, ["config-env", "--check", str(target)])
    assert fresh.exit_code == 0


#: Файлы, из которых переменные окружения читают compose и скрипты эксплуатации (DOC-007).
OPS_FILES = ("deploy/compose/*.yml", "deploy/backup/*.sh", "deploy/scripts/*.sh",
             "deploy/logging/*.sh", "deploy/envs/*.yml", "deploy/envs/*.sh")  # fmt: skip
#: В compose переменная — любое ``${NAME``; в скриптах — только с умолчанием или
#: обязательная (``${NAME:-…}``, ``${NAME:?}``), остальное — внутренние переменные скрипта.
COMPOSE_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]+)")
SCRIPT_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]+):[-?]")


def _ops_variables() -> set[str]:
    found: set[str] = set()
    for pattern in OPS_FILES:
        for path in ROOT.glob(pattern):
            rx = COMPOSE_VAR if path.suffix == ".yml" else SCRIPT_VAR
            found |= set(rx.findall(path.read_text(encoding="utf-8")))
    return found


def test_readme_describes_ops_variables() -> None:
    """DOC-007: каждая переменная compose и скриптов эксплуатации описана в README."""
    text = README.read_text(encoding="utf-8")
    table = text[
        text.index("<!-- ops-env-table:begin -->") : text.index("<!-- ops-env-table:end -->")
    ]
    variables = _ops_variables()
    assert {"POSTGRES_PASSWORD", "BACKUP_KEEP_DAYS", "LOG_DIR"} <= variables
    missing = sorted(v for v in variables if f"`{v}`" not in table)
    assert missing == []
