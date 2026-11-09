"""CORE-020 и CR-006 · типы узлов проекта (SPEC FR-TREE-03, GAP-07, NFR-LIM-01; 15.2
``GET/POST /projects/{id}/node-types``).

* Список — активные типы словаря и локальные типы этого проекта (кроме объединённых с типом
  словаря: их узлы уже перепривязаны). Тип словаря, выключенный администратором, тоже входит в
  список с ``is_active = false``, если на него ссылается живой узел проекта: клиенту нужно его
  название в дереве, а в меню «+» он не попадает.
* Локальный тип — название 1–50 символов (пробелы по краям обрезаются, переводы строк
  запрещены) и ключ иконки из курируемого набора; сразу работает только в этом проекте и
  попадает администратору в «Предложенные типы» (``proposal_status = proposed``). Запись — в
  журнал проекта (``project.node_type``).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import NodeTypeProposal
from estimator.db.models.dictionaries import NodeType
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.uuid7 import uuid7
from estimator.services.projects import journal

NAME_MAX = 50


class NodeTypeIcon(StrEnum):
    """Курируемый набор иконок (GAP-07, DESIGN.md 16.3; ``NodeTypeIcon`` контракта): 10 иконок
    типов таблицы 5.2 и 20 дополнительных. Другие ключи сервер не принимает."""

    MODULE = "module"
    FUNCTION = "function"
    SCREEN = "screen"
    INTEGRATION = "integration"
    REPORT = "report"
    ENTITY = "entity"
    SERVICE = "service"
    TEST_SUITE = "test_suite"
    DOCUMENT = "document"
    WORK = "work"
    API = "api"
    CLOUD = "cloud"
    SERVER = "server"
    LOCK = "lock"
    USERS = "users"
    MAIL = "mail"
    BELL = "bell"
    CHART_BAR = "chart_bar"
    FILE_SPREADSHEET = "file_spreadsheet"
    DEVICE_MOBILE = "device_mobile"
    WORLD = "world"
    SEARCH = "search"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    CALENDAR = "calendar"
    CREDIT_CARD = "credit_card"
    SHIELD_CHECK = "shield_check"
    BUG = "bug"
    ROBOT = "robot"
    MAP = "map"


def type_out(row: NodeType) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "icon": row.icon,
        "norms": list(row.norms or []),
        "is_system": row.is_system,
        "is_active": row.is_active,
        "project_id": row.project_id,
    }


async def project_types(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    used = exists().where(
        Node.project_id == project_id, Node.type_id == NodeType.id, Node.deleted_at.is_(None)
    )
    stmt = (
        select(NodeType)
        .where(
            or_(
                and_(NodeType.project_id.is_(None), or_(NodeType.is_active, used)),
                and_(
                    NodeType.project_id == project_id,
                    NodeType.proposal_status != NodeTypeProposal.MERGED,
                ),
            )
        )
        .order_by(NodeType.project_id.is_not(None), NodeType.name, NodeType.id)
    )
    return [type_out(r) for r in (await db.scalars(stmt)).all()]


def _validation(message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": "name", "code": "invalid", "message": message}],
    )


def clean_name(raw: str) -> str:
    name = raw.strip()
    if not name or len(name) > NAME_MAX:
        raise _validation(f"Название — от 1 до {NAME_MAX} символов")
    if "\n" in name or "\r" in name:
        raise _validation("Название — одной строкой")
    return name


async def create_local(
    db: AsyncSession, principal: Principal, project: Project, name: str, icon: NodeTypeIcon
) -> dict[str, Any]:
    row = NodeType(
        id=uuid7(),
        name=clean_name(name),
        icon=icon.value,
        norms=[],
        project_id=project.id,
        proposal_status=NodeTypeProposal.PROPOSED,
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(row)
    journal.record(
        db,
        project.id,
        principal.user_id,
        "project.node_type",
        {"name": (None, row.name), "icon": (None, row.icon)},
    )
    await db.flush()
    await db.refresh(row)
    return type_out(row)
