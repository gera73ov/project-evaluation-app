"""Мастер первичной настройки (ADM-001; SPEC 7.1 шаги 1–5, FR-SA-02, Q-16, SEC-AUD-01;
15.2 ``GET/POST /system/setup/{step}``).

Шаги API и отметки ``app.setup.steps_done`` (contracts/settings.schema.json):

=============  ====================  ===============================================
шаг            отметка               что сохраняет
=============  ====================  ===============================================
``app``        ``address_timezone``  ``app.base_url`` (обязателен), ``app.timezone``
``smtp``       ``smtp``              ``smtp.server``, ``smtp.password`` (тестовое письмо —
                                     ``POST /system/smtp/test``)
``auth``       ``auth_mode``         способ входа: «Приложение» — политика паролей
                                     (``security.password_policy``); AD — параметры
                                     ``auth.ad.*`` после обеих проверок AD
``security``   ``security_policies`` остальные ключи раздела ``security``
``first_admin`` ``first_admin``      первый администратор (или уже заведённый)
=============  ====================  ===============================================

Значения шага проверяются и записываются так же, как в системных настройках (ADM-002: контракт,
секреты, аудит «было → стало», оповещение ИБ при смене SMTP), но без step-up: мастер доступен
только суперадминистратору и только до завершения. Шаги можно проходить в любом порядке и
повторять. ``complete: true`` завершает мастер, когда отмечены все пять шагов и есть хотя бы один
администратор (FR-SA-02: без тупика «нет ни одного администратора»): ``completed_at``
снимает режим «Приложение настраивается» (AUTH-012). После завершения запись шагов — 409
``SETUP_ALREADY_COMPLETED``. Каждый шаг — ``system.setup.step_completed``, завершение —
``system.setup.finished``.

Режим AD в мастере (FE-094, 7.1 шаг 3): параметры AD записываются так же, как в разделе
«Аутентификация» (:func:`estimator.auth.ad_settings.save`), и только после успешных «Проверить
подключение» и «Проверить вход» с этими параметрами (иначе 409 ``AD_CHECKS_REQUIRED``), нужна хотя
бы одна группа доступа; затем ``auth.mode = ad`` сразу, без отчёта сопоставления: на чистой
установке локальных учёток, кроме суперадминистраторов (они всегда локальные, FR-SA-03), нет.
Если они уже есть — 422 на ``/auth.mode``: переход только через «Перейти на Active Directory…»
с отчётом (FR-AUTH-SW-01). Вернуться к «Приложению» до завершения мастера можно, пока нет учёток
из AD. Первого администратора в режиме AD выбирают поиском по каталогу (CR-011).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.admin import admins, settings
from estimator.admin.settings import schema
from estimator.api.common.errors import ApiError
from estimator.auth.context import Principal
from estimator.auth.policy import load_auth_mode
from estimator.auth.setup_gate import SETUP_KEY
from estimator.db.enums import SystemRole, UserSource, UserStatus
from estimator.db.models.settings import SystemSetting
from estimator.db.models.users import User, UserRole
from estimator.security import audit

#: шаг API → (отметка в ``app.setup.steps_done``, раздел настроек, ключи шага)
STEPS: dict[str, tuple[str, str | None, tuple[str, ...]]] = {
    "app": ("address_timezone", "app", ("app.base_url", "app.timezone")),
    "smtp": ("smtp", "smtp", ("smtp.server", "smtp.password")),
    "auth": (
        "auth_mode",
        "auth",
        (
            "auth.mode",
            "security.password_policy",
            "auth.ad.connection",
            "auth.ad.bind_password",
            "auth.ad.access_groups",
            "auth.ad.role_mapping",
        ),
    ),
    "security": (
        "security_policies",
        "security",
        (
            "security.session",
            "security.lockout",
            "security.mfa_policy",
            "security.admin_networks",
            "security.alert_email",
        ),
    ),
    "first_admin": ("first_admin", None, ()),
}
ALL_MARKS = tuple(mark for mark, _, _ in STEPS.values())
FIRST_ADMIN_FIELDS = frozenset({"login", "email", "full_name", "ad_object_guid"})


def _step(name: str) -> tuple[str, str | None, tuple[str, ...]]:
    if name not in STEPS:
        raise ApiError("NOT_FOUND")
    return STEPS[name]


async def state(db: AsyncSession) -> dict[str, Any]:
    raw = (await settings.stored(db, (SETUP_KEY,))).get(SETUP_KEY)
    return {**schema.default(SETUP_KEY), **(raw or {})}


async def _save_state(db: AsyncSession, actor: Principal, value: dict[str, Any]) -> None:
    await db.merge(SystemSetting(key=SETUP_KEY, value=value, updated_by=actor.user_id))
    await db.flush()


def _admin_exists() -> Any:
    return exists().where(
        UserRole.user_id == User.id,
        UserRole.role == SystemRole.ADMIN,
        User.status.in_((UserStatus.ACTIVE, UserStatus.PENDING_PASSWORD)),
    )


async def _admins(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(User.id, User.login, User.full_name, User.status)
        .where(_admin_exists())
        .order_by(User.full_name, User.id)
    )
    return [
        {"id": str(i), "login": login, "full_name": name, "status": status.value}
        for i, login, name, status in rows.all()
    ]


async def _values(db: AsyncSession, step: str) -> dict[str, Any]:
    _, _, names = _step(step)
    if step == "first_admin":
        return {"admins": await _admins(db)}
    raw = await settings.stored(db, names)
    return {k: settings.public_value(k, settings.effective(k, raw)) for k in names}


async def get_step(db: AsyncSession, step: str) -> dict[str, Any]:
    mark, _, _ = _step(step)
    current = await state(db)
    return {"step": step, "done": mark in current["steps_done"], "values": await _values(db, step)}


def _only(values: Mapping[str, Any], names: tuple[str, ...]) -> None:
    extra = sorted(set(values) - set(names))
    if extra:
        raise settings.validation_error([(f"/{k}", "Ключ не из этого шага") for k in extra])


async def _save_settings(
    db: AsyncSession, actor: Principal, step: str, values: Mapping[str, Any], ip: str | None
) -> None:
    _, _, names = _step(step)
    _only(values, names)
    if step == "auth":
        await _save_auth(db, actor, values, ip)
        return
    if step == "app":
        raw = await settings.stored(db, ("app.base_url",))
        if not values.get("app.base_url", raw.get("app.base_url")):
            raise settings.validation_error([("/app.base_url", "Укажите адрес приложения")])
    await settings.apply(db, actor, STEPS[step][1] or step, values, ip=ip)


def _other_users(*sources: UserSource) -> Any:
    """Живые учётки, кроме суперадминистраторов, из указанных источников."""
    superadmin = exists().where(UserRole.user_id == User.id, UserRole.role == SystemRole.SUPERADMIN)
    return exists().where(
        User.source.in_(sources), User.status != UserStatus.ANONYMIZED, ~superadmin
    )


async def _save_auth(
    db: AsyncSession, actor: Principal, values: Mapping[str, Any], ip: str | None
) -> None:
    from estimator.auth import ad_settings
    from estimator.auth.providers import ldap

    mode = values.get("auth.mode", "local")
    ad_values = {k: v for k, v in values.items() if k.startswith("auth.ad.")}
    current = await load_auth_mode(db)
    if mode == "local":
        if ad_values:
            raise settings.validation_error([(f"/{k}", "Только для режима AD") for k in ad_values])
        if current == "ad":
            if await db.scalar(select(_other_users(UserSource.AD))):
                raise settings.validation_error(
                    [("/auth.mode", "Уже есть учётки из AD: способ входа не вернуть")]
                )
            await _set_mode(db, actor, "local", ip)
        policy = {k: v for k, v in values.items() if k != "auth.mode"}
        await settings.apply(db, actor, "security", policy, ip=ip)
        return
    if mode != "ad":
        raise settings.validation_error([("/auth.mode", "Неизвестный способ входа")])
    if "security.password_policy" in values:
        raise settings.validation_error([("/security.password_policy", "Только для «Приложения»")])
    if current != "ad" and await db.scalar(select(_other_users(UserSource.LOCAL))):
        raise settings.validation_error(
            [("/auth.mode", "Есть локальные учётки: переход на AD — в разделе «Аутентификация»")]
        )
    await settings.apply(db, actor, "auth", ad_values, ip=ip)
    stored, password = await ldap.stored_values(db)
    ver = await ad_settings.verification(db)
    same = ver.get("params_sha256") == ldap.fingerprint(stored, password)
    missing = [n for n in ("connection", "login") if not same or not ver.get(f"{n}_ok_at")]
    if missing:
        raise ApiError(
            "AD_CHECKS_REQUIRED",
            missing=missing,
            detail="Сохранить можно после успешных проверок подключения и входа",
        )
    if not stored.get(ldap.ACCESS_GROUPS):
        raise settings.validation_error([("/auth.ad.access_groups", "Укажите группу доступа")])
    if current != "ad":
        await _set_mode(db, actor, "ad", ip)


async def _set_mode(db: AsyncSession, actor: Principal, mode: str, ip: str | None) -> None:
    await db.merge(SystemSetting(key="auth.mode", value=mode, updated_by=actor.user_id))
    await db.flush()
    await audit.write(
        db, "system.auth_mode.switched", user_id=actor.user_id, login=actor.login, ip=ip,
        session_id=actor.session_id, object_type="setting", object_id="auth.mode",
        details={"from": "ad" if mode == "local" else "local", "to": mode, "via": "ui",
                 "matched": 0, "ambiguous_confirmed": 0, "ambiguous_rejected": 0,
                 "not_found_blocked": 0, "dry_run": False},
    )  # fmt: skip


async def _first_admin(
    db: AsyncSession, actor: Principal, values: Mapping[str, Any]
) -> dict[str, Any]:
    extra = sorted(set(values) - FIRST_ADMIN_FIELDS)
    if extra:
        raise settings.validation_error([(f"/{k}", "Лишнее поле") for k in extra])
    out: dict[str, Any] = {}
    if values:
        missing = [k for k in ("login", "email", "full_name") if not values.get(k)]
        if missing:
            raise settings.validation_error([(f"/{k}", "Обязательное поле") for k in missing])
        out["activation"] = await admins.create_admin(
            db, actor, login=str(values["login"]), email=str(values["email"]),
            full_name=str(values["full_name"]), role=SystemRole.ADMIN.value,
            ad_object_guid=values.get("ad_object_guid"),
        )  # fmt: skip
    elif not await db.scalar(select(_admin_exists())):
        raise settings.validation_error([("/login", "Заведите первого администратора")])
    out["admins"] = await _admins(db)
    return out


async def post_step(
    db: AsyncSession,
    actor: Principal,
    step: str,
    values: Mapping[str, Any],
    *,
    complete: bool = False,
    ip: str | None = None,
) -> dict[str, Any]:
    mark, _, _ = _step(step)
    current = await state(db)
    if current.get("completed_at"):
        raise ApiError("SETUP_ALREADY_COMPLETED")
    extra: dict[str, Any] | None = None
    if step == "first_admin":
        extra = await _first_admin(db, actor, values)
    else:
        await _save_settings(db, actor, step, values, ip)
    if mark not in current["steps_done"]:
        current["steps_done"] = [m for m in ALL_MARKS if m in {*current["steps_done"], mark}]
        await _save_state(db, actor, current)
        await audit.write(
            db, "system.setup.step_completed", user_id=actor.user_id, login=actor.login, ip=ip,
            session_id=actor.session_id, object_type="setting", object_id=SETUP_KEY,
            details={"step": mark},
        )  # fmt: skip
    if complete:
        await _finish(db, actor, current, ip)
    return {"step": step, "done": True, "values": extra or await _values(db, step)}


async def _finish(
    db: AsyncSession, actor: Principal, current: dict[str, Any], ip: str | None
) -> None:
    missing = [m for m in ALL_MARKS if m not in current["steps_done"]]
    if missing:
        raise settings.validation_error([("/complete", "Не пройдены шаги: " + ", ".join(missing))])
    if not await db.scalar(select(_admin_exists())):
        raise settings.validation_error([("/complete", "Нет ни одного администратора")])
    current["completed_at"] = dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")
    await _save_state(db, actor, current)
    await audit.write(
        db, "system.setup.finished", user_id=actor.user_id, login=actor.login, ip=ip,
        session_id=actor.session_id, details={},
    )  # fmt: skip
