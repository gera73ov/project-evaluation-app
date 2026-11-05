"""DB-005: денежные модели импортирует только сервис денег (contracts/db/schema.md G-11).

SEC-AUTHZ-04: деньги не должны утечь через сериализацию «чужого» модуля, поэтому сам импорт
``estimator.db.models.money`` разрешён только ``estimator.services.money`` и пакету моделей
(метаданные для Alembic). Проверка — по AST всех модулей ``src/estimator``, как контракт
import-linter ``forbidden``, без отдельной зависимости.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.spec("SEC-AUTHZ-04")

SRC = Path(__file__).resolve().parents[3] / "src"
MONEY = "estimator.db.models.money"
ALLOWED_PREFIXES = ("estimator.services.money", "estimator.db.models")


def _module_name(path: Path, root: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def money_importers(root: Path = SRC) -> set[str]:
    found = set()
    for path in root.rglob("*.py"):
        module = _module_name(path, root)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    anchor = package.split(".")
                    anchor = anchor[: len(anchor) - (node.level - 1)]
                    base = ".".join([*anchor, base] if base else anchor)
                targets = [base, *(f"{base}.{a.name}" for a in node.names)]
            if any(t == MONEY or t.startswith(MONEY + ".") for t in targets):
                found.add(module)
    return found


def test_only_money_service_imports_money_models() -> None:
    offenders = {
        m
        for m in money_importers()
        if m != MONEY and not any(m == p or m.startswith(p + ".") for p in ALLOWED_PREFIXES)
    }
    assert not offenders, f"денежные модели импортируют: {sorted(offenders)} (G-11)"


def test_detector_finds_forbidden_import(tmp_path: Path) -> None:
    pkg = tmp_path / "estimator" / "services" / "tree"
    pkg.mkdir(parents=True)
    (pkg / "leak.py").write_text("from estimator.db.models import money\n", encoding="utf-8")
    (pkg / "rel.py").write_text("from ...db.models.money import ProjectRate\n", encoding="utf-8")
    assert money_importers(tmp_path) == {
        "estimator.services.tree.leak",
        "estimator.services.tree.rel",
    }
