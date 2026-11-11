"""Общее для шагов приёмочных сценариев: асинхронные шаги в синхронном pytest-bdd и состояние
сценария между шагами."""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
import pytest


@pytest.fixture
async def bdd_loop() -> asyncio.AbstractEventLoop:
    """Цикл событий теста: шаги pytest-bdd синхронные, а БД и API — асинхронные."""
    return asyncio.get_running_loop()


def aio(step: Callable[..., Coroutine[object, object, None]]) -> Callable[..., None]:
    """Асинхронный шаг → синхронный: выполняется в цикле событий теста (``bdd_loop``)."""
    sig = inspect.signature(step)

    @functools.wraps(step)
    def run(**kwargs: object) -> None:  # pytest-bdd передаёт аргументы шага по именам
        loop = kwargs.pop("bdd_loop")
        assert isinstance(loop, asyncio.AbstractEventLoop)
        loop.run_until_complete(step(**kwargs))

    params = [*sig.parameters.values(),
              inspect.Parameter("bdd_loop", inspect.Parameter.POSITIONAL_OR_KEYWORD)]  # fmt: skip
    run.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]
    return run


class Scene:
    """Состояние сценария между шагами (QA-013…QA-017): проект, узлы, ответы API."""

    def __init__(self) -> None:
        self.s: Any = None  # Setup проекта (tests.integration.core.test_nodes_api)
        self.nodes: dict[str, dict[str, Any]] = {}
        self.responses: dict[str, httpx.Response] = {}
        self.data: dict[str, Any] = {}


@pytest.fixture
def scene() -> Scene:
    return Scene()
