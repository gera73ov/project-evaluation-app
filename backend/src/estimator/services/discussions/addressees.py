"""Адресаты сообщений и вопросов (CORE-040; FR-DISC-03, contracts/notifications.yaml).

Адресат — пара ``(target_type, target_id)``: ``user`` и ``discipline`` с идентификатором,
``moderators`` и ``customer`` без него. Для «вопросов мне» пользователь раскрывается в набор
таких пар (:func:`tokens_for`), а адресаты вопроса — в пользователей (:func:`expand`):

* ``@участник`` — он сам; ``@Дисциплина`` — эксперты дисциплины в проекте;
* ``@модератор`` — все модераторы проекта;
* ``@заказчик`` — пресейл проекта, а если пресейла нет — модераторы (толкование
  contracts/notifications.yaml ``question_to_me``).

Адресат по умолчанию (флаг «нужен ответ» без адресатов): узел внутри ветки — эксперты её
дисциплины, фаза и проект — модераторы (FR-DISC-03). Его записывают в ``message_addressees``
явно, поэтому «вопрос мне» не зависит от последующих изменений правила.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.db.enums import AddresseeType, ProjectRole, UserStatus
from estimator.db.models.dictionaries import Discipline
from estimator.db.models.discussions import MessageAddressee
from estimator.db.models.projects import ProjectDiscipline, ProjectMember
from estimator.db.models.tree import Node
from estimator.db.models.users import User

Token = tuple[AddresseeType, uuid.UUID | None]

MODERATORS_LABEL = "модератор"
CUSTOMER_LABEL = "заказчик"
SUGGEST_LIMIT = 20
_WITH_ID = {AddresseeType.USER, AddresseeType.DISCIPLINE}


def invalid(field: str, message: str) -> ApiError:
    return ApiError(
        "VALIDATION_FAILED",
        detail=message,
        errors=[{"field": f"/{field}", "code": "invalid", "message": message}],
    )


@dataclass(frozen=True)
class Team:
    """Состав проекта для адресатов: модераторы, пресейл, эксперты по дисциплинам."""

    moderators: frozenset[uuid.UUID]
    presale: frozenset[uuid.UUID]
    experts: dict[uuid.UUID, frozenset[uuid.UUID]]
    disciplines: frozenset[uuid.UUID]

    @property
    def members(self) -> frozenset[uuid.UUID]:
        users = set(self.moderators) | set(self.presale)
        for ids in self.experts.values():
            users |= ids
        return frozenset(users)

    def tokens(self, user_id: uuid.UUID) -> set[Token]:
        """Адресаты, которые означают этого пользователя («вопрос мне»)."""
        tokens: set[Token] = {(AddresseeType.USER, user_id)}
        tokens |= {
            (AddresseeType.DISCIPLINE, d) for d, ids in self.experts.items() if user_id in ids
        }
        if user_id in self.moderators:
            tokens.add((AddresseeType.MODERATORS, None))
        if user_id in self.presale or (user_id in self.moderators and not self.presale):
            tokens.add((AddresseeType.CUSTOMER, None))
        return tokens

    def expand(self, addressees: Iterable[Token]) -> set[uuid.UUID]:
        """Адресаты → пользователи (получатели «вопрос мне»)."""
        users: set[uuid.UUID] = set()
        for kind, target in addressees:
            if kind is AddresseeType.USER and target is not None:
                users.add(target)
            elif kind is AddresseeType.DISCIPLINE and target is not None:
                users |= self.experts.get(target, frozenset())
            elif kind is AddresseeType.MODERATORS:
                users |= self.moderators
            elif kind is AddresseeType.CUSTOMER:
                users |= self.presale or self.moderators
        return users


async def team(db: AsyncSession, project_id: uuid.UUID) -> Team:
    rows = (
        await db.execute(
            select(ProjectMember.user_id, ProjectMember.role, ProjectMember.discipline_id).where(
                ProjectMember.project_id == project_id
            )
        )
    ).all()
    moderators: set[uuid.UUID] = set()
    presale: set[uuid.UUID] = set()
    experts: dict[uuid.UUID, set[uuid.UUID]] = {}
    for user_id, role, discipline_id in rows:
        if role is ProjectRole.MODERATOR:
            moderators.add(user_id)
        elif role is ProjectRole.PRESALE:
            presale.add(user_id)
        elif discipline_id is not None:
            experts.setdefault(discipline_id, set()).add(user_id)
    disciplines = await db.scalars(
        select(ProjectDiscipline.discipline_id).where(ProjectDiscipline.project_id == project_id)
    )
    return Team(
        moderators=frozenset(moderators),
        presale=frozenset(presale),
        experts={d: frozenset(ids) for d, ids in experts.items()},
        disciplines=frozenset(disciplines),
    )


def default_for(node: Node | None) -> list[Token]:
    """Адресат по умолчанию для вопроса без адресатов (FR-DISC-03)."""
    if node is not None and node.discipline_id is not None:
        return [(AddresseeType.DISCIPLINE, node.discipline_id)]
    return [(AddresseeType.MODERATORS, None)]


def validate(raw: Sequence[tuple[str, uuid.UUID | None]], squad: Team) -> list[Token]:
    """Проверить адресатов запроса: участник проекта, дисциплина проекта; дубли убираются."""
    out: list[Token] = []
    for i, (kind_raw, target) in enumerate(raw):
        kind = AddresseeType(kind_raw)
        field = f"addressees/{i}/target_id"
        if (kind in _WITH_ID) != (target is not None):
            raise invalid(field, "target_id нужен только для участника и дисциплины")
        if kind is AddresseeType.USER and target not in squad.members:
            raise invalid(field, "адресат не участник проекта")
        if kind is AddresseeType.DISCIPLINE and target not in squad.disciplines:
            raise invalid(field, "дисциплины нет в проекте")
        token: Token = (kind, target)
        if token not in out:
            out.append(token)
    return out


def matches(tokens: Iterable[Token]) -> ColumnElement[bool]:
    """Условие на ``message_addressees``: строка — один из адресатов-«мне»."""
    parts: list[ColumnElement[bool]] = []
    for kind, target in tokens:
        cond = MessageAddressee.target_type == kind
        if target is None:
            parts.append(and_(cond, MessageAddressee.target_id.is_(None)))
        else:
            parts.append(and_(cond, MessageAddressee.target_id == target))
    return or_(*parts)


async def suggest(db: AsyncSession, project_id: uuid.UUID, q: str) -> list[dict[str, object]]:
    """Автодополнение ``@``: дисциплины проекта, участники, «модератор», «заказчик» (GAP-02)."""
    needle = q.strip().lstrip("@").strip().lower()
    like = "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    items: list[dict[str, object]] = []
    disciplines = await db.execute(
        select(Discipline.id, Discipline.name)
        .join(ProjectDiscipline, ProjectDiscipline.discipline_id == Discipline.id)
        .where(
            ProjectDiscipline.project_id == project_id,
            or_(
                func.lower(Discipline.name).like(like, escape="\\"),
                func.lower(Discipline.short_name).like(like, escape="\\"),
            ),
        )
        .order_by(Discipline.name)
    )
    items += [
        {"target_type": "discipline", "target_id": str(d), "label": name}
        for d, name in disciplines.all()
    ]
    users = await db.execute(
        select(User.id, User.full_name)
        .where(
            User.id.in_(
                select(ProjectMember.user_id).where(ProjectMember.project_id == project_id)
            ),
            User.status == UserStatus.ACTIVE,
            func.lower(User.full_name).like(like, escape="\\"),
        )
        .order_by(User.full_name, User.id)
        .limit(SUGGEST_LIMIT)
    )
    items += [
        {"target_type": "user", "target_id": str(u), "label": name} for u, name in users.all()
    ]
    for kind, label in (("moderators", MODERATORS_LABEL), ("customer", CUSTOMER_LABEL)):
        if needle in label:
            items.append({"target_type": kind, "target_id": None, "label": label})
    return items[:SUGGEST_LIMIT]
