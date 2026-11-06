"""API-003: повтор POST с тем же Idempotency-Key возвращает исходный ответ (api-conventions 9)."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from estimator.api.common import Idempotency, install_error_handlers

pytestmark = pytest.mark.spec("15.1")


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key], self.ttl[key] = value, ex or 0
        return True

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


def _client() -> tuple[TestClient, FakeRedis, list[int]]:
    app = FastAPI()
    install_error_handlers(app)
    app.state.redis = FakeRedis()
    created: list[int] = []

    @app.post("/nodes", status_code=201)
    async def create(idem: Idempotency, fail: bool = False):
        async with idem.scope("user-1") as replay:
            if replay is not None:
                return replay
            if fail:
                raise RuntimeError("сбой")
            created.append(len(created) + 1)
            return idem.remember({"id": created[-1]}, status_code=201)

    return TestClient(app, raise_server_exceptions=False), app.state.redis, created


def test_retry_returns_original_response() -> None:
    client, redis, created = _client()
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    first = client.post("/nodes", headers=headers)
    second = client.post("/nodes", headers=headers)
    assert (first.status_code, first.json()) == (201, {"id": 1})
    assert (second.status_code, second.json()) == (201, {"id": 1})
    assert created == [1]
    assert set(redis.ttl.values()) == {600}


def test_without_key_every_request_acts() -> None:
    client, _, created = _client()
    client.post("/nodes")
    client.post("/nodes")
    assert created == [1, 2]


def test_failed_action_can_be_retried() -> None:
    client, redis, _created = _client()
    headers = {"Idempotency-Key": str(uuid.uuid4())}
    assert client.post("/nodes", headers=headers, params={"fail": True}).status_code == 500
    assert redis.data == {}
    assert client.post("/nodes", headers=headers).json() == {"id": 1}


def test_in_flight_duplicate_is_conflict() -> None:
    client, redis, _ = _client()
    key = uuid.uuid4()
    redis.data[f"idem:user-1:{key}"] = "pending"
    r = client.post("/nodes", headers={"Idempotency-Key": str(key)})
    assert (r.status_code, r.json()["code"]) == (409, "ALREADY_EXISTS")


def test_key_must_be_uuid() -> None:
    client, _, _ = _client()
    r = client.post("/nodes", headers={"Idempotency-Key": "abc"})
    assert (r.status_code, r.json()["code"]) == (422, "VALIDATION_FAILED")
