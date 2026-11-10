"""Правила системных ролей (SEC-017; BR-ROLE-02, BR-ROLE-03, SEC-AUTHZ-06, FR-SA-05, Q-07, G-08).

Правила из contracts/permissions.yaml (R-COMPAT, R-SUPERADMIN-COUNT, R-ROLE-GRANT-LIMITS) в одном
месте, чтобы их применяли все пути изменения ролей: админка пользователей (ADM), раздел
«Суперадминистраторы и администраторы» (ADM, FR-SA-05), консоль (AUTH-011), команда проекта.

* :func:`check_combination` — несовместимые роли: суперадминистратор — ни с какой другой,
  аудитор ИБ — только с «Пользователь» (409 ``ROLE_INCOMPATIBLE``);
* :func:`check_project_member` — суперадминистратор и аудитор ИБ не участвуют в проектах;
* :func:`check_change` — кто какие роли меняет: администратор — «Модератор», «Пресейл»,
  «Руководитель пресейла»; суперадминистратор — «Администратор» и «Аудитор ИБ»; свои роли не
  меняет никто (403 ``FORBIDDEN``); ручная выдача «Модератор» и «Пресейл» пользователю AD при
  включённом сопоставлении групп — 409 ``ROLE_INCOMPATIBLE`` (FR-AUTH-AD-07);
* :func:`ensure_not_last_superadmin`, :func:`ensure_superadmin_slot` — 2–3 активных
  суперадминистратора: последнего нельзя заблокировать, разжаловать или анонимизировать
  (409 ``LAST_SUPERADMIN``), четвёртого нельзя создать (409 ``SUPERADMIN_LIMIT``);
* :func:`needs_second_superadmin` — признак красного баннера «Заведите второго
  суперадминистратора…» (активен только один).

Роль «Суперадминистратор» выдаётся только созданием учётки суперадминистратора (FR-SA-05) и не
меняется через изменение ролей.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.db.enums import SystemRole, UserStatus
from estimator.db.models.users import User, UserRole

MAX_SUPERADMINS = 3  # BR-ROLE-03, Q-07: активных 2–3

#: R-COMPAT: роль → роли, с которыми её нельзя совмещать
INCOMPATIBLE: dict[SystemRole, frozenset[SystemRole]] = {
    SystemRole.SUPERADMIN: frozenset(SystemRole) - {SystemRole.SUPERADMIN},
    SystemRole.SECURITY_AUDITOR: frozenset(SystemRole) - {SystemRole.SECURITY_AUDITOR},
}
#: Роли, с которыми нельзя быть участником проекта (R-COMPAT, project_member)
NO_PROJECTS = frozenset({SystemRole.SUPERADMIN, SystemRole.SECURITY_AUDITOR})
#: R-ROLE-GRANT-LIMITS: какие роли меняет администратор и какие — суперадминистратор
ADMIN_GRANTS = frozenset({SystemRole.MODERATOR, SystemRole.PRESALE, SystemRole.PRESALE_HEAD})
SUPERADMIN_GRANTS = frozenset({SystemRole.ADMIN, SystemRole.SECURITY_AUDITOR})
#: Роли, которые при включённом сопоставлении групп у пользователей AD выдают группы
AD_GROUP_ROLES = frozenset({SystemRole.MODERATOR, SystemRole.PRESALE})

#: «Живые» учётки для предела в три суперадминистратора: активные и ждущие пароль
_COUNTED_FOR_LIMIT = (UserStatus.ACTIVE, UserStatus.PENDING_PASSWORD)


def _roles(values: Iterable[SystemRole | str]) -> frozenset[SystemRole]:
    return frozenset(SystemRole(v) for v in values)


def conflicts(roles: Iterable[SystemRole | str]) -> list[str]:
    """Роли из набора, которые нельзя совмещать между собой; пусто — сочетание допустимо."""
    have = _roles(roles)
    clash: set[SystemRole] = set()
    for role, banned in INCOMPATIBLE.items():
        if role in have and have & banned:
            clash |= {role, *(have & banned)}
    return sorted(r.value for r in clash)


def check_combination(roles: Iterable[SystemRole | str]) -> None:
    """409 ``ROLE_INCOMPATIBLE``, если набор ролей нарушает BR-ROLE-02."""
    clash = conflicts(roles)
    if clash:
        raise ApiError("ROLE_INCOMPATIBLE", conflicting_roles=clash)


def check_project_member(roles: Iterable[SystemRole | str]) -> None:
    """409 ``ROLE_INCOMPATIBLE``: суперадминистратор и аудитор ИБ не назначаются в проекты."""
    clash = sorted(r.value for r in _roles(roles) & NO_PROJECTS)
    if clash:
        raise ApiError("ROLE_INCOMPATIBLE", conflicting_roles=clash)


def check_change(
    *,
    actor_id: uuid.UUID,
    actor_roles: Collection[SystemRole | str],
    target_id: uuid.UUID,
    before: Iterable[SystemRole | str],
    after: Iterable[SystemRole | str],
    ad_mapping_locked: bool = False,
) -> None:
    """Проверить изменение системных ролей ``target`` с ``before`` на ``after``.

    ``ad_mapping_locked`` — пользователь из AD, а сопоставление групп включено: «Модератор» и
    «Пресейл» у него выдают группы (FR-AUTH-AD-07).
    """
    old, new = _roles(before), _roles(after)
    changed = old ^ new
    if not changed:
        return
    if actor_id == target_id:
        raise ApiError("FORBIDDEN", permission="users.roles.grant")  # SEC-AUTHZ-06
    if SystemRole.SUPERADMIN in changed:
        raise ApiError("FORBIDDEN", permission="system.admins.manage")  # только FR-SA-05
    mine = _roles(actor_roles)
    allowed: frozenset[SystemRole] = frozenset()
    if SystemRole.ADMIN in mine:
        allowed |= ADMIN_GRANTS
    if SystemRole.SUPERADMIN in mine:
        allowed |= SUPERADMIN_GRANTS
    if changed - allowed:
        needed = "system.admins.manage" if changed & SUPERADMIN_GRANTS else "users.roles.grant"
        raise ApiError("FORBIDDEN", permission=needed)
    if ad_mapping_locked and changed & AD_GROUP_ROLES:
        raise ApiError(
            "ROLE_INCOMPATIBLE", conflicting_roles=sorted(r.value for r in changed & AD_GROUP_ROLES)
        )
    check_combination(new)


async def superadmin_count(
    db: AsyncSession,
    *,
    statuses: Collection[UserStatus] = (UserStatus.ACTIVE,),
    exclude: uuid.UUID | None = None,
) -> int:
    query = (
        select(func.count())
        .select_from(UserRole)
        .join(User, User.id == UserRole.user_id)
        .where(UserRole.role == SystemRole.SUPERADMIN, User.status.in_(tuple(statuses)))
    )
    if exclude is not None:
        query = query.where(User.id != exclude)
    return int(await db.scalar(query) or 0)


async def ensure_not_last_superadmin(db: AsyncSession, user_id: uuid.UUID) -> None:
    """409 ``LAST_SUPERADMIN``: блокировка, разжалование или анонимизация последнего активного."""
    is_active_super = await db.scalar(
        select(func.count())
        .select_from(UserRole)
        .join(User, User.id == UserRole.user_id)
        .where(
            User.id == user_id,
            UserRole.role == SystemRole.SUPERADMIN,
            User.status == UserStatus.ACTIVE,
        )
    )
    if is_active_super and await superadmin_count(db, exclude=user_id) == 0:
        raise ApiError("LAST_SUPERADMIN")


async def ensure_superadmin_slot(db: AsyncSession) -> None:
    """409 ``SUPERADMIN_LIMIT``: уже три суперадминистратора (активные и ждущие пароль)."""
    if await superadmin_count(db, statuses=_COUNTED_FOR_LIMIT) >= MAX_SUPERADMINS:
        raise ApiError("SUPERADMIN_LIMIT")


async def needs_second_superadmin(db: AsyncSession) -> bool:
    """Активен только один суперадминистратор — красный баннер в админке (BR-ROLE-03)."""
    return await superadmin_count(db) == 1
