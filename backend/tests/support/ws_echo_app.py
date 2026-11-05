"""Тестовое ASGI-приложение для самопроверки фикстур процессов (QA-001).

``/health/live`` — как у приложения; ``/ws`` — отвечает на сообщение строкой
``<PID процесса>:<сообщение>``, чтобы тест видел, к какому процессу подключён клиент.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, WebSocket

app = FastAPI()
PROCESS_ID = str(os.getpid())


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok", "pid": PROCESS_ID}


@app.websocket("/ws")
async def echo(websocket: WebSocket) -> None:
    await websocket.accept()
    while True:
        message = await websocket.receive_text()
        await websocket.send_text(f"{PROCESS_ID}:{message}")
