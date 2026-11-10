"""Настройки AD: проверки и сохранение (AUTH-015; FR-AUTH-AD-03, -04, -07, 11.2 №3–6, SEC-AUTH-05,
SEC-AUTH-07; ``POST /system/auth/ad/test-connection``, ``/test-login``,
``/system/auth/role-mapping/preview``, ``PUT /system/settings/auth``).

* «Проверить подключение» — bind сервисной учёткой и поиск в Base DN, время ответа.
* «Проверить вход» — тестовые логин и пароль: найденные ФИО, email, отключена ли запись, группы,
  итоговые роли. Пароль не сохраняется и не пишется в лог.
* Обе проверки берут несохранённые значения формы (``values``) поверх сохранённых. Сохранённый
  пароль сервисной учётки подставляется, только если контроллеры и учётка bind не менялись.
* Успешная проверка записывает в ``auth.ad.verification`` отпечаток проверенных параметров
  (:func:`ldap.fingerprint`) и время. Параметры подключения, пароль и группы доступа сохраняются,
  только если обе проверки прошли с тем же отпечатком, иначе 409 ``AD_CHECKS_REQUIRED``
  (``missing``: ``connection``, ``login``).
* Сопоставление групп с ролями: перед включением — отчёт (:func:`preview`), при сохранении —
  немедленный пересчёт ролей пользователей AD и отчёт в аудит (``users.ad_role_mapping.report``);
  выключение делает роли из групп ручными.
* Изменение — ``system.ad_settings.changed`` (оповещение ИБ всегда); пароль и сертификат —
  ``{"changed": true}``.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth import ad_roles
from estimator.auth.context import Principal
from estimator.auth.providers import ldap
from estimator.auth.providers.ldap import (
    ACCESS_GROUPS,
    BIND_PASSWORD,
    CONNECTION,
    ROLE_MAPPING,
    AdConfig,
    AdConfigError,
    AdUnavailableError,
)
from estimator.db.enums import SystemRole
from estimator.db.models.settings import SystemSetting
from estimator.logging import get_logger
from estimator.security import audit

log = get_logger(__name__)

VERIFICATION = "auth.ad.verification"
#: Ключи, после изменения которых нужны обе проверки.
CHECKED = (CONNECTION, BIND_PASSWORD, ACCESS_GROUPS)
KEEP = {"set": True}

REASON_TEXT = {
    "user_not_found": "Пользователь не найден в AD",
    "ad_ambiguous": "По логину найдено несколько записей",
    "wrong_password": "Неверный пароль",  # nosec B105 — текст ответа, не пароль
    "ad_account_disabled": "Учётная запись в AD отключена",
    "ad_not_in_group": "Пользователь не состоит в группе доступа",
}


def _check(values: Mapping[str, Any]) -> None:
    from estimator.admin import settings

    names = (CONNECTION, BIND_PASSWORD, ACCESS_GROUPS, ROLE_MAPPING)
    problems = settings.check_values(names, values)
    if problems:
        raise settings.validation_error(problems)


def _target(values: Mapping[str, Any]) -> tuple[Any, Any]:
    conn = values.get(CONNECTION) or {}
    hosts = [(c.get("host"), c.get("port")) for c in conn.get("controllers") or []]
    return hosts, conn.get("bind_dn")


async def candidate(
    db: AsyncSession, values: Mapping[str, Any]
) -> tuple[dict[str, Any], str | None]:
    """Значения формы поверх сохранённых и пароль сервисной учётки для проверки."""
    saved, saved_password = await ldap.stored_values(db)
    merged = {**saved, **{k: v for k, v in values.items() if k in (CONNECTION, ACCESS_GROUPS,
                                                                    ROLE_MAPPING)}}  # fmt: skip
    given = values.get(BIND_PASSWORD, KEEP)
    if isinstance(given, str):
        return merged, given
    if given is None:
        return merged, None
    return merged, saved_password if _target(saved) == _target(merged) else None


async def verification(db: AsyncSession) -> dict[str, Any]:
    from estimator.admin.settings import schema
    from estimator.auth.policy import read_settings

    raw = (await read_settings(db, VERIFICATION)).get(VERIFICATION)
    return dict(raw or schema.default(VERIFICATION))


async def _mark(db: AsyncSession, actor: Principal, fp: str, check: str) -> None:
    current = await verification(db)
    if current.get("params_sha256") != fp:
        current = {"params_sha256": fp, "connection_ok_at": None, "login_ok_at": None}
    current[f"{check}_ok_at"] = dt.datetime.now(dt.UTC).isoformat()
    await db.merge(SystemSetting(key=VERIFICATION, value=current, updated_by=actor.user_id))
    await db.flush()


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def test_connection(db: AsyncSession, actor: Principal,
                          values: Mapping[str, Any]) -> dict[str, Any]:  # fmt: skip
    _check(values)
    merged, password = await candidate(db, values)
    started = time.monotonic()
    try:
        config = AdConfig.from_values(merged, password)
        await ldap.directory(config).ping()
    except AdConfigError as exc:
        return {"ok": False, "elapsed_ms": _ms(started), "detail": f"Не заданы параметры: {exc}",
                "user": None}  # fmt: skip
    except AdUnavailableError as exc:
        return {"ok": False, "elapsed_ms": _ms(started),
                "detail": f"Не удалось подключиться к AD: {exc}", "user": None}  # fmt: skip
    elapsed = _ms(started)
    await _mark(db, actor, ldap.fingerprint(merged, password), "connection")
    return {"ok": True, "elapsed_ms": elapsed, "detail": None, "user": None}


async def _app_roles(db: AsyncSession, guid: uuid.UUID) -> set[SystemRole]:
    from estimator.auth import ad_provisioning
    from estimator.auth.login import user_roles

    user = await ad_provisioning.by_guid(db, guid)
    return set(await user_roles(db, user.id)) if user is not None else set()


async def test_login(db: AsyncSession, actor: Principal, values: Mapping[str, Any],
                     login: str, password: str) -> dict[str, Any]:  # fmt: skip
    _check(values)
    merged, bind_password = await candidate(db, values)
    started = time.monotonic()
    try:
        config = AdConfig.from_values(merged, bind_password)
        verdict = await ldap.verify(ldap.directory(config), config, login.strip(), password)
    except AdConfigError as exc:
        return {"ok": False, "elapsed_ms": _ms(started), "detail": f"Не заданы параметры: {exc}",
                "user": None}  # fmt: skip
    except AdUnavailableError as exc:
        return {"ok": False, "elapsed_ms": _ms(started),
                "detail": f"Не удалось подключиться к AD: {exc}", "user": None}  # fmt: skip
    elapsed = _ms(started)
    user = None
    entry = verdict.entry
    if entry is not None and verdict.reason != "wrong_password":
        roles = await _app_roles(db, entry.object_guid)
        if config.mapping_enabled:
            roles = (roles - ad_roles.MAPPED) | ad_roles.desired(config.mappings, verdict.groups)
        user = {
            "full_name": entry.full_name, "email": entry.email, "disabled": entry.disabled,
            "groups": sorted(verdict.groups),
            "roles": sorted(r.value for r in roles),
            "in_access_group": bool(verdict.groups.intersection(config.access_groups)),
        }  # fmt: skip
    ok = verdict.reason is None
    if ok:
        await _mark(db, actor, ldap.fingerprint(merged, bind_password), "login")
    return {"ok": ok, "elapsed_ms": elapsed, "detail": REASON_TEXT.get(verdict.reason or ""),
            "user": user}  # fmt: skip


# --- сопоставление групп с ролями ---------------------------------------------------------------


async def _changes(
    db: AsyncSession, config: AdConfig
) -> list[tuple[Any, frozenset[SystemRole], ad_roles.Change]]:
    """Изменения ролей пользователей AD по сопоставлению ``config`` (AD недоступен — исключение)."""
    if not config.mapping_enabled:
        return []
    directory = ldap.directory(config)
    groups = tuple(dict.fromkeys(dn for dn, _ in config.mappings))
    users = await ad_roles.ad_users(db)
    have = await ad_roles.current(db, [u.id for u in users])
    out = []
    for user in users:
        if user.ad_object_guid is None:  # отобрано ad_users, проверка для типов
            continue
        entry = await directory.by_guid(user.ad_object_guid)
        if entry is None:
            continue
        want = ad_roles.desired(config.mappings, await directory.groups_of(entry.dn, groups))
        out.append((user, want, ad_roles.plan(user.id, have[user.id], want)))
    return out


async def preview(db: AsyncSession, mapping: Mapping[str, Any]) -> dict[str, Any]:
    from estimator.services.common import user_ref

    _check({ROLE_MAPPING: mapping})
    saved, password = await ldap.stored_values(db)
    try:
        config = AdConfig.from_values({**saved, ROLE_MAPPING: mapping}, password)
        changes = await _changes(db, config)
    except (AdConfigError, AdUnavailableError):
        raise ApiError("AUTH_SERVICE_UNAVAILABLE") from None
    items = [
        {"user": user_ref(user.id, user.full_name), "login": user.login,
         "removed": [r.value for r in change.removed], "added": [r.value for r in change.added]}
        for user, _want, change in changes if not change.empty
    ]  # fmt: skip
    return {"items": sorted(items, key=lambda i: str(i["login"]).lower())}


async def recalculate(db: AsyncSession, *, source: str) -> tuple[int, int] | None:
    """Пересчитать роли всех пользователей AD; (сколько ролей снято, у скольких изменились).

    None — AD недоступен или не настроен: роли пересчитаются при входе и ежедневной синхронизации.
    """
    try:
        config = await ldap.load_config(db)
        changes = await _changes(db, config)
    except (AdConfigError, AdUnavailableError) as exc:
        log.warning("ad_roles_recalculate_skipped", error=type(exc).__name__)
        return None
    removed = changed = 0
    for user, want, _plan in changes:
        applied = await ad_roles.apply(db, user, want, source=source)
        removed += len(applied.removed)
        changed += not applied.empty
    return removed, changed


# --- сохранение ---------------------------------------------------------------------------------


def _audit_value(key: str, old: Any, new: Any) -> Any:
    if key == BIND_PASSWORD:
        return {"changed": True}
    if key == CONNECTION and isinstance(old, dict) and isinstance(new, dict):
        out = [{k: v for k, v in (old or {}).items() if k != "ca_cert_pem"},
               {k: v for k, v in new.items() if k != "ca_cert_pem"}]  # fmt: skip
        if old.get("ca_cert_pem") != new.get("ca_cert_pem"):
            out.append({"ca_cert_pem": {"changed": True}})
        return out
    return [old, new]


async def save(
    db: AsyncSession, actor: Principal, values: Mapping[str, Any], raw: Mapping[str, Any],
    changed: Mapping[str, Any], *, ip: str | None,
) -> None:  # fmt: skip
    """Записать изменённые ключи AD (``changed``) после проверок (раздел ``auth``)."""
    from estimator.admin import settings

    if any(key in changed for key in CHECKED):
        merged, password = await candidate(db, values)
        fp = ldap.fingerprint(merged, password)
        ver = await verification(db)
        same = ver.get("params_sha256") == fp
        missing = [name for name in ("connection", "login")
                   if not same or not ver.get(f"{name}_ok_at")]  # fmt: skip
        if missing:
            raise ApiError(
                "AD_CHECKS_REQUIRED",
                missing=missing,
                detail="Сохранить можно после успешных проверок подключения и входа",
            )
    old_mapping = settings.effective(ROLE_MAPPING, raw)
    for key, value in changed.items():
        await settings._store(db, actor, key, value)  # общий способ записи ключа
    await db.flush()
    await audit.write(
        db, "system.ad_settings.changed", user_id=actor.user_id, login=actor.login, ip=ip,
        session_id=actor.session_id, object_type="setting", object_id="auth",
        details={"changes": {k: _audit_value(k, settings.effective(k, raw), v)
                             for k, v in changed.items()}},
    )  # fmt: skip
    if ROLE_MAPPING in changed:
        await _mapping_changed(db, old_mapping or {}, changed[ROLE_MAPPING])


async def _mapping_changed(
    db: AsyncSession, old: Mapping[str, Any], new: Mapping[str, Any]
) -> None:
    was, now = bool(old.get("enabled")), bool(new.get("enabled"))
    if was and not now:
        await ad_roles.make_manual(db)
        return
    if not now:
        return
    result = await recalculate(db, source="ad_mapping_enabled" if not was else "ad_group")
    if not was:
        await audit.write(
            db, "users.ad_role_mapping.report", object_type=None, actor="system",
            details={"roles_to_remove": result[0] if result else 0, "applied": result is not None},
        )  # fmt: skip
