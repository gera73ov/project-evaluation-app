"""CORE-012 · команда проекта (SPEC 3.2, BR-ROLE-04..08, FR-PRJ-01, FR-PRJ-04, FR-ADM-05,
BR-ADM-03 / Q-25, BR-PRJ-07; 15.2 ``GET/PUT /projects/{id}/members``,
``POST /projects/{id}/members/{user_id}/replace``).

Строка команды — «пользователь × роль × дисциплина» (эксперт — по дисциплине, несколько
дисциплин — несколько строк; модератор + эксперт — две строки, права модератора, BR-ROLE-04).

* ``PUT`` — полная замена состава. Проверки новых строк: модератор — системная роль «Модератор»
  (руководитель пресейла становится модератором только сам, CORE-071), пресейл — роль «Пресейл»
  и не больше трёх, эксперт — любой незаблокированный пользователь. Уже назначенные строки
  сохраняются без проверки системных ролей (BR-ROLE-08). Суперадминистратор и аудитор ИБ в
  проект не назначаются (409 ``ROLE_INCOMPATIBLE``). Без модератора — 409 ``LAST_MODERATOR``.
* Эксперт на дисциплину, которой нет в проекте, сначала добавляет её (FR-PRJ-04).
* Каждое изменение — аудит ``project.team.changed`` (``added_by_admin_self`` — администратор
  назначил себя, Q-25), журнал проекта и событие ``member.updated`` (по нему RT перепроверяет
  права и отзывает доступ исключённых, BR-ROLE-06).
* «Вас назначили» — модераторам сразу, остальным — сразу, если проект уже не в «Подготовке»
  (иначе при запуске оценки, BR-PRJ-01).
* ``no_moderator_since`` пересчитывается после каждого изменения (BR-PRJ-07).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.enums import ProjectRole, ProjectStatus, SystemRole, UserStatus
from estimator.db.models.projects import Project, ProjectMember
from estimator.db.models.users import User, UserRole
from estimator.notifications import inapp
from estimator.security import audit
from estimator.services.common import emit, user_ref
from estimator.services.projects import disciplines, journal
from estimator.services.projects.lifecycle import notify_assigned

PRESALE_LIMIT = 3  # FR-PRJ-01
_ROLE_ORDER = {ProjectRole.MODERATOR: 0, ProjectRole.PRESALE: 1, ProjectRole.EXPERT: 2}
_INCOMPATIBLE = (SystemRole.SUPERADMIN, SystemRole.SECURITY_AUDITOR)

Key = tuple[uuid.UUID, ProjectRole, uuid.UUID | None]


@dataclass(frozen=True)
class MemberSpec:
    user_id: uuid.UUID
    role: ProjectRole
    discipline_id: uuid.UUID | None = None
    is_reviewer: bool = False

    @property
    def key(self) -> Key:
        return (self.user_id, self.role, self.discipline_id)


def _key(row: ProjectMember) -> Key:
    return (row.user_id, ProjectRole(row.role), row.discipline_id)


def _validation(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": field, "code": "invalid", "message": message}],
    )


async def _rows(db: AsyncSession, project_id: uuid.UUID) -> list[ProjectMember]:
    stmt = select(ProjectMember).where(ProjectMember.project_id == project_id)
    return list((await db.scalars(stmt)).all())


async def _system_roles(
    db: AsyncSession, user_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, set[SystemRole]]:
    ids = set(user_ids)
    roles: dict[uuid.UUID, set[SystemRole]] = {uid: set() for uid in ids}
    rows = await db.execute(
        select(UserRole.user_id, UserRole.role).where(UserRole.user_id.in_(ids))
    )
    for uid, role in rows.all():
        roles[uid].add(SystemRole(role))
    return roles


async def members_out(db: AsyncSession, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Тело ``{"items": Member[]}``: модераторы, пресейл, эксперты; внутри — по ФИО."""
    rows = (
        await db.execute(
            select(ProjectMember, User.full_name, User.status)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
        )
    ).all()
    rows.sort(key=lambda r: (_ROLE_ORDER[ProjectRole(r[0].role)], r[1], str(r[0].discipline_id)))
    out = []
    for member, name, status in rows:
        state = str(status)
        out.append(
            {
                "user": user_ref(member.user_id, name, is_active=state == UserStatus.ACTIVE.value),
                "role": str(member.role),
                "discipline_id": str(member.discipline_id) if member.discipline_id else None,
                "is_reviewer": member.is_reviewer,
                # анонимизированный — тоже «заблокирован» (SEC-PD-03 разрешён только блокированным)
                "status": state if state != UserStatus.ANONYMIZED.value else "blocked",
                "added_by_admin_self": member.added_by_admin_self,
            }
        )
    return out


