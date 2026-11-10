"""Поиск в каталоге AD и заведение заранее (AUTH-017; FR-AUTH-AD-10, FR-SA-02, Q-16, 3.3 «Найти
человека в AD»; ``GET /admin/ad/search``, ``GET /system/auth/ad/search``,
``GET/POST /projects/{id}/ad-search``).

* Поиск идёт сервисной учёткой; ввод экранируется каталогом, от 3 символов, до 50 записей: ФИО,
  логин, email, подразделение, признак «в группе доступа» и учётка приложения, если она уже есть.
* Заводится только тот, кто в группе доступа (иначе 409 ``AD_USER_NOT_IN_GROUP``). Существующая
  учётка (тот же ``objectGUID``) не создаётся заново — её просто назначают.
* Администратор заводит учётку с ролями до первого входа (``users.created`` ``admin_ad_search``);
  модератор проекта — только с ролью «Пользователь» и сразу назначает на дисциплину
  (``moderator_ad_search`` с ``project_id``).
* AD недоступен или не настроен — 503 ``AUTH_SERVICE_UNAVAILABLE``.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.errors import ApiError
from estimator.auth import ad_provisioning
from estimator.auth.context import Principal
from estimator.auth.providers import ldap
from estimator.auth.providers.ldap import AdConfig, AdConfigError, AdUnavailableError, Entry
from estimator.db.models.users import User

MIN_LENGTH = 3
LIMIT = 50


async def _config(db: AsyncSession) -> AdConfig:
    try:
        return await ldap.load_config(db)
    except AdConfigError:
        raise ApiError("AUTH_SERVICE_UNAVAILABLE") from None


async def search(db: AsyncSession, query: str) -> list[dict[str, Any]]:
    text = query.strip()
    if len(text) < MIN_LENGTH:
        raise ApiError("VALIDATION_FAILED", detail="Введите не меньше трёх символов",
                       errors=[{"field": "/q", "code": "too_short",
                                "message": "Введите не меньше трёх символов"}])  # fmt: skip
    config = await _config(db)
    directory = ldap.directory(config)
    try:
        entries = await directory.search(text, LIMIT)
        access = [bool(await directory.groups_of(e.dn, config.access_groups)) for e in entries]
    except AdUnavailableError:
        raise ApiError("AUTH_SERVICE_UNAVAILABLE") from None
    known = dict((await db.execute(
        select(User.ad_object_guid, User.id).where(
            User.ad_object_guid.in_([e.object_guid for e in entries])
        )
    )).all())  # fmt: skip
    return [
        {"object_guid": str(e.object_guid), "login": e.login, "full_name": e.full_name,
         "email": e.email, "department": e.department, "in_access_group": ok,
         "user_id": str(known[e.object_guid]) if e.object_guid in known else None}
        for e, ok in zip(entries, access, strict=True)
    ][:LIMIT]  # fmt: skip


async def entry_in_group(db: AsyncSession, guid: uuid.UUID) -> Entry:
    """Запись AD по ``objectGUID`` из поиска, состоящая в группе доступа."""
    config = await _config(db)
    directory = ldap.directory(config)
    try:
        entry = await directory.by_guid(guid)
        groups = await directory.groups_of(entry.dn, config.access_groups) if entry else set()
    except AdUnavailableError:
        raise ApiError("AUTH_SERVICE_UNAVAILABLE") from None
    if entry is None:
        raise ApiError("VALIDATION_FAILED", detail="Запись не найдена в AD",
                       errors=[{"field": "/ad_object_guid", "code": "not_found",
                                "message": "Запись не найдена в AD"}])  # fmt: skip
    if not groups:
        raise ApiError("AD_USER_NOT_IN_GROUP")
    return entry


async def ensure_user(
    db: AsyncSession, actor: Principal, guid: uuid.UUID, *, source: str,
    project_id: uuid.UUID | None = None, roles: Collection[str] = (),
) -> tuple[User, bool]:  # fmt: skip
    """Учётка человека из AD: существующая или новая; второй элемент — создана ли сейчас."""
    entry = await entry_in_group(db, guid)
    user = await ad_provisioning.by_guid(db, guid)
    if user is not None:
        return user, False
    try:
        user = await ad_provisioning.create(
            db, entry, source=source, actor_id=actor.user_id, actor_login=actor.login,
            project_id=project_id, roles=roles,
        )  # fmt: skip
    except ad_provisioning.LoginTakenError:
        raise ApiError("ALREADY_EXISTS", detail="Логин из AD уже занят другой учётной записью",
                       field="login") from None  # fmt: skip
    user.created_by = actor.user_id
    user.updated_by = actor.user_id
    return user, True
