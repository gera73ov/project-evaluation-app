"""RT-003 · WebSocket-эндпоинт ``/api/v1/ws`` и подписки (SPEC 15.4, SEC-AUTHZ-01, SEC-WEB-04/08).

Подключение (contracts/ws-events.md, «Главное»):

1. ``Origin`` — только адрес приложения, иначе соединение закрывается кодом 4403 (SEC-WEB-04);
2. сессия из cookie ``__Host-session`` — без продления (FR-SESS-02); нет сессии — HTTP 401,
   незавершённые смена пароля или подключение TOTP — 403, мастер настройки — 503, сессия
   суперадминистратора из чужой сети — 404 (FR-SA-06);
3. личный канал ``user:{id}`` подписывается сразу; на проект — командой ``subscribe``.

Каждая команда проверяет сессию и права заново по актуальным данным. ``subscribe`` подписывает
на ``project:{id}`` (право ``tree.read`` с учётом статуса, M3.4-01) и, при праве и пройденном
TOTP, на ``:money`` и ``:notes``; чужой и несуществующий проект — одинаковый ``NOT_FOUND``.
Сообщение больше 64 КБ закрывает соединение кодом 1009, поток команд сверх лимита — ответ
``RATE_LIMITED``, затем закрытие 4429. Захват ячеек (``lock``/``unlock``) подключит RT-005,
догрузку по ``since`` — RT-007; до этого отставший клиент получает ``resync: true``.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from collections import deque
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, WebSocket
from starlette.websockets import WebSocketDisconnect, WebSocketState

from estimator.api.common.errors import problem_response
from estimator.auth.context import Principal, UnauthenticatedError, resolve_principal
from estimator.auth.policy import read_settings
from estimator.logging import get_logger
from estimator.realtime import metrics as ws_metrics
from estimator.realtime.bus import build_event
from estimator.realtime.bus.contract import check_event
from estimator.realtime.changes import VersionTooOld, changes_since
from estimator.realtime.locks import CellLocked
from estimator.realtime.revoke import DEFAULT_ENDED, UNAUTH_TO_ENDED
from estimator.realtime.users import user_ref
from estimator.realtime.ws import access as ws_access
from estimator.realtime.ws.hub import Connection, ProjectAccess, allowed
from estimator.realtime.ws.protocol import (
    CLOSE_ORIGIN,
    CLOSE_RATE_LIMITED,
    CLOSE_SESSION_ENDED,
    CLOSE_TOO_BIG,
    CLOSE_UNSUPPORTED,
    MAX_MESSAGE_BYTES,
    Command,
    CommandError,
    ack,
    command_error,
    error,
    parse_command,
)
from estimator.security.web.origin import origin_allowed

if TYPE_CHECKING:
    from estimator.realtime.runtime import Realtime

log = get_logger(__name__)

PATH = "/ws"
#: Не больше стольких проектов на одно соединение (вкладка открывает один проект)
MAX_SUBSCRIPTIONS = 10
#: Команд за окно; сверх — ``RATE_LIMITED``, сверх двойного — закрытие 4429 (толкование 3)
RATE_WINDOW_SECONDS = 10.0
RATE_MAX_COMMANDS = 100
MAX_LOCKS = 20

router = APIRouter()


@router.websocket(PATH)
async def websocket_endpoint(ws: WebSocket) -> None:
    realtime: Realtime = ws.app.state.realtime
    await WsSession(realtime, ws).run()


def _base_url_host(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("url") or value.get("value")
    if not isinstance(value, str) or "://" not in value:
        return None
    return value.split("://", 1)[1].split("/", 1)[0] or None


class WsSession:
    """Одно соединение: рукопожатие, чтение команд, отправка событий, перепроверка прав."""

    def __init__(self, realtime: Realtime, ws: WebSocket) -> None:
        self.rt = realtime
        self.ws = ws
        self.conn: Connection | None = None
        self.principal: Principal | None = None
        self._commands: deque[float] = deque()

    @property
    def c(self) -> Connection:
        if self.conn is None:
            raise RuntimeError("соединение ещё не открыто")
        return self.conn

    # --- рукопожатие ---

    async def _origin_ok(self, db: Any) -> bool:
        hosts = set(self.rt.allowed_hosts)
        configured = await read_settings(db, "app.base_url")
        if host := _base_url_host(configured.get("app.base_url")):
            hosts.add(host)
        return origin_allowed(self.ws.headers.get("origin"), hosts)

    async def _deny(self, code: str) -> None:
        response = problem_response(self.ws, code)  # type: ignore[arg-type]
        try:
            await self.ws.send_denial_response(response)
        except RuntimeError:  # сервер без расширения websocket.http.response
            await self.ws.close(code=1008)

    async def _open(self) -> Principal | None:
        service = self.rt.session_service()
        async with self.rt.db() as db:
            if not await self._origin_ok(db):
                await self.ws.accept()
                await self.ws.close(code=CLOSE_ORIGIN)
                return None
            try:
                return await ws_access.handshake(self.ws, db, service)
            except ws_access.HandshakeDenied as denied:
                await self._deny(denied.code)
                return None

    async def run(self) -> None:
        principal = await self._open()
        if principal is None:
            return
        self.principal = principal
        await self.ws.accept()
        conn = Connection(
            user_id=principal.user_id,
            session_id=principal.session_id,
            session_hash=principal.session_hash,
            user=user_ref(principal.user_id, principal.full_name),
            roles=frozenset(str(r) for r in principal.roles),
            support_projects=principal.support_projects,
        )
        self.conn = conn
        self.rt.hub.add(conn)
        tasks = [
            asyncio.create_task(self._writer(), name="ws-writer"),
            asyncio.create_task(self._reader(), name="ws-reader"),
            asyncio.create_task(self._revalidator(), name="ws-revalidator"),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            if tasks[0] not in done:
                # Читатель или перепроверка закончили: дать писателю дослать очередь и закрыть
                conn.close(conn.close_code or 1000)
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(asyncio.shield(tasks[0]), timeout=2)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            self.rt.hub.remove(conn)
            await self.rt.cells.release_all(conn, "disconnected")
            await self._leave_all()

    async def _leave_all(self) -> None:
        conn = self.c
        for project_id in list(conn.projects):
            await self._presence_leave(project_id)

    # --- задачи соединения ---

    async def _writer(self) -> None:
        conn = self.c
        while True:
            message = await conn.queue.get()
            if message is None:
                break
            try:
                await self.ws.send_text(json.dumps(message, ensure_ascii=False))
            except (WebSocketDisconnect, RuntimeError):
                return
            ws_metrics.observe_sent(message)
        if self.ws.application_state is WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await self.ws.close(code=conn.close_code or 1000, reason=conn.close_reason)

    async def _reader(self) -> None:
        conn = self.c
        while not conn.closing:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            text = message.get("text")
            if text is None:
                conn.close(CLOSE_UNSUPPORTED, "text frames only")
                return
            if len(text.encode()) > MAX_MESSAGE_BYTES:
                conn.close(CLOSE_TOO_BIG, "message too big")
                return
            if self._rate_ok(text):
                await self._handle(text)

    def _rate_ok(self, text: str) -> bool:
        conn = self.c
        now = time.monotonic()
        while self._commands and self._commands[0] < now - RATE_WINDOW_SECONDS:
            self._commands.popleft()
        self._commands.append(now)
        count = len(self._commands)
        if count > 2 * RATE_MAX_COMMANDS:
            conn.close(CLOSE_RATE_LIMITED, "rate limited")
            return False
        if count > RATE_MAX_COMMANDS:
            retry = max(1, int(self._commands[0] + RATE_WINDOW_SECONDS - now) + 1)
            op = req_id = None
            with contextlib.suppress(Exception):
                raw = json.loads(text)
                op, req_id = raw.get("op"), raw.get("req_id")
            conn.push(error(op, req_id, "RATE_LIMITED", retry_after=retry))
            return False
        return True

    async def _revalidator(self) -> None:
        conn = self.c
        while not conn.closing:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(conn.recheck.wait(), timeout=self.rt.revalidate_seconds)
            conn.recheck.clear()
            if conn.closing:
                return
            try:
                await self.revalidate()
                await self.rt.cells.expire(conn)
            except Exception:  # сбой БД или Redis: проверить на следующем круге
                log.exception("ws_revalidate_failed")

    # --- команды ---

    async def _handle(self, text: str) -> None:
        conn = self.c
        try:
            command = parse_command(text)
        except CommandError as exc:
            conn.push(command_error(exc))
            return
        try:
            await self._dispatch(command)
        except CommandError as exc:
            conn.push(error(command.op, command.req_id, exc.code, exc.detail, **exc.extensions))
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            code = str(detail.get("code", "FORBIDDEN"))
            ext = {k: v for k, v in detail.items() if k != "code"}
            conn.push(error(command.op, command.req_id, code, **ext))

    async def _dispatch(self, command: Command) -> None:
        conn = self.c
        async with self.rt.db() as db:
            principal = await self._current(db)
            if principal is None:
                return
            if command.op == "subscribe":
                await self._subscribe(db, principal, command)
            elif command.op == "unsubscribe":
                await self._unsubscribe(command)
            elif command.op == "heartbeat":
                # продлевает захваты, но не сессию (FR-SESS-02)
                extended, lost = await self.rt.cells.extend(conn, command.args.get("locks", []))
                conn.push(ack("heartbeat", command.req_id, {"extended": extended, "lost": lost}))
            elif command.op == "lock":
                await self._lock(db, principal, command)
            else:
                await self._unlock(command)

    # --- RT-005: захват ячеек ---

    def _cell(self, command: Command) -> tuple[uuid.UUID, uuid.UUID, str]:
        return command.uuid("project_id"), command.uuid("node_id"), str(command.args["field"])

    async def _lock(self, db: Any, principal: Principal, command: Command) -> None:
        conn = self.c
        key = self._cell(command)
        project_id, node_id, field = key
        if project_id not in conn.projects:
            raise CommandError("NOT_FOUND", "сначала подпишитесь на проект")
        target = await ws_access.node_target(db, node_id)
        if target is None or target.project_id != project_id:
            raise CommandError("NOT_FOUND")
        authz = ws_access.authorizer(self.ws, principal, db, self.rt.redis)
        await authz.check(ws_access.write_permission(field), target)
        force = bool(command.args.get("force", False))
        if force:
            await authz.check("tree.lock.force", target)
        if key not in conn.locks and len(conn.locks) >= MAX_LOCKS:
            raise CommandError("VALIDATION_FAILED", f"не больше {MAX_LOCKS} захватов")
        try:
            got = await self.rt.cells.acquire(conn, key, force=force)
        except CellLocked as exc:
            raise CommandError(
                "CELL_LOCKED", locked_by=exc.holder.user, expires_at=exc.holder.expires_at
            ) from None
        conn.push(ack("lock", command.req_id, {"expires_at": got.expires_at}))

    async def _unlock(self, command: Command) -> None:
        conn = self.c
        key = self._cell(command)
        if key in conn.locks:
            await self.rt.cells.release(conn, key, "released")
        conn.push(ack("unlock", command.req_id))

    async def _current(self, db: Any) -> Principal | None:
        """Сессия и пользователь по актуальным данным; пропали — ``session.ended`` и закрытие."""
        conn = self.c
        try:
            principal = await resolve_principal(
                self.ws, db, self.rt.session_service(), conn.session_id, touch=False
            )
        except UnauthenticatedError as exc:
            self.end_session(UNAUTH_TO_ENDED.get(exc.reason or "", DEFAULT_ENDED))
            return None
        self.principal = principal
        return principal

    async def _subscribe(self, db: Any, principal: Principal, command: Command) -> None:
        conn = self.c
        project_id = command.uuid("project_id")
        is_new = project_id not in conn.projects
        if is_new and len(conn.projects) >= MAX_SUBSCRIPTIONS:
            raise CommandError("VALIDATION_FAILED", f"не больше {MAX_SUBSCRIPTIONS} проектов")
        access = await ws_access.project_access(self.ws, principal, db, self.rt.redis, project_id)
        since = command.args.get("since")
        # Живые события проекта ждут, пока не дослан журнал: порядок версий сохраняется (RT-007)
        if since is not None:
            conn.holding[project_id] = []
        self.rt.hub.set_access(conn, access)
        conn.support_projects = principal.support_projects
        state = await ws_access.project_state(db, project_id)
        backlog: list[dict[str, Any]] = []
        resync = False
        if since is not None:
            try:
                changes = await changes_since(
                    db, project_id, since, state.version,
                    allowed=lambda e: allowed(access, e, strict=self.rt.hub.strict),
                )  # fmt: skip
                backlog = changes.events
            except VersionTooOld:
                resync = True
        conn.push(
            ack(
                "subscribe",
                command.req_id,
                {
                    "project_version": state.version,
                    "channels": sorted(access.channels),
                    "resync": resync,
                },
            )
        )
        if resync:
            event = build_event(
                f"project:{project_id}",
                "resync.required",
                {"project_id": str(project_id), "project_version": state.version},
            )
            check_event(event)
            conn.push(event, direct=True)
        for event in backlog:
            conn.push(event, direct=True)
        self._release_hold(project_id, state.version if resync else _last_version(backlog, since))
        if is_new:
            await self.rt.presence.join(project_id, conn.id, conn.user)

    def _release_hold(self, project_id: uuid.UUID, sent_up_to: int | None) -> None:
        """Отложенные живые события — после журнала, без уже досланных версий."""
        conn = self.c
        held = conn.holding.pop(project_id, None) or []
        for event in held:
            version = event.get("project_version")
            if sent_up_to is not None and isinstance(version, int) and version <= sent_up_to:
                continue
            conn.push(event)

    async def _unsubscribe(self, command: Command) -> None:
        conn = self.c
        project_id = command.uuid("project_id")
        await self.rt.cells.release_all(conn, "released", project_id=project_id)
        if self.rt.hub.drop_project(conn, project_id):
            await self._presence_leave(project_id)
        conn.push(ack("unsubscribe", command.req_id))

    async def _presence_leave(self, project_id: uuid.UUID) -> None:
        conn = self.c
        try:
            await self.rt.presence.leave(project_id, conn.id)
        except Exception:  # Redis недоступен: запись устареет сама за 30 с
            log.exception("presence_leave_failed")

    # --- RT-008: перепроверка и отзыв ---

    async def revalidate(self) -> None:
        """Сессия и права на каждый подписанный проект — по актуальным данным."""
        conn = self.c
        async with self.rt.db() as db:
            principal = await self._current(db)
            if principal is None:
                return
            had_support = conn.support_projects
            conn.support_projects = principal.support_projects
            for project_id in list(conn.projects):
                try:
                    access = await ws_access.project_access(
                        self.ws, principal, db, self.rt.redis, project_id, audited=False
                    )
                except HTTPException:
                    reason = await ws_access.revoke_reason(
                        db, principal, project_id, had_support=project_id in had_support
                    )
                    await self.revoke(project_id, reason)
                    continue
                if access != conn.projects.get(project_id):
                    self.rt.hub.set_access(conn, access)
            if conn.locks:
                await self._recheck_locks(db, principal)

    async def revoke(self, project_id: uuid.UUID, reason: str) -> None:
        """``access.revoked`` подписчику и отписка от всех каналов проекта."""
        conn = self.c
        event = build_event(
            f"project:{project_id}",
            "access.revoked",
            {"project_id": str(project_id), "reason": reason},
        )
        check_event(event)
        conn.push(event)
        await self.rt.cells.release_all(conn, "released", project_id=project_id)
        if self.rt.hub.drop_project(conn, project_id):
            await self._presence_leave(project_id)

    async def _recheck_locks(self, db: Any, principal: Principal) -> None:
        """Пропало право правки узла (``member.updated``, статус проекта) — снять захват."""
        conn = self.c
        for key in list(conn.locks):
            _, node_id, field = key
            target = await ws_access.node_target(db, node_id)
            try:
                if target is None:
                    raise HTTPException(404)
                await ws_access.check_silent(
                    self.ws, principal, db, self.rt.redis, ws_access.write_permission(field), target
                )
            except HTTPException:
                await self.rt.cells.release(conn, key, "released")

    def end_session(self, reason: str) -> None:
        conn = self.c
        end_connection(conn, reason)


def _last_version(events: list[dict[str, Any]], since: int | None) -> int | None:
    versions = [e["project_version"] for e in events if isinstance(e.get("project_version"), int)]
    return max(versions, default=since)


def end_connection(conn: Connection, reason: str) -> None:
    """``session.ended`` в личный канал и закрытие кодом 4401 (FR-SESS-02)."""
    if conn.closing:
        return
    event = build_event(conn.user_channel, "session.ended", {"reason": reason})
    check_event(event)
    conn.push(event)
    conn.close(CLOSE_SESSION_ENDED, "session ended")


__all__ = ["PATH", "ProjectAccess", "WsSession", "end_connection", "router"]