def _check_shape(specs: Sequence[MemberSpec]) -> None:
    seen: set[Key] = set()
    for i, spec in enumerate(specs):
        field = f"/members/{i}"
        if (spec.role is ProjectRole.EXPERT) != (spec.discipline_id is not None):
            raise _validation(f"{field}/discipline_id", "Дисциплина указывается только у эксперта")
        if spec.is_reviewer and spec.role is not ProjectRole.EXPERT:
            raise _validation(f"{field}/is_reviewer", "Ревьюером может быть только эксперт")
        if spec.key in seen:
            raise ApiError("ALREADY_EXISTS", field="members")
        seen.add(spec.key)


async def _check_new(
    db: AsyncSession, project: Project, specs: Sequence[MemberSpec], kept: set[Key]
) -> None:
    """Проверки пользователей и системных ролей для строк, которых в команде ещё не было."""
    new = [s for s in specs if s.key not in kept]
    if not new:
        return
    ids = {s.user_id for s in new}
    users = {u.id: u for u in (await db.scalars(select(User).where(User.id.in_(ids)))).all()}
    roles = await _system_roles(db, ids)
    for spec in new:
        user = users.get(spec.user_id)
        if user is None:
            raise _validation("/members", "Пользователь не найден")
        if user.status in (UserStatus.BLOCKED, UserStatus.ANONYMIZED):
            raise _validation("/members", "Заблокированного пользователя нельзя назначить")
        clash = sorted(r.value for r in roles[spec.user_id] if r in _INCOMPATIBLE)
        if clash:
            raise ApiError("ROLE_INCOMPATIBLE", conflicting_roles=clash)
        if spec.role is ProjectRole.MODERATOR and SystemRole.MODERATOR not in roles[spec.user_id]:
            raise ApiError("MEMBER_ROLE_REQUIRED", required_role="moderator")
        if spec.role is ProjectRole.PRESALE and SystemRole.PRESALE not in roles[spec.user_id]:
            raise ApiError("MEMBER_ROLE_REQUIRED", required_role="presale")


async def _audit_row(
    db: AsyncSession,
    principal: Principal,
    project_id: uuid.UUID,
    row: ProjectMember,
    op: str,
    via: str,
) -> None:
    await audit.write(
        db,
        "project.team.changed",
        user_id=principal.user_id,
        login=principal.login,
        session_id=principal.session_id,
        object_type="project_member",
        object_id=row.user_id,
        project_id=project_id,
        details={
            "op": op,
            "member_user_id": str(row.user_id),
            "role": str(row.role),
            "discipline_id": str(row.discipline_id) if row.discipline_id else None,
            "is_reviewer": row.is_reviewer,
            "added_by_admin_self": row.added_by_admin_self,
            "via": via,
        },
    )


def _state(row: ProjectMember | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "user_id": str(row.user_id),
        "role": str(row.role),
        "discipline_id": str(row.discipline_id) if row.discipline_id else None,
        "is_reviewer": row.is_reviewer,
    }


def _journal_key(key: Key) -> str:
    user_id, role, discipline_id = key
    return f"{user_id}:{role.value}:{discipline_id or '-'}"


async def refresh_no_moderator(db: AsyncSession, project: Project) -> None:
    """``no_moderator_since``: с какого момента у проекта нет активного модератора (BR-PRJ-07).

    Когда признак появляется, все активные администраторы получают «Проект без модератора».
    """
    active = await db.scalar(
        select(ProjectMember.id)
        .join(User, User.id == ProjectMember.user_id)
        .where(
            ProjectMember.project_id == project.id,
            ProjectMember.role == ProjectRole.MODERATOR,
            User.status == UserStatus.ACTIVE,
        )
        .limit(1)
    )
    if active is not None:
        project.no_moderator_since = None
        return
    if project.no_moderator_since is not None:
        return
    project.no_moderator_since = dt.datetime.now(dt.UTC)
    admins = (
        await db.scalars(select(UserRole.user_id).where(UserRole.role == SystemRole.ADMIN))
    ).all()
    await inapp.notify(
        db,
        "project_without_moderator",
        admins,
        project_id=project.id,
        payload={"project_id": str(project.id)},
    )


async def _announce(
    db: AsyncSession,
    project: Project,
    added: Sequence[uuid.UUID],
    removed: Sequence[uuid.UUID],
    updated: Sequence[uuid.UUID],
) -> int:
    version = project.version
    for change, ids in (("added", added), ("removed", removed), ("updated", updated)):
        if ids:
            version = await emit(
                db,
                project.id,
                "member.updated",
                {"user_ids": sorted({str(i) for i in ids}), "change": change},
            )
    project.version = version
    return version


