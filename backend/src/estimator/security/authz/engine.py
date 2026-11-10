"""Движок решений о доступе (SEC-005; SPEC SEC-AUTHZ-01…03, 3.3, 3.4, BR-ROLE-01/04, FR-2FA-05).

Чистые функции без ввода-вывода: на вход — субъект (кто и в каком контексте), право, объект и
статус проекта; на выход — :class:`Access` или :class:`AccessDenied` с кодом из
contracts/errors.yaml. Порядок проверок — contracts/permissions.md, раздел «Алгоритм»:

1. право с ``network`` из чужой сети → 404 (FR-SA-06);
2. объект в проекте, а у пользователя нет членства, режима поддержки и контекста
   руководителя пресейла → 404 (R-OBJECT-CHAIN); проект скрыт статусом (M3.4-01) → 404;
3. права нет ни в одной применимой выдаче → 403 ``FORBIDDEN`` с полем ``permission``;
4. область выдачи не подходит к объекту → 403;
5. роль разрешает, статус проекта запрещает → 409 ``PROJECT_STATUS_CONFLICT``;
6. ``totp_gate`` без пройденного в сессии TOTP → 403 ``TOTP_REQUIRED`` (R-TOTP-GATE);
7. ``step_up`` без свежего step-up → 403 ``STEP_UP_REQUIRED`` (R-STEP-UP).

Выдачи всех ролей суммируются (R-SUM, R-MOD-OVER-EXPERT): право есть, если его даёт хотя бы
одна роль, прошедшая шаги 3–5. Если объект не указан (список, запрос на уровне проекта), а
область выдачи объектная (``own_discipline``, ``author`` …), решение отмечается
``restricted``: эндпоинт обязан сузить выборку или проверить конкретный объект.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from estimator.security.authz.catalog import (
    FILTER_SCOPES,
    OBJECT_SCOPES,
    PSEUDO,
    VISIBILITY_KEY,
    Catalog,
    Grant,
    StatusGate,
)

#: Чем ближе отказ к успеху, тем выше; из нескольких прав «любое из» побеждает самый поздний шаг.
_RANK = {
    "NOT_FOUND": 0,
    "FORBIDDEN": 1,
    "PROJECT_STATUS_CONFLICT": 2,
    "TOTP_REQUIRED": 3,
    "STEP_UP_REQUIRED": 4,
}
_STATUS = {"NOT_FOUND": 404, "PROJECT_STATUS_CONFLICT": 409}


class AccessDenied(Exception):
    """Отказ с кодом из contracts/errors.yaml и полями-расширениями."""

    def __init__(self, code: str, permission: str, **extensions: Any) -> None:
        super().__init__(code)
        self.code = code
        self.permission = permission
        self.extensions = extensions

    @property
    def status(self) -> int:
        return _STATUS.get(self.code, 403)

    @property
    def rank(self) -> int:
        return _RANK[self.code]

    def detail(self) -> dict[str, Any]:
        """Тело ``HTTPException.detail``; поле ``permission`` — только у FORBIDDEN (errors.yaml)."""
        out: dict[str, Any] = {"code": self.code, **self.extensions}
        if self.code == "FORBIDDEN":
            out["permission"] = self.permission
        return out


@dataclass(frozen=True)
class Membership:
    """Строка ``project_members`` пользователя в проекте."""

    role: str  # moderator | expert | presale (ProjectRole)
    discipline_id: uuid.UUID | None = None
    is_reviewer: bool = False

    @property
    def subject(self) -> str:
        if self.role == "moderator":
            return "project_moderator"
        if self.role == "presale":
            return "project_presale"
        return "reviewer" if self.is_reviewer else "expert"


@dataclass(frozen=True)
class Subject:
    """Кто обращается: системные роли, флаги сессии и контексты в проекте объекта."""

    user_id: uuid.UUID
    roles: frozenset[str]
    mfa_passed: bool = False
    step_up_active: bool = False
    network_allowed: bool = True
    memberships: tuple[Membership, ...] = ()
    support: bool = False
    facts: Mapping[str, str] = field(default_factory=dict)

    @property
    def disciplines(self) -> frozenset[uuid.UUID]:
        return frozenset(m.discipline_id for m in self.memberships if m.discipline_id)

    def sources(self, in_project: bool) -> dict[str, str]:
        """Ключи раздела ``grants`` → контекст, в котором субъект их получает."""
        out = {"any_authenticated": "global"}
        if "superadmin" not in self.roles:
            out["user"] = "global"
        out |= dict.fromkeys(self.roles, "global")
        if not in_project:
            return out
        out |= {m.subject: "member" for m in self.memberships}
        if self.support and "admin" in self.roles:
            out["admin"] = "support_session"
        if "presale_head" in self.roles:
            out["presale_head"] = "any_project"
        return out


@dataclass(frozen=True)
class Target:
    """Объект проверки. ``project_id=None`` — системный объект (контекст global)."""

    project_id: uuid.UUID | None = None
    project_status: str | None = None
    disciplines: frozenset[uuid.UUID] | None = None
    author_id: uuid.UUID | None = None
    addressees: frozenset[uuid.UUID] = frozenset()
    kind: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=dict)
    #: Проверка проекта-источника (``branch.copy_from``, M3.4-09): применяются только строки
    #: с ``evaluated_on: source_project``.
    as_source: bool = False


@dataclass(frozen=True)
class Access:
    """Разрешение: каким правом, через какие роли и с какими ограничениями."""

    permission: str
    sources: frozenset[str]
    context: str
    restricted: frozenset[str] = frozenset()
    limits: tuple[Mapping[str, Any], ...] = ()
    project_status: str | None = None
    #: Деньги и заметки в ответе (SEC-AUTHZ-04, R-TOTP-GATE): заполняет :func:`decide_any`.
    money: bool = False
    notes: bool = False

    @property
    def via_presale_head(self) -> bool:
        """Доступ только через контекст any_project (аудит первого открытия, R-PRESALE-HEAD)."""
        return self.context == "any_project"


def _scope_ok(scope: str | None, subject: Subject, target: Target) -> bool | None:
    """True — подходит, False — нет, None — объект не указан (ограничение на эндпоинт)."""
    if scope is None or scope not in OBJECT_SCOPES:
        return True
    if scope == "own_discipline":
        if target.disciplines is None:
            return None
        return bool(target.disciplines) and target.disciplines <= subject.disciplines
    if scope == "author":
        if target.author_id is None:
            return None
        return target.author_id == subject.user_id
    if scope == "author_or_addressee":
        if target.author_id is None:
            return None
        return target.author_id == subject.user_id or subject.user_id in target.addressees
    # documents_only (GAP-06): в корзине — только удалённые документы
    if target.kind is None:
        return None
    return target.kind == "document"


def _condition_ok(condition: str | None, target: Target) -> bool | None:
    if condition is None:
        return True
    if condition == "cq_status_new":
        status = target.attrs.get("cq_status")
        return None if status is None else status == "new"
    return False  # неизвестное условие — запрет (deny by default)


def _grant_applies(grant: Grant, context: str, subject: Subject) -> bool:
    if grant.context not in ("global", context):
        return False
    if grant.unless_role & subject.roles:
        return False
    if grant.requires_system_role and grant.requires_system_role not in subject.roles:
        return False
    if grant.requires_setting:
        key, value = grant.requires_setting
        if subject.facts.get(key) != value:
            return False
    return True


def _gates(catalog: Catalog, code: str, target: Target) -> tuple[StatusGate, ...]:
    gates = catalog.gates_for(code)
    if target.as_source:
        return tuple(g for g in gates if g.evaluated_on == "source_project")
    return tuple(g for g in gates if g.evaluated_on is None)


def project_visible(catalog: Catalog, subject: Subject, status: str) -> bool:
    """Видна ли команде проектная часть (M3.4-01): в «Подготовке» — только модераторам."""
    gate = next(g for g in catalog.gates if g.key == VISIBILITY_KEY)
    return any(
        gate.allows(m.subject, status) for m in subject.memberships if gate.covers(m.subject)
    )


def decide(
    catalog: Catalog, subject: Subject, code: str, target: Target, *, step_up: bool = True
) -> Access:
    """Решение по одному праву. Бросает :class:`AccessDenied`.

    ``step_up=False`` — операция без ``x-step-up`` (чтение списка, проверка без записи): флаг
    ``step_up`` права к ней не применяется (contracts/openapi.yaml задаёт step-up по операции).
    """
    if code in PSEUDO:
        raise ValueError(f"псевдоправо {code!r} проверяют зависимости AUTH, а не движок")
    perm = catalog.permission(code)

    if perm.network and not subject.network_allowed:
        raise AccessDenied("NOT_FOUND", code)

    in_project = target.project_id is not None
    sources = subject.sources(in_project)
    if in_project:
        status = target.project_status
        if status is None:
            raise ValueError("для объекта проекта нужен статус проекта")
        contexts = set(sources.values()) - {"global"}
        if not contexts:
            raise AccessDenied("NOT_FOUND", code)
        if contexts == {"member"} and not project_visible(catalog, subject, status):
            raise AccessDenied("NOT_FOUND", code)

    granted: list[tuple[Grant, str]] = []
    for source, context in sources.items():
        for grant in catalog.grants.get(source, ()):
            if grant.permission == code and _grant_applies(grant, context, subject):
                granted.append((grant, context))
    if not granted:
        raise AccessDenied("FORBIDDEN", code)

    scoped: list[tuple[Grant, str, frozenset[str]]] = []
    for grant, context in granted:
        scope = _scope_ok(grant.scope, subject, target)
        cond = _condition_ok(grant.condition, target)
        if scope is False or cond is False:
            continue
        pending = set()
        if scope is None:
            pending.add(grant.scope or "")
        if cond is None:
            pending.add(f"condition:{grant.condition}")
        if grant.scope in FILTER_SCOPES:
            pending.add(grant.scope)
        scoped.append((grant, context, frozenset(pending)))
    if not scoped:
        raise AccessDenied("FORBIDDEN", code)

    if in_project:
        gates = _gates(catalog, code, target)
        status = target.project_status or ""
        passed = [
            item
            for item in scoped
            if all(g.allows(item[0].source, status) for g in gates if g.covers(item[0].source))
        ]
        if not passed:
            raise AccessDenied("PROJECT_STATUS_CONFLICT", code, project_status=status)
        scoped = passed

    if perm.totp_gate and not subject.mfa_passed:
        raise AccessDenied("TOTP_REQUIRED", code)
    if perm.step_up and step_up and not subject.step_up_active:
        raise AccessDenied("STEP_UP_REQUIRED", code)

    # Без ограничений побеждает: модератор и эксперт одного проекта — права модератора (BR-ROLE-04)
    free = [item for item in scoped if not item[2]]
    chosen = free or scoped
    restricted = frozenset() if free else frozenset().union(*(item[2] for item in scoped))
    contexts_used = {item[1] for item in chosen}
    context = next(c for c in ("member", "support_session", "any_project", "global")
                   if c in contexts_used)  # fmt: skip
    return Access(
        permission=code,
        sources=frozenset(item[0].source for item in chosen),
        context=context,
        restricted=restricted,
        limits=tuple(item[0].limit for item in chosen if item[0].limit),
        project_status=target.project_status,
    )


def _holds(catalog: Catalog, subject: Subject, code: str, target: Target) -> bool:
    try:
        decide(catalog, subject, code, target)
    except AccessDenied:
        return False
    return True


def decide_any(
    catalog: Catalog,
    subject: Subject,
    codes: Collection[str],
    target: Target,
    *,
    step_up: bool = True,
) -> Access:
    """Любое из прав (``x-permission`` списком). Отказ — самый близкий к успеху."""
    if not codes:
        raise ValueError("пустой список прав")
    failures: list[AccessDenied] = []
    for code in codes:
        try:
            access = decide(catalog, subject, code, target, step_up=step_up)
        except AccessDenied as exc:
            failures.append(exc)
            continue
        project = Target(project_id=target.project_id, project_status=target.project_status)
        money = _holds(catalog, subject, "money.read", project)
        notes = _holds(catalog, subject, "notes.read", project)
        return Access(**{**access.__dict__, "money": money, "notes": notes})
    raise max(failures, key=lambda exc: exc.rank)
