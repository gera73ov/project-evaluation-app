# Тестовые случаи правил raw-sql.yml (semgrep --test). Код не выполняется и не импортируется.
# ruff: noqa
from sqlalchemy import select, text


async def bad(session, conn, name, table):
    # ruleid: estimator-raw-sql-interpolation
    await session.execute(text(f"SELECT * FROM users WHERE login = '{name}'"))
    # ruleid: estimator-raw-sql-interpolation
    await session.execute(text("SELECT * FROM users WHERE login = '%s'" % name))
    # ruleid: estimator-raw-sql-interpolation
    await session.execute(text("SELECT * FROM {} WHERE 1=1".format(table)))
    # ruleid: estimator-raw-sql-interpolation
    await session.execute(text("SELECT * FROM users WHERE login = '" + name + "'"))
    # ruleid: estimator-raw-sql-interpolation
    q = f"DELETE FROM projects WHERE id = {name}"
    await conn.execute(q)
    # ruleid: estimator-raw-sql-interpolation
    await conn.fetch(f"SELECT {table}")
    # ruleid: estimator-exec-driver-sql
    await conn.exec_driver_sql(name)


async def good(session, conn, name, users):
    # ok: estimator-raw-sql-interpolation
    await session.execute(text("SELECT * FROM users WHERE login = :login"), {"login": name})
    # ok: estimator-raw-sql-interpolation
    await session.execute(select(users).where(users.c.login == name))
    # ok: estimator-raw-sql-interpolation
    await session.execute(text("SELECT 1"))
    # ok: estimator-exec-driver-sql
    await conn.exec_driver_sql("SELECT 1")
