"""Cookie сессии ``__Host-session`` (FR-SESS-01).

Префикс ``__Host-`` требует ``Secure``, ``Path=/`` и запрещает ``Domain``: cookie не уходит на
поддомены и не перезаписывается по HTTP. ``Max-Age`` не задаётся — срок проверяет сервер.
"""

from __future__ import annotations

from fastapi import Request, Response

COOKIE_NAME = "__Host-session"
BACKGROUND_HEADER = "X-Background"


def set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        session_id,
        path="/",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", secure=True, httponly=True, samesite="strict")


def session_id_from(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME) or None


def is_background(request: Request) -> bool:
    """Запрос не продлевает сессию: heartbeat, фоновые опросы (FR-SESS-02)."""
    return request.headers.get(BACKGROUND_HEADER, "").strip() == "1"
