"""Роли БД (DB-002; contracts/db/schema.md G-14, SEC-AUD-03/04).

Роли кластерные и создаются первой миграцией (``NOLOGIN``). Учётные записи для входа
(``LOGIN`` с паролем) заводит служба эксплуатации и включает их в эти роли — см. alembic/README.md.
Каждое соединение само переключается на нужную роль командой ``SET ROLE``:

* ``estimator migrate`` (Alembic) — на :data:`MIGRATOR`, поэтому все объекты принадлежат ей;
* API и Celery (:mod:`estimator.db.session`) — на :data:`APP`;
* ``estimator audit purge`` (SEC-004) — на :data:`AUDIT_PURGE`.
"""

from __future__ import annotations

#: Владелец схем ``public`` (объекты) и ``audit``; выполняет миграции.
MIGRATOR = "estimator_migrator"
#: Рабочая роль API и Celery: DML без DDL; на таблицах «только INSERT» нет UPDATE/DELETE.
APP = "estimator_app"
#: Только удаление старых записей аудита и запись якоря (``estimator audit purge``).
AUDIT_PURGE = "estimator_audit_purge"

ALL = (MIGRATOR, APP, AUDIT_PURGE)


def set_role_sql(role: str) -> str:
    """``SET ROLE`` для одной из ролей :data:`ALL` (имя — константа, не ввод пользователя)."""
    if role not in ALL:
        raise ValueError(f"неизвестная роль БД: {role}")
    return f'SET ROLE "{role}"'
