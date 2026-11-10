"""Обсуждения: ленты узла и проекта, вопросы, ответы, автодополнение адресатов (CORE-040).

contracts/openapi.yaml: ``GET/POST /projects/{id}/threads``, ``GET/POST /nodes/{id}/messages``,
``GET/POST /projects/{id}/messages`` (CR-007), ``POST /threads/{id}/messages``,
``GET /projects/{id}/members/suggest``. Читают все участники проекта (FR-DISC-08), пишут — по
статусу проекта (M3.4-05, проверяет gate). Каждое сообщение, вопрос и ответ расходует лимит
60 сообщений в минуту на пользователя (SEC-WEB-07) сверх общего лимита изменений.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.api.common.pagination import PageParams, encode_cursor
from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.context import Principal
from estimator.auth.mfa_policy import ActivePrincipal, RedisDep
from estimator.db.enums import ThreadStatus
from estimator.db.models.discussions import Message, MessageAddressee, Thread
from estimator.db.models.projects import Project
from estimator.db.models.tree import Node
from estimator.db.session import DbSession
from estimator.security.authz.deps import AuthorizerDep, register_resolver
from estimator.security.authz.engine import Target
from estimator.security.ratelimit.limiter import LIMITS, RateLimiter
from estimator.services.customer_questions import flow as cq_flow
from estimator.services.discussions import addressees as addr
from estimator.services.discussions import edit as message_edit
from estimator.services.discussions import feed, resolve, write
from estimator.services.tree import edit as node_edit
from estimator.services.tree.moderator_edits import notify_experts

router = ApiRouter(tags=["Обсуждения"])
_NO_CONCLUSION = s.ResolveRequest()


async def thread_target(db: AsyncSession, thread_id: uuid.UUID) -> Target | None:
    """Объект ``/threads/{id}``: проект, статус, дисциплина узла, автор и адресаты вопроса."""
    row = (
        await db.execute(
            select(
                Thread.project_id,
                Thread.opened_by,
                Project.status,
                Node.discipline_id,
                Thread.customer_status,
            )
            .join(Project, Project.id == Thread.project_id)
            .outerjoin(Node, Node.id == Thread.node_id)
            .where(Thread.id == thread_id, Node.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        return None
    project_id, opened_by, status, discipline_id, cq_status = row
    tokens = (
        await db.execute(
            select(MessageAddressee.target_type, MessageAddressee.target_id)
            .join(Message, Message.id == MessageAddressee.message_id)
            .where(Message.thread_id == thread_id, Message.needs_answer)
        )
    ).all()
    users = (await addr.team(db, project_id)).expand((k, t) for k, t in tokens)
    return Target(
        project_id=project_id,
        project_status=str(status),
        disciplines=frozenset({discipline_id}) if discipline_id else frozenset(),
        author_id=opened_by,
        addressees=frozenset(users),
        attrs={"cq_status": str(cq_status)} if cq_status else {},
    )


register_resolver("/threads/{id}", thread_target)


async def message_target(db: AsyncSession, message_id: uuid.UUID) -> Target | None:
    """Объект ``/messages/{id}``: проект, статус, дисциплина узла, автор сообщения."""
    row = (
        await db.execute(
            select(Message.project_id, Message.author_id, Project.status, Node.discipline_id)
            .join(Project, Project.id == Message.project_id)
            .outerjoin(Node, Node.id == Message.node_id)
            .where(Message.id == message_id, Node.deleted_at.is_(None))
        )
    ).first()
    if row is None:
        return None
    project_id, author_id, status, discipline_id = row
    return Target(
        project_id=project_id,
        project_status=str(status),
        disciplines=frozenset({discipline_id}) if discipline_id else frozenset(),
        author_id=author_id,
    )


register_resolver("/messages/{id}", message_target)


async def _project(db: AsyncSession, project_id: uuid.UUID) -> Project:
    project = await db.get(Project, project_id)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return project


async def _node(db: AsyncSession, node_id: uuid.UUID) -> Node:
    node = await db.get(Node, node_id)
    if node is None or node.deleted_at is not None:  # pragma: no cover — gate ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return node


async def _limit(redis: RedisDep, principal: Principal) -> None:
    await RateLimiter(redis).check(LIMITS["messages"], str(principal.user_id))


def _raw(items: list[s.Addressee]) -> list[write.RawAddressee]:
    return [(str(a.target_type), a.target_id) for a in items]


async def _feed(
    db: AsyncSession, project_id: uuid.UUID, node_id: uuid.UUID | None, page: PageParams
) -> dict[str, Any]:
    scope = f"feed:{node_id or project_id}"
    out = await feed.feed(db, project_id, node_id, limit=page.limit, after=page.position(scope))
    return {
        "items": out.items,
        "threads": out.threads,
        "next_cursor": encode_cursor(scope, out.last) if out.more and out.last else None,
    }


@router.get(
    "/projects/{id}/threads",
    permission="discussion.read",
    response_model=s.ThreadList,
    response_model_exclude_unset=True,
)
async def list_threads(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    page: PageParams,
    principal: ActivePrincipal,
    db: DbSession,
    status: Annotated[ThreadStatus | None, Query()] = None,
    addressee: Annotated[str | None, Query(pattern="^(me|any)$")] = None,
    discipline_id: Annotated[uuid.UUID | None, Query()] = None,
    node_id: Annotated[uuid.UUID | None, Query()] = None,
    project_level: Annotated[bool | None, Query()] = None,
) -> dict[str, Any]:
    to_me = None
    if addressee == "me":
        to_me = frozenset((await addr.team(db, id)).tokens(principal.user_id))
    flt = feed.ThreadFilter(status, to_me, discipline_id, node_id, project_level)
    scope = f"threads:{id}"
    items, more, last = await feed.list_threads(
        db, id, flt, limit=page.limit, after=page.position(scope)
    )
    return {"items": items, "next_cursor": encode_cursor(scope, last) if more and last else None}


@router.post(
    "/projects/{id}/threads",
    permission="discussion.write",
    status_code=201,
    response_model=s.Thread,
    response_model_exclude_unset=True,
)
async def create_thread(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.ThreadCreate,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    await _limit(redis, principal)
    project = await _project(db, id)
    node = None
    if body.node_id is not None:
        node = await db.get(Node, body.node_id)
        if node is None or node.deleted_at is not None or node.project_id != project.id:
            raise addr.invalid("node_id", "узла нет в проекте")
    _, thread = await write.post(
        db, principal, project, node, body.body, _raw(body.addressees), needs_answer=True
    )
    if thread is None:  # pragma: no cover — needs_answer=True всегда открывает вопрос
        raise HTTPException(500)
    [out] = await feed.threads_out(db, [thread])
    return out


@router.get(
    "/nodes/{id}/messages",
    permission="discussion.read",
    response_model=s.NodeFeed,
    response_model_exclude_unset=True,
)
async def list_node_messages(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    page: PageParams,
    db: DbSession,
) -> dict[str, Any]:
    node = await _node(db, id)
    return await _feed(db, node.project_id, node.id, page)


@router.post(
    "/nodes/{id}/messages",
    permission="discussion.write",
    status_code=201,
    response_model=s.Message,
    response_model_exclude_unset=True,
)
async def post_node_message(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.MessageCreate,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    await _limit(redis, principal)
    node = await _node(db, id)
    project = await _project(db, node.project_id)
    out, _ = await write.post(
        db,
        principal,
        project,
        node,
        body.body,
        _raw(body.addressees),
        needs_answer=body.needs_answer,
    )
    return out


@router.get(
    "/projects/{id}/messages",
    permission="discussion.read",
    response_model=s.NodeFeed,
    response_model_exclude_unset=True,
)
async def list_project_messages(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    page: PageParams,
    db: DbSession,
) -> dict[str, Any]:
    return await _feed(db, id, None, page)


@router.post(
    "/projects/{id}/messages",
    permission="discussion.write",
    status_code=201,
    response_model=s.Message,
    response_model_exclude_unset=True,
)
async def post_project_message(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.MessageCreate,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    await _limit(redis, principal)
    project = await _project(db, id)
    out, _ = await write.post(
        db,
        principal,
        project,
        None,
        body.body,
        _raw(body.addressees),
        needs_answer=body.needs_answer,
    )
    return out


@router.post(
    "/threads/{id}/messages",
    permission="discussion.write",
    status_code=201,
    response_model=s.Message,
    response_model_exclude_unset=True,
)
async def reply_thread(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.MessageCreate,
    principal: ActivePrincipal,
    redis: RedisDep,
    db: DbSession,
) -> dict[str, Any]:
    await _limit(redis, principal)
    thread = await db.get(Thread, id)
    if thread is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    project = await _project(db, thread.project_id)
    return await write.reply(db, principal, project, thread, body.body, _raw(body.addressees))


@router.get(
    "/projects/{id}/members/suggest",
    permission="discussion.read",
    tags=["Проекты"],
    response_model=s.SuggestList,
)
async def suggest_addressees(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    q: Annotated[str, Query(max_length=100)],
    db: DbSession,
) -> dict[str, Any]:
    return {"items": await addr.suggest(db, id, q)}


async def _thread(db: AsyncSession, thread_id: uuid.UUID) -> Thread:
    thread = await db.get(Thread, thread_id)
    if thread is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return thread


async def _thread_out(db: AsyncSession, thread: Thread) -> dict[str, Any]:
    await db.flush()
    [out] = await feed.threads_out(db, [thread])
    return out


@router.post(
    "/threads/{id}/resolve",
    permission=["thread.resolve", "cq.close"],
    response_model=s.Thread,
    response_model_exclude_unset=True,
)
async def resolve_thread(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
    body: s.ResolveRequest = _NO_CONCLUSION,
) -> dict[str, Any]:
    """«Решено» (FR-DISC-05); с ``conclusion`` — строка вывода в комментарий узла вопроса."""
    thread = await _thread(db, id)
    target = await thread_target(db, thread.id)
    if thread.is_customer:  # BR-CQ-02: «отвечен» → «решён» (автор, модератор, пресейл)
        await authz.check("cq.close", target)
        await cq_flow.close(db, principal, thread)
        return await _thread_out(db, thread)
    await authz.check("thread.resolve", target)
    conclusion = body.conclusion
    if conclusion is not None:
        node = await node_edit.live_node(db, thread.node_id) if thread.node_id else None
        if node is None:
            raise addr.invalid("conclusion", "вывод добавляется только к вопросу узла")
        project = await _project(db, thread.project_id)
        node_target = Target(
            project_id=project.id,
            project_status=str(project.status),
            disciplines=frozenset({node.discipline_id}) if node.discipline_id else frozenset(),
        )
        await authz.check("comment.write", node_target)
        lines = resolve.conclusion_lines(node, conclusion.text, conclusion.tag_id)
        was = node.version
        node, _, _ = await node_edit.patch_node(
            db, principal, project, node, node.version, {"comment_lines": lines}
        )
        if node.version != was:
            await notify_experts(
                db, principal, project.id, node.id, node.discipline_id, ["comment"]
            )
    await resolve.resolve(db, principal, thread)
    return await _thread_out(db, thread)


@router.post(
    "/threads/{id}/reopen",
    permission=["thread.resolve", "cq.reopen"],
    response_model=s.Thread,
    response_model_exclude_unset=True,
)
async def reopen_thread(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
    authz: AuthorizerDep,
) -> dict[str, Any]:
    thread = await _thread(db, id)
    if thread.is_customer:  # BR-CQ-02: «решён» → «отвечен» (модератор, пресейл)
        await authz.check("cq.reopen", await thread_target(db, thread.id))
        await cq_flow.reopen(db, principal, thread)
        return await _thread_out(db, thread)
    await authz.check("thread.resolve", await thread_target(db, thread.id))
    await resolve.reopen(db, principal, thread)
    return await _thread_out(db, thread)


async def _message(db: AsyncSession, message_id: uuid.UUID) -> Message:
    message = await db.get(Message, message_id)
    if message is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    return message


@router.patch(
    "/messages/{id}",
    permission="discussion.write",
    response_model=s.Message,
    response_model_exclude_unset=True,
)
async def edit_message(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    body: s.MessagePatch,
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    return await message_edit.edit(db, principal, await _message(db, id), body.body)


@router.post(
    "/messages/{id}/revoke",
    permission="discussion.write",
    response_model=s.Message,
    response_model_exclude_unset=True,
)
async def revoke_message(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> dict[str, Any]:
    return await message_edit.revoke(db, principal, await _message(db, id))


@router.get(
    "/messages/{id}/history",
    permission="discussion.history",
    response_model=s.MessageHistoryList,
    response_model_exclude_unset=True,
)
async def get_message_history(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    db: DbSession,
) -> dict[str, Any]:
    return {"items": await message_edit.history(db, await _message(db, id))}
