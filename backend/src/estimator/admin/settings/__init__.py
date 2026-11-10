"""Системные настройки суперадминистратора (ADM-002; SPEC 3.2, 7.1, FR-AUTH-LOC-02, FR-SESS-02,
FR-LOCK-01..04, FR-2FA-02, FR-SA-04, FR-SA-06, NFR-REL-06, SEC-AUD-04, FR-NOTIF-02, SEC-AUTH-05,
SEC-AUTH-07; 15.2 ``GET/PUT /system/settings/{section}``).

Разделы API и ключи ``system_settings`` (``contracts/settings.schema.json``, ``x-sections``):
``app`` (в контракте — ``system``: адрес и часовой пояс), ``smtp``, ``auth``, ``security``,
``siem``, ``retention``, ``digest``. Раздел ``method`` — «Пороги и проценты» администратора
(``/admin/method-settings``, ADM-007), здесь его нет.

* Чтение отдаёт все ключи раздела: сохранённое значение или значение по умолчанию из контракта.
  Секреты (``x-secret``) не отдаются: вместо них ``{"set": true|false}``.
* Запись — частичная: в ``values`` только меняемые ключи раздела. Каждое значение проверяется по
  контракту; ключи, которые ведёт приложение (``x-owner: system``), записать нельзя. Секрет:
  строка — новое значение (хранится зашифрованным, SEC-CRYPT-03), ``null`` — удалить,
  ``{"set": true}`` — оставить прежний.
* Аудит ``system.settings.changed`` — «было → стало», секрет — ``{"changed": true}``. Раздел
  ``security`` пишет по событию на каждый изменённый ключ (``section`` = ключ), чтобы условия
  оповещений ИБ (сети, отключение обязательного TOTP) срабатывали по ключу; остальные — одним
  событием на раздел. Условия оповещений проверяет сам :func:`audit.write` (SEC-011).
* Смена SMTP: до записи новых значений — письмо ИБ через **старый** сервер
  (:func:`notify.before_smtp_change`); через новый письмо уходит от самого события.
* Раздел ``auth``: способ входа меняет только переход «Приложение → AD» (AUTH-018, здесь — 422),
  параметры AD записывает :func:`estimator.auth.ad_settings.save` — только после проверок
  подключения и входа (409 ``AD_CHECKS_REQUIRED``), с пересчётом ролей по группам (AUTH-015).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin.settings import schema
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.db.models.settings import SystemSetting
from estimator.security import audit
from estimator.security.crypto import get_cipher
from estimator.security.crypto.aead import is_encrypted_setting

#: Раздел API → раздел ``x-sections`` контракта
SECTIONS = {
    "app": "system",
    "smtp": "smtp",
    "auth": "auth",
    "security": "security",
    "siem": "siem",
    "retention": "retention",
    "digest": "digest",
}
KEEP_SECRET = {"set": True}


def section_keys(section: str) -> tuple[str, ...]:
    if section not in SECTIONS:
        raise ApiError("NOT_FOUND")
    return schema.section_keys(SECTIONS[section])


def validation_error(errors: Iterable[tuple[str, str]]) -> ApiError:
    items = [{"field": f"/values{p}", "code": "invalid", "message": m} for p, m in errors]
    return ApiError("VALIDATION_FAILED", detail=items[0]["message"], errors=items)


async def stored(db: AsyncSession, names: Iterable[str]) -> dict[str, Any]:
    """Значения ключей, как они лежат в БД (секреты — зашифрованными); нет ключа — нет в ответе."""
    rows = await db.execute(
        select(SystemSetting.key, SystemSetting.value).where(SystemSetting.key.in_(list(names)))
    )
    return {str(k): v for k, v in rows.all()}


def effective(key: str, raw: Mapping[str, Any]) -> Any:
    return raw[key] if key in raw else schema.default(key)


def public_value(key: str, value: Any) -> Any:
    if schema.is_secret(key):
        return {"set": value is not None}
    return value


async def read_section(db: AsyncSession, section: str) -> dict[str, Any]:
    names = section_keys(section)
    raw = await stored(db, names)
    return {
        "section": section,
        "values": {k: public_value(k, effective(k, raw)) for k in names},
    }


def _cross_checks(key: str, value: Any) -> list[tuple[str, str]]:
    if key == "security.password_policy" and value["min_length"] > value["max_length"]:
        return [(f"/{key}/min_length", "Минимальная длина больше максимальной")]
    if key == "smtp.server" and value.get("host") and not value.get("from_address"):
        return [(f"/{key}/from_address", "Укажите адрес отправителя")]
    if key == "siem.connection" and value.get("enabled") and not value.get("host"):
        return [(f"/{key}/host", "Укажите адрес SIEM")]
    return []


def check_values(names: Iterable[str], values: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Ошибки ``values`` для ключей раздела ``names`` (секрет ``{"set": true}`` — допустим)."""
    allowed = set(names)
    problems: list[tuple[str, str]] = []
    for key, value in values.items():
        if key not in allowed:
            problems.append((f"/{key}", "Ключ не из этого раздела"))
            continue
        if schema.owner(key) == "system":
            problems.append((f"/{key}", "Этот ключ ведёт приложение"))
            continue
        if schema.is_secret(key) and value == KEEP_SECRET:
            continue
        found = schema.errors(schema.key_schema(key), value, f"/{key}")
        problems += found or _cross_checks(key, value)
    return problems


