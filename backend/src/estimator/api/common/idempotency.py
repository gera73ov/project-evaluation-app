"""Повторы создающих ``POST`` по ``Idempotency-Key`` (API-003; contracts/api-conventions.md 9).

Клиент передаёт ``Idempotency-Key: <UUID>`` на одно действие пользователя. Сервер хранит ответ
10 минут в Redis на пару «пользователь + ключ» и на повтор с тем же ключом возвращает сохранённый
ответ, не выполняя действие второй раз. Одновременный повтор, пока первый запрос ещё идёт, получает
409 ``ALREADY_EXISTS`` (действие уже выполняется). Ключ не UUID → 422 ``VALIDATION_FAILED``.

Использование в эндпоинте::

    @router.post("/nodes", permission="tree.edit", status_code=201)
    async def create_node(body: NodeIn, idem: Idempotency, principal: CurrentPrincipal):
        async with idem.scope(principal.user_id) as replay:
            if replay is not None:
                return replay              # исходный ответ (статус и тело)
            node = await service.create(...)
            return idem.remember(NodeOut.model_validate(node), status_code=201)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from estimator.api.common.errors import ApiError

TTL_SECONDS = 600
_PENDING = "pending"


class IdempotencyGuard:
    def __init__(self, redis: Any, key: uuid.UUID | None) -> None:
        self._redis = redis
        self._key = key
        self._redis_key: str | None = None
        self._value: str | None = None

    @asynccontextmanager
    async def scope(self, user_id: uuid.UUID | str) -> AsyncIterator[JSONResponse | None]:
        """Внутри блока — действие; ``replay`` не ``None`` — повтор с сохранённым ответом."""
        if self._key is None:
            yield None
            return
        self._redis_key = f"idem:{user_id}:{self._key}"
        if not await self._redis.set(self._redis_key, _PENDING, nx=True, ex=TTL_SECONDS):
            stored = await self._redis.get(self._redis_key)
            if stored is None or stored in (_PENDING, _PENDING.encode()):
                raise ApiError("ALREADY_EXISTS", detail="запрос с этим Idempotency-Key выполняется")
            data = json.loads(stored)
            yield JSONResponse(data["body"], status_code=data["status"])
            return
        try:
            yield None
        except BaseException:
            # Действие не выполнено — повтор с тем же ключом должен пройти заново
            await self._redis.delete(self._redis_key)
            raise
        if self._value is None:
            await self._redis.delete(self._redis_key)
        else:
            await self._redis.set(self._redis_key, self._value, ex=TTL_SECONDS)

    def remember(self, body: Any, *, status_code: int = 200) -> JSONResponse:
        """Сохранить ответ для повторов и вернуть его."""
        content = jsonable_encoder(body)
        response = JSONResponse(content, status_code=status_code)
        if self._redis_key is not None:
            self._value = json.dumps({"status": status_code, "body": content})
        return response


async def idempotency(
    request: Request,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> IdempotencyGuard:
    key: uuid.UUID | None = None
    if idempotency_key is not None:
        try:
            key = uuid.UUID(idempotency_key)
        except ValueError as exc:
            raise ApiError(
                "VALIDATION_FAILED",
                errors=[
                    {"field": "/headers/Idempotency-Key", "code": "pattern", "message": "UUID"}
                ],
            ) from exc
    return IdempotencyGuard(request.app.state.redis, key)


Idempotency = Annotated[IdempotencyGuard, Depends(idempotency)]
