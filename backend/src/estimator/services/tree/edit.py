"""CORE-015 · создание и изменение узлов (SPEC FR-TREE-01, FR-TREE-02, FR-TREE-20..22,
FR-TREE-31, FR-TREE-32, BR-TREE-05..08, BR-CALC-03, 15.3; ``POST /projects/{id}/nodes``,
``PATCH /nodes/{id}``).

Каждое изменение в одной транзакции: узел, ``node_history``, ``projects.version++`` и
``change_log`` (через :func:`services.common.emit`), при смене статуса ветки — ещё одно событие
``branch.status`` со своей версией. Толкования — agents/journal/DEC-20261109-core-node-edit.md.

* Тип нового узла: явный ``type_id`` (``null`` — «Работа», BR-TREE-08); без поля — по профилю
  ветки (FR-TREE-01). Нормы типа O/R/P не заполняют (FR-TREE-02).
* O/R/P округляются до 0,5 по ROUND_HALF_UP, вне 0–99 999,5 — 422 ``VALUE_OUT_OF_RANGE``;
  O ≤ R ≤ P не проверяется (черновик, FR-TREE-22).
* ``base_version``: поле, изменённое после неё другим пользователем, — 409 ``FIELD_CONFLICT``;
  разные поля не конфликтуют (FR-TREE-32).
* Захват ячейки проверяет ``realtime.locks.iface.assert_not_locked`` (423 ``CELL_LOCKED``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.decimal import format_decimal, parse_decimal
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import NodeAction, NodeKind, NodeTypeProposal
from estimator.db.models.dictionaries import (
    CommentTag,
    DisciplineProfile,
    NodeType,
    Phase,
)
from estimator.db.models.projects import Project, ProjectDiscipline
from estimator.db.models.tree import Node, NodeHistory
from estimator.db.models.users import User
from estimator.db.uuid7 import uuid7
from estimator.realtime.locks import iface as locks
from estimator.services.branches.status import touch
from estimator.services.common import emit, user_ref
from estimator.services.review import marks
from estimator.services.tree.load import DEPTH_LIMIT, NODES_LIMIT, count_live_nodes, node_event
from estimator.services.tree.positions import key_between

TITLE_MAX = 200
COMMENT_LINES_MAX = 10
COMMENT_MAX = 2000  # NFR-LIM-01: комментарий листа
HOURS_MAX = Decimal("99999.5")
HALF = Decimal("0.5")

#: Поле запроса → ключ ``field_versions`` и истории (contracts/db/schema.md 2.4)
FIELD_KEYS: Mapping[str, str] = {
    "title": "title",
    "type_id": "type",
    "o": "o",
    "r": "r",
    "p": "p",
    "multiplier": "multiplier",
    "comment_lines": "comment",
}
ESTIMATE_KEYS = frozenset({"o", "r", "p", "multiplier"})
#: Поля, меняющие цифру: сбрасывают «готово» (BR-BR-02)
RESETS_DONE = ESTIMATE_KEYS


def invalid(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": "invalid", "message": message}],
    )


def clean_title(raw: str, field: str = "title") -> str:
    """BR-TREE-07: пробелы по краям обрезаются, 1–200 символов, без переводов строк."""
    title = raw.strip()
    if not title or len(title) > TITLE_MAX:
        raise invalid(field, f"Название — от 1 до {TITLE_MAX} символов")
    if "\n" in title or "\r" in title:
        raise invalid(field, "Название — одной строкой")
    return title


def round_hours(raw: str, field: str) -> tuple[Decimal, bool]:
    """Часы O/R/P: шаг 0,5 по ROUND_HALF_UP (BR-CALC-03); второе — было ли округление."""
    try:
        value = parse_decimal(raw)
    except ValueError:
        raise invalid(field, "Ожидается число часов") from None
    rounded = (value / HALF).quantize(Decimal(1), rounding=ROUND_HALF_UP) * HALF
    if rounded < 0 or rounded > HOURS_MAX:
        raise ApiError(
            "VALUE_OUT_OF_RANGE",
            detail="Значение должно быть от 0 до 99 999,5",
            field=field,
            min="0",
            max="99999.5",
        )
    return rounded, rounded != value


def _same_hours(a: Decimal | None, b: Decimal | None) -> bool:
    return a == b if a is not None and b is not None else a is b


async def _check_comment(db: AsyncSession, lines: list[dict[str, Any]] | None) -> list[Any] | None:
    """R-03: до 10 строк, у строки своя метка из справочника; всего до 2 000 символов."""
    if not lines:
        return None
    if len(lines) > COMMENT_LINES_MAX:
        raise invalid("comment_lines", f"Не больше {COMMENT_LINES_MAX} строк комментария")
    if sum(len(line["text"]) for line in lines) > COMMENT_MAX:
        raise invalid("comment_lines", f"Комментарий — не больше {COMMENT_MAX} символов")
    tags = {line["tag_id"] for line in lines if line["tag_id"] is not None}
    if tags:
        known = set((await db.scalars(select(CommentTag.id).where(CommentTag.id.in_(tags)))).all())
        if tags - known:
            raise invalid("comment_lines", "Метка не найдена в справочнике")
    return [
        {"tag_id": str(line["tag_id"]) if line["tag_id"] else None, "text": line["text"]}
        for line in lines
    ]


async def work_type(db: AsyncSession) -> uuid.UUID:
    """Тип «Работа» (BR-TREE-08): системный тип словаря."""
    return (await db.scalars(select(NodeType.id).where(NodeType.is_system))).one()


async def _check_type(
    db: AsyncSession, project_id: uuid.UUID, type_id: uuid.UUID, current: uuid.UUID | None = None
) -> uuid.UUID:
    """Тип из списка проекта: активный словаря или локальный этого проекта (FR-TREE-03)."""
    if type_id == current:
        return type_id
    row = await db.get(NodeType, type_id)
    ok = row is not None and (
        (row.project_id is None and row.is_active)
        or (row.project_id == project_id and row.proposal_status is not NodeTypeProposal.MERGED)
    )
    if not ok:
        raise invalid("type_id", "Тип узла не найден в проекте")
    return type_id


async def suggest_type(db: AsyncSession, project_id: uuid.UUID, parent: Node) -> uuid.UUID:
    """FR-TREE-01: у ветки — первый тип цепочки профиля; у родителя с N-м типом цепочки —
    (N+1)-й; иначе — тип родителя; без типа — «Работа»."""
    chain: list[uuid.UUID] = []
    if parent.discipline_id is not None:
        chain = list(
            await db.scalar(
                select(DisciplineProfile.type_chain)
                .join(ProjectDiscipline, ProjectDiscipline.profile_id == DisciplineProfile.id)
                .where(
                    ProjectDiscipline.project_id == project_id,
                    ProjectDiscipline.discipline_id == parent.discipline_id,
                )
            )
            or []
        )
    if parent.kind is NodeKind.DISCIPLINE:
        candidate = chain[0] if chain else None
    elif parent.type_id in chain:
        index = chain.index(parent.type_id)
        candidate = chain[index + 1] if index + 1 < len(chain) else parent.type_id
    else:
        candidate = parent.type_id
    if candidate is not None:
        try:
            return await _check_type(db, project_id, candidate)
        except ApiError:
            pass  # тип цепочки выключен или объединён — «Работа»
    return await work_type(db)


async def has_live_children(db: AsyncSession, node_id: uuid.UUID) -> bool:
    stmt = select(exists().where(Node.parent_id == node_id, Node.deleted_at.is_(None)))
    return bool(await db.scalar(stmt))


async def depth_below_branch(db: AsyncSession, node: Node) -> int:
    """Уровень узла ниже ветки дисциплины: ветка — 0, её ребёнок — 1 (BR-TREE-05)."""
    depth = 0
    current = node
    while current.kind is NodeKind.ITEM and current.parent_id is not None:
        depth += 1
        parent = await db.get(Node, current.parent_id)
        if parent is None:  # pragma: no cover — FK
            break
        current = parent
    return depth


async def live_node(db: AsyncSession, node_id: uuid.UUID) -> Node | None:
    node = await db.get(Node, node_id, populate_existing=True, with_for_update=True)
    if node is None or node.deleted_at is not None:
        return None
    return node


async def _is_cross_cutting(db: AsyncSession, phase_id: uuid.UUID) -> bool:
    return bool(await db.scalar(select(Phase.is_cross_cutting).where(Phase.id == phase_id)))


def history(
    node: Node,
    principal: Principal,
    project_version: int,
    action: NodeAction,
    changes: Mapping[str, tuple[Any, Any]],
) -> NodeHistory:
    def plain(value: Any) -> Any:
        if isinstance(value, Decimal):
            return format_decimal(value)
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    return NodeHistory(
        id=uuid7(),
        node_id=node.id,
        project_id=node.project_id,
        project_version=project_version,
        node_version=node.version,
        user_id=principal.user_id,
        action=action,
        changes={k: [plain(old), plain(new)] for k, (old, new) in changes.items()},
    )


async def place(
    db: AsyncSession,
    parent_id: uuid.UUID,
    after_id: uuid.UUID | None,
    *,
    exclude: uuid.UUID | None = None,
) -> str:
    """Позиция среди живых детей ``parent_id``: сразу за ``after_id``, без него — первой.

    ``exclude`` — сам переносимый узел: его прежнее место не считается соседом.
    """
    siblings = select(Node.position).where(Node.parent_id == parent_id, Node.deleted_at.is_(None))
    if exclude is not None:
        siblings = siblings.where(Node.id != exclude)
    if after_id is None:
        return key_between(None, await db.scalar(siblings.order_by(Node.position).limit(1)))
    before = await db.scalar(siblings.where(Node.id == after_id))
    if before is None:
        raise invalid("after_id", "Соседний узел не найден у этого родителя")
    after = await db.scalar(siblings.where(Node.position > before).order_by(Node.position).limit(1))
    return key_between(before, after)


# --- создание ---------------------------------------------------------------------------------


async def create_node(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    parent: Node,
    body: Mapping[str, Any],
) -> tuple[Node, dict[str, Any] | None, list[str]]:
    """Создать лист под ``parent``; узел, изменение статуса ветки и округлённые поля."""
    if parent.kind is NodeKind.PHASE:
        if await _is_cross_cutting(db, parent.phase_id):
            raise ApiError("CROSS_CUTTING_PHASE_LOCKED")
        raise invalid("parent_id", "Ветки дисциплин добавляются через «Добавить дисциплину»")
    if parent.o is not None or parent.r is not None or parent.p is not None:
        raise invalid("parent_id", "У листа есть оценка: разбейте его (BR-TREE-02)")
    if parent.multiplier != 1:
        raise invalid("parent_id", "У листа задан ×N: разбейте его (BR-TREE-02)")
    if await depth_below_branch(db, parent) + 1 > DEPTH_LIMIT:
        raise ApiError("DEPTH_LIMIT", max_depth=DEPTH_LIMIT)
    current = await count_live_nodes(db, project.id)
    if current + 1 > NODES_LIMIT:
        raise ApiError("NODES_LIMIT", limit=NODES_LIMIT, current=current, requested=1)

    title = clean_title(str(body["title"]))
    if "type_id" not in body:
        type_id = await suggest_type(db, project.id, parent)
    elif body["type_id"] is None:
        type_id = await work_type(db)
    else:
        type_id = await _check_type(db, project.id, body["type_id"])

    rounded: list[str] = []
    hours: dict[str, Decimal | None] = {}
    for key in ("o", "r", "p"):
        raw = body.get(key)
        if raw is None:
            hours[key] = None
            continue
        hours[key], changed = round_hours(raw, key)
        if changed:
            rounded.append(key)
    multiplier = int(body.get("multiplier") or 1)

    position = await place(db, parent.id, body.get("after_id"))

    node = Node(
        id=uuid7(),
        project_id=project.id,
        parent_id=parent.id,
        kind=NodeKind.ITEM,
        phase_id=parent.phase_id,
        discipline_id=parent.discipline_id,
        type_id=type_id,
        title=title,
        position=position,
        o=hours["o"],
        r=hours["r"],
        p=hours["p"],
        multiplier=multiplier,
        comment_lines=None,
        self_review=False,
        version=1,
        field_versions={},
        created_by=principal.user_id,
        updated_by=principal.user_id,
    )
    db.add(node)
    await db.flush()
    author = user_ref(principal.user_id, principal.full_name)
    version = await emit(
        db, project.id, "node.created", {"node": node_event(node), "author": author}
    )
    created: dict[str, tuple[Any, Any]] = {"title": (None, title), "type": (None, type_id)}
    created |= {k: (None, v) for k, v in hours.items() if v is not None}
    if multiplier != 1:
        created["multiplier"] = (1, multiplier)
    db.add(history(node, principal, version, NodeAction.CREATE, created))
    await marks.clear(db, principal, [parent, *await marks.ancestors(db, parent)])
    branch = None
    if node.discipline_id is not None:  # ребёнок ветки всегда в дисциплине (CHECK item_branch)
        branch = await touch(
            db, principal, project.id, node.phase_id, node.discipline_id, resets_done=True
        )
    return node, branch, rounded


# --- изменение --------------------------------------------------------------------------------


async def field_conflicts(
    db: AsyncSession, node: Node, principal: Principal, base_version: int, keys: set[str]
) -> list[dict[str, Any]]:
    """Поля из ``keys``, изменённые после ``base_version`` другим пользователем (FR-TREE-32)."""
    stale = {k for k in keys if int(node.field_versions.get(k, 0)) > base_version}
    if not stale:
        return []
    rows = (
        await db.execute(
            select(NodeHistory, User.full_name)
            .outerjoin(User, User.id == NodeHistory.user_id)
            .where(NodeHistory.node_id == node.id, NodeHistory.node_version > base_version)
            .order_by(NodeHistory.node_version.desc())
        )
    ).all()
    out = []
    for key in sorted(stale):
        last = next(((h, name) for h, name in rows if key in h.changes), None)
        if last is None or last[0].user_id == principal.user_id:
            continue
        entry, name = last
        out.append(
            {
                "field": key,
                "current": entry.changes[key][1],
                "changed_by": name,
                "changed_at": entry.created_at.isoformat().replace("+00:00", "Z"),
            }
        )
    return out


async def patch_node(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    node: Node,
    base_version: int,
    changes: Mapping[str, Any],
) -> tuple[Node, dict[str, Any] | None, list[str]]:
    """Изменить поля узла; узел, изменение статуса ветки и округлённые поля (15.3)."""
    if node.kind is NodeKind.PHASE:
        raise invalid("changes", "Строку фазы не редактируют")
    if node.kind is NodeKind.DISCIPLINE and ({"title", "type_id"} & changes.keys()):
        raise invalid("changes", "Название и тип ветки дисциплины задаёт справочник")
    if ESTIMATE_KEYS & changes.keys() and await has_live_children(db, node.id):
        raise ApiError("NODE_HAS_CHILDREN")

    new: dict[str, Any] = {}
    rounded: list[str] = []
    for field, raw in changes.items():
        if field == "title":
            new["title"] = clean_title(str(raw))
        elif field == "type_id":
            new["type_id"] = (
                await work_type(db)
                if raw is None
                else await _check_type(db, project.id, raw, node.type_id)
            )
        elif field in ("o", "r", "p"):
            if raw is None:
                new[field] = None
            else:
                new[field], changed = round_hours(raw, field)
                if changed:
                    rounded.append(field)
        elif field == "multiplier":
            new["multiplier"] = int(raw)
        elif field == "comment_lines":
            new["comment_lines"] = await _check_comment(db, raw)

    diff: dict[str, tuple[Any, Any]] = {}
    for field, value in new.items():
        old = getattr(node, field)
        same = _same_hours(old, value) if field in ("o", "r", "p") else old == value
        if not same:
            diff[field] = (old, value)
    keys = {FIELD_KEYS[f] for f in diff}
    conflicts = await field_conflicts(db, node, principal, base_version, keys)
    if conflicts:
        raise ApiError("FIELD_CONFLICT", conflicts=conflicts, current_version=node.version)
    for key in sorted(keys & locks.LOCK_FIELDS):
        await locks.assert_not_locked(project.id, node.id, key, user_id=principal.user_id)
    if not diff:
        return node, None, rounded

    resets = bool(RESETS_DONE & diff.keys())
    unreview = resets and node.reviewed_by is not None
    node.version += 1
    versions = dict(node.field_versions)
    for field, (_, value) in diff.items():
        setattr(node, field, value)
        versions[FIELD_KEYS[field]] = node.version
    if unreview:  # FR-REV-02: правка цифры снимает «Проверено» с листа
        node.reviewed_by, node.reviewed_at, node.self_review = None, None, False
        versions["review"] = node.version
        keys.add("review")
    node.field_versions = versions
    node.updated_by = principal.user_id
    await db.flush()
    author = user_ref(principal.user_id, principal.full_name)
    version = await emit(
        db,
        project.id,
        "node.updated",
        {"node": node_event(node), "author": author, "changed_fields": sorted(keys)},
    )
    db.add(
        history(
            node,
            principal,
            version,
            NodeAction.UPDATE,
            {FIELD_KEYS[f]: change for f, change in diff.items()}
            | ({"review": (True, False)} if unreview else {}),
        )
    )
    if resets:  # BR-BR-02: и со всех предков
        await marks.clear(db, principal, await marks.ancestors(db, node))
    branch = None
    if node.discipline_id is not None:
        branch = await touch(
            db,
            principal,
            project.id,
            node.phase_id,
            node.discipline_id,
            resets_done=resets,
        )
    return node, branch, rounded
