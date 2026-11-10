"""Роли по группам AD (AUTH-014; FR-AUTH-AD-07, Q-17, 14.2 ``user_roles.source``).

Сопоставление «группа AD → роль» есть только для «Модератора» и «Пресейла»; роли из нескольких
групп суммируются, вложенные группы учитываются (членство считает каталог). Пока сопоставление
включено, эти две роли у пользователей AD определяются только группами: при входе и ежедневной
синхронизации (AUTH-016) лишние снимаются, недостающие выдаются с ``source = ad_group``, ручная
выдача им запрещена (``admin.users``). Остальные роли (администратор, руководитель пресейла,
аудитор ИБ) группами не выдаются и не трогаются.

Выключение сопоставления оставляет роли как есть, но делает их ручными (``ad_group → manual``).
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.enums import RoleSource, SystemRole, UserSource, UserStatus
from estimator.db.models.users import User, UserRole
from estimator.security import audit

#: Роли, которые выдаются по группам.
MAPPED = frozenset({SystemRole.MODERATOR, SystemRole.PRESALE})


def desired(mappings: Iterable[tuple[str, str]], groups: Collection[str]) -> frozenset[SystemRole]:
    """Роли по группам, в которых состоит пользователь."""
    member = {g.lower() for g in groups}
    return frozenset(SystemRole(role) for dn, role in mappings
                     if dn.lower() in member and SystemRole(role) in MAPPED)  # fmt: skip


@dataclass(frozen=True)
class Change:
    user_id: uuid.UUID
    added: tuple[SystemRole, ...]
    removed: tuple[SystemRole, ...]

    @property
    def empty(self) -> bool:
        return not self.added and not self.removed


async def current(
    db: AsyncSession, user_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, dict[SystemRole, RoleSource]]:
    rows = await db.execute(
        select(UserRole.user_id, UserRole.role, UserRole.source).where(
            UserRole.user_id.in_(user_ids), UserRole.role.in_(MAPPED)
        )
    )
    out: dict[uuid.UUID, dict[SystemRole, RoleSource]] = {uid: {} for uid in user_ids}
    for user_id, role, source in rows.all():
        out[user_id][SystemRole(role)] = RoleSource(source)
    return out


def plan(user_id: uuid.UUID, have: Mapping[SystemRole, RoleSource],
         want: Collection[SystemRole]) -> Change:  # fmt: skip
    added = tuple(sorted(r for r in want if r not in have))
    removed = tuple(sorted(r for r in have if r not in want))
    return Change(user_id, added, removed)


async def apply(
    db: AsyncSession, user: User, want: Collection[SystemRole], *, source: str = "ad_group"
) -> Change:
    """Привести роли «Модератор» и «Пресейл» пользователя к ``want`` (по группам)."""
    have = (await current(db, [user.id]))[user.id]
    change = plan(user.id, have, want)
    keep_manual = [r for r in want if have.get(r) is RoleSource.MANUAL]
    if keep_manual:  # роль осталась, но теперь её задаёт группа
        await db.execute(
            update(UserRole).where(UserRole.user_id == user.id, UserRole.role.in_(keep_manual))
            .values(source=RoleSource.AD_GROUP)
        )  # fmt: skip
    if change.removed:
        await db.execute(
            delete(UserRole).where(UserRole.user_id == user.id, UserRole.role.in_(change.removed))
        )
    for role in change.added:
        db.add(UserRole(user_id=user.id, role=role, source=RoleSource.AD_GROUP))
    await db.flush()
    if not change.empty:
        await audit.write(
            db, "users.roles.changed", user_id=user.id, login=user.login, object_type="user",
            object_id=user.id, actor="system",
            details={"added": [r.value for r in change.added],
                     "removed": [r.value for r in change.removed], "source": source},
        )  # fmt: skip
    return change


async def ad_users(db: AsyncSession) -> list[User]:
    """Действующие пользователи AD (не анонимизированные), по логину."""
    return list((await db.scalars(
        select(User).where(User.source == UserSource.AD, User.status != UserStatus.ANONYMIZED,
                           User.ad_object_guid.is_not(None))
        .order_by(User.login)
    )).all())  # fmt: skip


async def make_manual(db: AsyncSession) -> int:
    """Выключение сопоставления: роли из групп становятся ручными; число строк."""
    result = await db.execute(
        update(UserRole).where(UserRole.source == RoleSource.AD_GROUP)
        .values(source=RoleSource.MANUAL)
    )  # fmt: skip
    return int(result.rowcount or 0)