async def _notify_new(
    db: AsyncSession, principal: Principal, project: Project, rows: Sequence[ProjectMember]
) -> None:
    """«Вас назначили»: модераторам — сразу, остальным — если оценка уже запущена (BR-PRJ-01)."""
    preparation = ProjectStatus(project.status) is ProjectStatus.PREPARATION
    due = [r for r in rows if not preparation or ProjectRole(r.role) is ProjectRole.MODERATOR]
    if due:
        await notify_assigned(db, principal, project.id, list(due))


async def put_members(
    db: AsyncSession, principal: Principal, project: Project, specs: Sequence[MemberSpec]
) -> int:
    """Полная замена состава команды; новая ``project_version`` (прежняя — без изменений)."""
    _check_shape(specs)
    current = {_key(r): r for r in await _rows(db, project.id)}
    wanted = {s.key: s for s in specs}
    if not any(k[1] is ProjectRole.MODERATOR for k in wanted):
        raise ApiError("LAST_MODERATOR")
    await _check_new(db, project, specs, set(current))
    presale = {k[0] for k in wanted if k[1] is ProjectRole.PRESALE}
    if len(presale) > PRESALE_LIMIT:
        raise ApiError("MEMBER_LIMIT", role="presale", limit=PRESALE_LIMIT)

    present = await disciplines.project_discipline_ids(db, project.id)
    for discipline_id in sorted({k[2] for k in wanted if k[2] is not None} - present, key=str):
        await disciplines.add_discipline(db, principal, project, discipline_id)

    admin = SystemRole.ADMIN in principal.roles
    changes: dict[str, tuple[Any, Any]] = {}
    added_rows: list[ProjectMember] = []
    updated: list[ProjectMember] = []
    for key, spec in wanted.items():
        row = current.get(key)
        if row is None:
            row = ProjectMember(
                project_id=project.id,
                user_id=spec.user_id,
                role=spec.role,
                discipline_id=spec.discipline_id,
                is_reviewer=spec.is_reviewer,
                added_by_admin_self=admin and spec.user_id == principal.user_id,
                created_by=principal.user_id,
                updated_by=principal.user_id,
            )
            db.add(row)
            added_rows.append(row)
            changes[_journal_key(key)] = (None, _state(row))
        elif row.is_reviewer != spec.is_reviewer:
            before = _state(row)
            row.is_reviewer = spec.is_reviewer
            row.updated_by = principal.user_id
            updated.append(row)
            changes[_journal_key(key)] = (before, _state(row))
    removed = [row for key, row in current.items() if key not in wanted]
    for row in removed:
        changes[_journal_key(_key(row))] = (_state(row), None)
        await db.delete(row)
    if not changes:
        return project.version
    await db.flush()

    for row in added_rows:
        await _audit_row(db, principal, project.id, row, "added", "team")
    for row in updated:
        await _audit_row(db, principal, project.id, row, "updated", "team")
    for row in removed:
        await _audit_row(db, principal, project.id, row, "removed", "team")
    journal.record(db, project.id, principal.user_id, "project.team", changes)
    await _notify_new(db, principal, project, added_rows)
    await refresh_no_moderator(db, project)
    remaining = {k[0] for k in wanted}
    return await _announce(
        db,
        project,
        added=[r.user_id for r in added_rows],
        removed=[r.user_id for r in removed if r.user_id not in remaining],
        updated=[r.user_id for r in updated]
        + [r.user_id for r in removed if r.user_id in remaining],
    )


async def remove_rows(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    rows: Sequence[ProjectMember],
    *,
    via: str,
) -> int:
    """Снять строки команды (например, экспертов удалённой дисциплины) без проверок состава."""
    changes = {_journal_key(_key(r)): (_state(r), None) for r in rows}
    for row in rows:
        await _audit_row(db, principal, project.id, row, "removed", via)
        await db.delete(row)
    await db.flush()
    journal.record(db, project.id, principal.user_id, "project.team", changes)
    remaining = {r.user_id for r in await _rows(db, project.id)}
    users = {r.user_id for r in rows}
    return await _announce(
        db,
        project,
        added=[],
        removed=sorted(users - remaining),
        updated=sorted(users & remaining),
    )