def _same(old: Any, new: Any) -> bool:
    return json.dumps(old, sort_keys=True) == json.dumps(new, sort_keys=True)


def _diff(
    names: Iterable[str], raw: Mapping[str, Any], values: Mapping[str, Any]
) -> dict[str, Any]:
    """Изменённые ключи → новое значение (секрет — открытым текстом или ``None``)."""
    out: dict[str, Any] = {}
    cipher = None
    for key in names:
        if key not in values:
            continue
        new = values[key]
        if schema.is_secret(key):
            if new == KEEP_SECRET:
                continue
            old = raw.get(key)
            if old is None and new is None:
                continue
            if old is not None and new is not None and is_encrypted_setting(old):
                cipher = cipher or get_cipher()
                if cipher.decrypt_setting(key, old) == new:
                    continue
            out[key] = new
        elif not _same(effective(key, raw), new):
            out[key] = new
    return out


def _audit_changes(key: str, raw: Mapping[str, Any], new: Any) -> Any:
    if schema.is_secret(key):
        return {"changed": True}
    return [effective(key, raw), new]


async def _store(db: AsyncSession, actor: Principal, key: str, value: Any) -> None:
    if schema.is_secret(key):
        if value is None:  # удалить секрет: значение по умолчанию — null
            await db.execute(delete(SystemSetting).where(SystemSetting.key == key))
            return
        value = get_cipher().encrypt_setting(key, value)
    await db.merge(SystemSetting(key=key, value=value, updated_by=actor.user_id))


async def apply(
    db: AsyncSession,
    actor: Principal,
    section: str,
    values: Mapping[str, Any],
    *,
    ip: str | None = None,
) -> list[str]:
    """Проверить и записать ``values`` раздела; вернуть изменённые ключи (без проверки прав)."""
    names = section_keys(section)
    problems = check_values(names, values)
    if problems:
        raise validation_error(problems)
    raw = await stored(db, names)
    changed = _diff(names, raw, values)
    if not changed:
        return []
    if section == "auth":
        if "auth.mode" in changed:
            raise validation_error(
                [("/auth.mode", "Способ входа меняет переход на Active Directory")]
            )
        from estimator.auth import ad_settings

        await ad_settings.save(db, actor, values, raw, changed, ip=ip)
        return list(changed)
    if section == "smtp":
        from estimator.security.alerts import notify

        await notify.before_smtp_change(db, actor_login=actor.login, ip=ip)
    for key, value in changed.items():
        await _store(db, actor, key, value)
    await db.flush()
    groups: list[tuple[str, list[str]]]
    if section == "security":
        groups = [(key, [key]) for key in changed]
    else:
        groups = [(section, list(changed))]
    for name, group in groups:
        await audit.write(
            db, "system.settings.changed", user_id=actor.user_id, login=actor.login, ip=ip,
            session_id=actor.session_id, object_type="setting", object_id=group[0],
            details={"section": name,
                     "changes": {k: _audit_changes(k, raw, changed[k]) for k in group}},
        )  # fmt: skip
    return list(changed)


def write_permission(section: str) -> str:
    """Раздел ``auth`` — право ``system.auth.manage``, остальные — ``system.settings.write``."""
    section_keys(section)
    return "system.auth.manage" if section == "auth" else "system.settings.write"
