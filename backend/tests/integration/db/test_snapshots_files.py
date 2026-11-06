"""DB-008: неизменяемость снимков, выгрузки, документы заказчика."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from estimator.db.models.files import CustomerDocument, ExportFile, Snapshot
from estimator.db.models.users import User
from tests.integration.db.conftest import as_app
from tests.integration.db.test_tree import tree
from tests.integration.db.test_users_constraints import _rejects

pytestmark = [pytest.mark.integration, pytest.mark.spec("14.2")]

PDF = "application/pdf"


async def _user(session: AsyncSession) -> User:
    user = User(login="s.moderator", full_name="Модератор", status="active")
    session.add(user)
    await session.flush()
    return user


async def _snapshot(session: AsyncSession, project_id, user_id) -> Snapshot:
    snapshot = Snapshot(
        project_id=project_id,
        name="Перед защитой",
        project_version=7,
        created_by=user_id,
        payload={"tree": []},
        money_payload={"currency": "RUB"},
        payload_sha256=hashlib.sha256(b"{}").digest(),
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE snapshots SET payload = '{}'",
        "UPDATE snapshots SET money_payload = NULL",
        "UPDATE snapshots SET name = 'x'",
        "DELETE FROM snapshots",
        "TRUNCATE snapshots",
    ],
    ids=["payload", "money", "name", "delete", "truncate"],
)
@pytest.mark.spec("FR-SNAP-02")
async def test_snapshot_is_immutable_for_app(db_session: AsyncSession, statement: str) -> None:
    user = await _user(db_session)
    await as_app(db_session)
    project, _, _ = await tree(db_session)
    await _snapshot(db_session, project.id, user.id)
    with pytest.raises(DBAPIError, match="permission denied"):
        async with db_session.begin_nested():
            await db_session.execute(text(statement))


@pytest.mark.spec("FR-SNAP-02")
async def test_app_marks_snapshot_invalid(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    await as_app(db_session)
    project, _, _ = await tree(db_session)
    snapshot = await _snapshot(db_session, project.id, user.id)
    snapshot.is_invalid = True
    snapshot.invalidated_by = user.id
    snapshot.invalidated_at = func.now()
    await db_session.flush()
    assert await db_session.scalar(select(Snapshot.is_invalid)) is True


@pytest.mark.spec("SEC-AUTHZ-04")
async def test_money_payload_not_loaded_by_default(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    snapshot = await _snapshot(db_session, project.id, user.id)
    db_session.expunge_all()
    loaded = await db_session.get(Snapshot, snapshot.id)
    with pytest.raises(Exception, match="raiseload"):
        _ = loaded.money_payload
    db_session.expunge_all()
    rows = await db_session.scalars(select(Snapshot).options(undefer(Snapshot.money_payload)))
    assert rows.one().money_payload == {"currency": "RUB"}


@pytest.mark.spec("BR-PRJ-04")
async def test_project_delete_cascades_as_app(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    await as_app(db_session)
    project, _, _ = await tree(db_session)
    snapshot = await _snapshot(db_session, project.id, user.id)
    now = dt.datetime.now(dt.UTC)
    db_session.add_all(
        [
            ExportFile(
                user_id=user.id,
                project_id=project.id,
                snapshot_id=snapshot.id,
                kind="xlsx.tree",
                expires_at=now + dt.timedelta(hours=24),
            ),
            CustomerDocument(
                project_id=project.id,
                file_name="ТЗ.pdf",
                mime=PDF,
                size_bytes=1024,
                storage_key=uuid.uuid4(),
                key_enc=b"\x01" * 60,
                uploaded_by=user.id,
            ),
        ]
    )
    await db_session.flush()
    await db_session.delete(project)
    await db_session.flush()
    for model in (Snapshot, ExportFile, CustomerDocument):
        count = await db_session.scalar(select(func.count()).select_from(model))
        assert count == 0, model.__tablename__


@pytest.mark.spec("FR-DOC-01")
@pytest.mark.parametrize(
    "kwargs",
    [
        {"mime": "text/html"},  # SEC-WEB-10
        {"size_bytes": 0},
        {"size_bytes": 52428801},  # 50 МБ
    ],
    ids=["mime", "empty", "too-big"],
)
async def test_document_checks(db_session: AsyncSession, kwargs: dict) -> None:
    user = await _user(db_session)
    project, _, _ = await tree(db_session)
    fields = {
        "project_id": project.id,
        "file_name": "ТЗ.pdf",
        "mime": PDF,
        "size_bytes": 1024,
        "storage_key": uuid.uuid4(),
        "key_enc": b"\x01",
        "uploaded_by": user.id,
        **kwargs,
    }
    await _rejects(db_session, CustomerDocument(**fields))