async def replace_member(
    db: AsyncSession,
    principal: Principal,
    project: Project,
    user_id: uuid.UUID,
    replacement_id: uuid.UUID,
) -> int:
    """Заменить заблокированного участника в проекте (FR-ADM-05, модератором проекта).

    Замена получает те же строки команды (роли, дисциплины, ревьюерство); исходный пользователь
    исключается, авторство его правок не меняется. Переадресацию открытых вопросов подключит
    ADM-012 после CORE-040 (``redirected_threads`` пока 0).
    """
    rows = [r for r in await _rows(db, project.id) if r.user_id == user_id]
    if not rows:
        raise ApiError("NOT_FOUND")
    original = await db.get(User, user_id)
    if original is None or original.status not in (UserStatus.BLOCKED, UserStatus.ANONYMIZED):
        raise _validation("/user_id", "Заменить можно только заблокированного участника")
    if replacement_id == user_id:
        raise _validation("/replacement_user_id", "Замена совпадает с исходным участником")
    replacement = await db.get(User, replacement_id)
    if replacement is None or replacement.status in (UserStatus.BLOCKED, UserStatus.ANONYMIZED):
        raise _validation(
            "/replacement_user_id", "Замена должна быть незаблокированным пользователем"
        )
    roles = (await _system_roles(db, [replacement_id]))[replacement_id]
    if roles & set(_INCOMPATIBLE):
        raise _validation("/replacement_user_id", "Этого пользователя нельзя назначить в проект")
    needed = {ProjectRole(r.role) for r in rows}
    if ProjectRole.MODERATOR in needed and not roles & {
        SystemRole.MODERATOR,
        SystemRole.PRESALE_HEAD,
    }:
        raise ApiError("MEMBER_ROLE_REQUIRED", required_role="moderator")
    if ProjectRole.PRESALE in needed and SystemRole.PRESALE not in roles:
        raise ApiError("MEMBER_ROLE_REQUIRED", required_role="presale")

    existing = {_key(r) for r in await _rows(db, project.id) if r.user_id == replacement_id}
    admin = SystemRole.ADMIN in principal.roles
    changes: dict[str, tuple[Any, Any]] = {}
    added: list[ProjectMember] = []
    for row in rows:
        key = (replacement_id, ProjectRole(row.role), row.discipline_id)
        changes[_journal_key(_key(row))] = (_state(row), None)
        if key not in existing:
            copy = ProjectMember(
                project_id=project.id,
                user_id=replacement_id,
                role=row.role,
                discipline_id=row.discipline_id,
                is_reviewer=row.is_reviewer,
                added_by_admin_self=admin and replacement_id == principal.user_id,
                created_by=principal.user_id,
                updated_by=principal.user_id,
            )
            db.add(copy)
            added.append(copy)
            changes[_journal_key(key)] = (None, _state(copy))
        await db.delete(row)
    await db.flush()
    for row in rows:
        await _audit_row(db, principal, project.id, row, "removed", "replace")
    for row in added:
        await _audit_row(db, principal, project.id, row, "added", "replace")
    journal.record(db, project.id, principal.user_id, "project.team", changes)

    moderators = {
        r.user_id
        for r in await _rows(db, project.id)
        if ProjectRole(r.role) is ProjectRole.MODERATOR
    }
    await inapp.notify(
        db,
        "member_replaced",
        moderators | {replacement_id},
        project_id=project.id,
        payload={
            "project_id": str(project.id),
            "replaced_user_id": str(user_id),
            "replacement_user_id": str(replacement_id),
            "actor_id": str(principal.user_id),
            "redirected_threads": 0,
        },
        actor_id=principal.user_id,
    )
    await refresh_no_moderator(db, project)
    return await _announce(
        db,
        project,
        added=[replacement_id] if added else [],
        removed=[user_id],
        updated=[],
    )


async def candidates(
    db: AsyncSession, q: str, role: ProjectRole | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Кандидаты в команду (CR-005): активные, без суперадминистраторов и аудиторов ИБ.

    ``role=moderator`` — только с системной ролью «Модератор», ``presale`` — «Пресейл». Поиск
    по ФИО без учёта регистра; логин, почта и статус не отдаются.
    """
    excluded = select(UserRole.user_id).where(UserRole.role.in_(_INCOMPATIBLE))
    pattern = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    stmt = select(User.id, User.full_name).where(
        User.status == UserStatus.ACTIVE,
        User.id.not_in(excluded),
        User.full_name.ilike(pattern, escape="\\"),
    )
    required = {
        ProjectRole.MODERATOR: SystemRole.MODERATOR,
        ProjectRole.PRESALE: SystemRole.PRESALE,
    }
    if role in required:
        stmt = stmt.where(
            User.id.in_(select(UserRole.user_id).where(UserRole.role == required[role]))
        )
    rows = (await db.execute(stmt.order_by(User.full_name, User.id).limit(limit))).all()
    roles = await _system_roles(db, [uid for uid, _ in rows])
    return [
        {
            "user": user_ref(uid, name, is_active=True),
            "system_roles": sorted(r.value for r in roles[uid]),
        }
        for uid, name in rows
    ]
