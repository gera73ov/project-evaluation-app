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
from estimator.realtime.bus import build_event
from estimator.realtime.bus.contract import check_event
from estimator.realtime.revoke import DEFAULT_ENDED, UNAUTH_TO_ENDED
from estimator.realtime.users import user_ref
from estimator.realtime.ws import access as ws_access
from estimator.realtime.ws.hub import Connection, ProjectAccess
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
                # Захватов до RT-005 нет: всё перечисленное — потеряно; сессию не продлевает
                lost = command.args.get("locks", [])
                conn.push(ack("heartbeat", command.req_id, {"extended": [], "lost": lost}))
            else:
                raise CommandError("SERVICE_UNAVAILABLE", "захват ячеек ещё не включён (RT-005)")

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
        state = await ws_access.project_state(db, project_id)
        self.rt.hub.set_access(conn, access)
        conn.support_projects = principal.support_projects
        since = command.args.get("since")
        # RT-007 заменит на догрузку из change_log; до него отставший клиент перезагружает дерево
        resync = since is not None and since != state.version
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
            conn.push(event)
        if is_new:
            await self.rt.presence.join(project_id, conn.id, conn.user)

    async def _unsubscribe(self, command: Command) -> None:
        conn = self.c
        project_id = command.uuid("project_id")
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
        if self.rt.hub.drop_project(conn, project_id):
            await self._presence_leave(project_id)

    def end_session(self, reason: str) -> None:
        conn = self.c
        end_connection(conn, reason)


def end_connection(conn: Connection, reason: str) -> None:
    """``session.ended`` в личный канал и закрытие кодом 4401 (FR-SESS-02)."""
    if conn.closing:
        return
    event = build_event(conn.user_channel, "session.ended", {"reason": reason})
    check_event(event)
    conn.push(event)
    conn.close(CLOSE_SESSION_ENDED, "session ended")


__all__ = ["PATH", "ProjectAccess", "WsSession", "end_connection", "router"]
