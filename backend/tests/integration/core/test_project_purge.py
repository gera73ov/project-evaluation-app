"""CORE-090: ``estimator project purge`` — физическое удаление проекта по заявке, согласованной с
ИБ: состав (dry-run), удаление каскадом, файлы с томов, аудит остаётся (BR-PRJ-04, GAP-12)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

import estimator.cli as cli
from estimator.db.models.files import CustomerDocument
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node, NodeHistory
from estimator.documents import storage
from estimator.services.projects import purge
from tests.integration.core.test_documents_api import PDF, _upload
from tests.integration.core.test_nodes_api import _setup
from tests.integration.core.test_structure_api import _leaf

pytestmark = [pytest.mark.integration, pytest.mark.spec("BR-PRJ-04"), pytest.mark.spec("GAP-12")]


async def _purged(db: AsyncSession, pid: uuid.UUID) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT details FROM audit.audit_log WHERE event_type = 'project.purged' "
            "AND object_id = :p ORDER BY id"
        ),
        {"p": str(pid)},
    )
    return [r[0] for r in rows]


async def test_dry_run_then_purge(world: Any, db_session: AsyncSession) -> None:
    s = await _setup(world, db_session)
    branch = await s.branch(db_session, s.backend)
    await _leaf(s.backend_expert, s, branch.id, "Вход", o="1", r="2", p="3")
    made = await _upload(s.moderator, s.pid, "ТЗ.pdf", PDF)
    assert made.status_code == 201, made.text
    doc = await db_session.get(CustomerDocument, uuid.UUID(made.json()["id"]))
    assert doc is not None
    file = storage.path_of(doc.storage_key)
    assert file.exists()

    dry = await purge.purge(
        db_session, s.pid, ticket="ИБ-2026-17", approved_by="ib.petrova",
        dry_run=True, os_user="ops",
    )  # fmt: skip
    assert dry.composition.nodes >= 2
    assert dry.composition.documents == 1
    assert await db_session.get(Project, s.pid) is not None

    done = await purge.purge(
        db_session, s.pid, ticket="ИБ-2026-17", approved_by="ib.petrova",
        dry_run=False, os_user="ops",
    )  # fmt: skip
    db_session.expunge_all()
    assert await db_session.get(Project, s.pid) is None
    for model in (Node, NodeHistory, CustomerDocument):
        left = await db_session.scalar(
            select(func.count()).select_from(model).where(model.project_id == s.pid)
        )
        assert left == 0, model.__tablename__
    assert purge.remove_files(done) == 1
    assert not file.exists()

    first, second = await _purged(db_session, s.pid)
    assert (first["dry_run"], second["dry_run"]) == (True, False)
    assert second["ticket"] == "ИБ-2026-17"
    assert second["approved_by_login"] == "ib.petrova"
    assert second["composition"]["documents"] == 1
    assert second["os_user"] == "ops"
    # записи аудита о проекте остаются
    kept = await db_session.scalar(
        text("SELECT count(*) FROM audit.audit_log WHERE details->>'project_id' = :p"),
        {"p": str(s.pid)},
    )
    assert kept >= 2


async def test_refusals(db_session: AsyncSession) -> None:
    with pytest.raises(purge.PurgeError, match="не найден"):
        await purge.purge(
            db_session, uuid.uuid4(), ticket="1", approved_by="ib", dry_run=True, os_user="o"
        )
    for ticket, approved in (("  ", "ib"), ("1", ""), ("x" * 101, "ib")):
        with pytest.raises(purge.PurgeError):
            await purge.purge(
                db_session, uuid.uuid4(), ticket=ticket, approved_by=approved,
                dry_run=True, os_user="o",
            )  # fmt: skip


def test_cli_asks_for_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без верного id в подтверждении удаления нет; dry-run только показывает состав."""
    calls: list[bool] = []
    pid = uuid.uuid4()

    async def fake(_db: object, project_id: uuid.UUID, **kw: Any) -> purge.PurgePlan:
        calls.append(kw["dry_run"])
        return purge.PurgePlan(project_id, "Портал", purge.Composition(nodes=5))

    class FakeTx:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *exc: object) -> None:
            return None

    async def dispose() -> None:
        return None

    monkeypatch.setattr("estimator.db.session.transaction", lambda: FakeTx())
    monkeypatch.setattr("estimator.db.session.dispose_engine", dispose)
    monkeypatch.setattr(purge, "purge", fake)
    cli.load_commands()
    runner = CliRunner()
    args = ["project", "purge", str(pid), "--ticket", "T-1", "--approved-by", "ib"]

    shown = runner.invoke(cli.app, [*args, "--dry-run"])
    assert shown.exit_code == 0, shown.output
    assert "узлов дерева: 5" in shown.output
    assert calls == [True]

    wrong = runner.invoke(cli.app, args, input="не тот\n")
    assert wrong.exit_code == 1
    assert calls == [True, True]

    ok = runner.invoke(cli.app, args, input=f"{pid}\n")
    assert ok.exit_code == 0, ok.output
    assert calls == [True, True, True, False]
    assert "удалён" in ok.output
