"""DB-002: правила миграций без БД — линейная история, обязательный downgrade, роли.

Правила — backend/alembic/README.md (NFR-MNT-02).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from estimator.db import roles

pytestmark = pytest.mark.spec("NFR-MNT-02")

BACKEND = Path(__file__).resolve().parents[3]
VERSIONS = BACKEND / "alembic" / "versions"


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND / "alembic.ini")))


def test_single_head_and_linear_history() -> None:
    script = _script()
    assert len(script.get_heads()) == 1, "история миграций должна быть линейной (один head)"
    for rev in script.walk_revisions():
        assert not rev.is_merge_point, f"{rev.revision}: merge-ревизии запрещены"
        assert not rev.branch_labels, f"{rev.revision}: ветки миграций запрещены"


def test_revision_ids_are_numbered_like_files() -> None:
    script = _script()
    revs = list(reversed(list(script.walk_revisions())))
    for number, rev in enumerate(revs, start=1):
        assert rev.revision.startswith(f"{number:04d}_"), rev.revision
        assert Path(rev.path).stem == rev.revision


@pytest.mark.parametrize("path", sorted(VERSIONS.glob("*.py")), ids=lambda p: p.stem)
def test_downgrade_is_implemented(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    assert {"upgrade", "downgrade"} <= funcs.keys()
    for node in ast.walk(funcs["downgrade"]):
        if isinstance(node, ast.Raise):
            pytest.fail(f"{path.name}: downgrade не реализован")
    body = funcs["downgrade"].body
    assert not (len(body) == 1 and isinstance(body[0], ast.Pass)), f"{path.name}: пустой downgrade"


def test_set_role_only_for_known_roles() -> None:
    assert roles.set_role_sql(roles.APP) == 'SET ROLE "estimator_app"'
    with pytest.raises(ValueError, match="неизвестная роль"):
        roles.set_role_sql("postgres")
