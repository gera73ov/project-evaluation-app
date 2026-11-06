"""CSRF (SEC-007; SEC-WEB-04, contracts/api-conventions.md раздел 3).

Токен создаётся вместе с сессией (``SessionRecord.csrf``) и отдаётся в cookie ``__Host-csrf``
(не HttpOnly — её читает фронтенд). Изменяющий запрос (``POST``, ``PUT``, ``PATCH``, ``DELETE``)
несёт тот же токен в заголовке ``X-CSRF-Token``; сервер сравнивает его с токеном сессии, а не
с cookie, поэтому подложенная cookie не помогает. Проверку вызывают зависимости сессии
(:mod:`estimator.auth.mfa_policy`) после проверки сессии и подключения TOTP.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, Response

CSRF_COOKIE = "__Host-csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class CsrfError(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=403, detail={"code": "CSRF_FAILED"})


def set_csrf_cookie(response: Response, token: str) -> None:
    response.set_cookie(CSRF_COOKIE, token, path="/", secure=True, httponly=False,
                        samesite="strict")  # fmt: skip


def clear_csrf_cookie(response: Response) -> None:
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="strict")


def check_csrf(request: Request, session_token: str) -> None:
    """403 ``CSRF_FAILED``, если изменяющий запрос не несёт токен своей сессии."""
    if request.method.upper() in SAFE_METHODS:
        return
    sent = request.headers.get(CSRF_HEADER, "")
    if not sent or not session_token or not hmac.compare_digest(sent, session_token):
        raise CsrfError
