"""Каталог прав из ``contracts/permissions.yaml`` (SEC-001) в виде, удобном движку SEC-005.

Файл — источник правды: права в коде — только строки из каталога (permissions.md).
В образе ``api`` файл кладётся рядом с модулем (deploy/docker/api.Dockerfile); в рабочей копии
и тестах читается прямо из ``contracts/``.

Загрузка проверяет инварианты, на которые опирается движок, и падает при нарушении:

* денежные права (``totp_gate`` и ``export.money``) выдаются только ``project_moderator``,
  ``project_presale`` и ``presale_head`` (R-SUM, BR-ADM-03);
* контекст ``support_session`` даёт только права ``read_only`` без денег (R-SUPPORT);
* каждое право выдачи и строки статусов есть в каталоге.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

FILE_NAME = "permissions.yaml"
ENV_PATH = "ESTIMATOR_PERMISSIONS_FILE"

#: Псевдоправа: эндпоинты без роли тоже объявляют право (TC-SEC-01); проверяют их зависимости AUTH.
PSEUDO = frozenset(
    {"public", "token.login_step", "token.activation", "session.pre_mfa", "authenticated"}
)
STATUSES = ("preparation", "estimation", "consolidation", "completed", "archived")
CONTEXTS = frozenset({"global", "member", "support_session", "any_project"})
#: Области, которые проверяются на объекте; без объекта решение «с ограничением».
OBJECT_SCOPES = frozenset({"own_discipline", "author", "author_or_addressee", "documents_only"})
#: Области, которые сужает сам эндпоинт (фильтр выборки), а не движок.
FILTER_SCOPES = frozenset({"admin_audit_categories"})
#: Кто может выдавать денежные права (R-SUM).
MONEY_SOURCES = frozenset({"project_moderator", "project_presale", "presale_head"})
#: Проектные роли (ключи grants), которые дают контекст ``member``.
PROJECT_ROLES = ("project_moderator", "expert", "reviewer", "project_presale")
#: Строка 3.4, задающая видимость проекта: её запрет — 404, а не 409 (SEC-AUTHZ-03, M3.4-01).
VISIBILITY_KEY = "project.visibility"


class CatalogError(RuntimeError):
    """Файл прав не соответствует инвариантам движка."""


@dataclass(frozen=True)
class Permission:
    code: str
    title: str
    totp_gate: bool = False
    step_up: bool = False
    network: bool = False
    money_fields: bool = False
    read_only: bool = False

    @property
    def is_money(self) -> bool:
        return self.totp_gate or self.code == "export.money"


@dataclass(frozen=True)
class Grant:
    """Выдача права субъекту (раздел 3 файла)."""

    source: str
    permission: str
    context: str = "global"
    scope: str | None = None
    condition: str | None = None
    unless_role: frozenset[str] = frozenset()
    requires_system_role: str | None = None
    requires_setting: tuple[str, str] | None = None
    limit: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StatusCell:
    effect: str
    subjects: frozenset[str] | None = None
    scope: str | None = None


@dataclass(frozen=True)
class StatusGate:
    """Ограничение права по статусу проекта: строка matrix_3_4 или derived_status_gates."""

    id: str
    key: str
    permissions: frozenset[str]
    applies_to: frozenset[str]
    statuses: Mapping[str, StatusCell]
    evaluated_on: str | None = None

    def covers(self, subject: str) -> bool:
        return subject in self.applies_to

    def allows(self, subject: str, status: str) -> bool:
        cell = self.statuses[status]
        if cell.effect != "allow":
            return False
        return cell.subjects is None or subject in cell.subjects


@dataclass(frozen=True)
class Catalog:
    version: str
    permissions: Mapping[str, Permission]
    grants: Mapping[str, tuple[Grant, ...]]
    gates: tuple[StatusGate, ...]
    groups: Mapping[str, frozenset[str]]

    def permission(self, code: str) -> Permission:
        try:
            return self.permissions[code]
        except KeyError:
            raise KeyError(f"право {code!r} отсутствует в contracts/permissions.yaml") from None

    def gates_for(self, code: str) -> tuple[StatusGate, ...]:
        return tuple(g for g in self.gates if code in g.permissions)

    def required_settings(self, codes: tuple[str, ...]) -> frozenset[str]:
        keys = {
            g.requires_setting[0]
            for grants in self.grants.values()
            for g in grants
            if g.permission in codes and g.requires_setting is not None
        }
        return frozenset(keys)


def _path() -> Path:
    override = os.environ.get(ENV_PATH)
    if override:
        return Path(override)
    packaged = Path(__file__).with_name(FILE_NAME)
    if packaged.is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / FILE_NAME
        if candidate.is_file():
            return candidate
    raise CatalogError(f"не найден {FILE_NAME}: ни рядом с модулем, ни в contracts/")


def _setting(raw: str | None) -> tuple[str, str] | None:
    if raw is None:
        return None
    key, _, value = raw.partition("=")
    if not value:
        raise CatalogError(f"requires_setting без значения: {raw!r}")
    return key.strip(), value.strip()


def _grants(raw: Mapping[str, list[dict[str, Any]]], key: str) -> tuple[Grant, ...]:
    out: list[Grant] = []
    for item in raw[key]:
        if "inherit" in item:
            out += [Grant(**{**g.__dict__, "source": key}) for g in _grants(raw, item["inherit"])]
            continue
        out.append(
            Grant(
                source=key,
                permission=item["permission"],
                context=item.get("context", "global"),
                scope=item.get("scope"),
                condition=item.get("condition"),
                unless_role=frozenset(item.get("unless_role", ())),
                requires_system_role=item.get("requires_system_role"),
                requires_setting=_setting(item.get("requires_setting")),
                limit=dict(item.get("limit") or {}),
            )
        )
    return tuple(out)


def _cells(raw: Mapping[str, Any], groups: Mapping[str, frozenset[str]]) -> dict[str, StatusCell]:
    def expand(names: list[str] | None) -> frozenset[str] | None:
        if names is None:
            return None
        return frozenset(n for name in names for n in groups.get(name, {name}))

    return {
        st: StatusCell(
            effect=raw[st]["effect"],
            subjects=expand(raw[st].get("subjects")),
            scope=raw[st].get("scope"),
        )
        for st in STATUSES
    }


def parse(data: Mapping[str, Any]) -> Catalog:
    groups = {k: frozenset(v) for k, v in data["subject_groups"].items()}
    perms = {
        code: Permission(
            code=code,
            title=p["title"],
            totp_gate=bool(p.get("totp_gate")),
            step_up=bool(p.get("step_up")),
            network=bool(p.get("network")),
            money_fields=bool(p.get("money_fields")),
            read_only=bool(p.get("read_only")),
        )
        for code, p in data["permissions"].items()
    }
    grants = {key: _grants(data["grants"], key) for key in data["grants"]}

    gates: list[StatusGate] = []
    for row in data["matrix_3_4"]:
        if "permissions" not in row:  # строки об уведомлениях — их применяет NTF
            continue
        applies = frozenset(n for name in row["applies_to"] for n in groups.get(name, {name}))
        gates.append(
            StatusGate(
                id=row["id"],
                key=row["key"],
                permissions=frozenset(row["permissions"]),
                applies_to=applies,
                statuses=_cells(row["statuses"], groups),
                evaluated_on=row.get("evaluated_on"),
            )
        )
    for row in data["derived_status_gates"]:
        if "statuses" not in row:  # D-04: переходы статуса проверяет CORE
            continue
        effects = {st: {"effect": eff} for st, eff in row["statuses"].items()}
        gates.append(
            StatusGate(
                id=row["id"],
                key=row["id"],
                permissions=frozenset(row["permissions"]),
                applies_to=groups["project_member"],
                statuses=_cells(effects, groups),
            )
        )
    catalog = Catalog(str(data["version"]), perms, grants, tuple(gates), groups)
    _validate(catalog)
    return catalog


def _validate(catalog: Catalog) -> None:
    problems: list[str] = []
    for source, grants in catalog.grants.items():
        for g in grants:
            perm = catalog.permissions.get(g.permission)
            if perm is None:
                problems.append(f"{source}: неизвестное право {g.permission}")
                continue
            if g.context not in CONTEXTS:
                problems.append(f"{source}: неизвестный контекст {g.context}")
            if perm.is_money and source not in MONEY_SOURCES:
                problems.append(f"{source}: денежное право {g.permission} (R-SUM)")
            if g.context == "support_session" and (not perm.read_only or perm.is_money):
                problems.append(f"{source}: {g.permission} в режиме поддержки (R-SUPPORT)")
            if g.context == "member" and source not in PROJECT_ROLES:
                problems.append(f"{source}: контекст member у системной роли")
    for gate in catalog.gates:
        problems += [
            f"{gate.id}: неизвестное право {p}"
            for p in sorted(gate.permissions)
            if p not in catalog.permissions
        ]
    if problems:
        raise CatalogError("; ".join(problems))


@cache
def load_catalog() -> Catalog:
    """Каталог процесса (читается один раз)."""
    with _path().open(encoding="utf-8") as fh:
        return parse(yaml.safe_load(fh))
