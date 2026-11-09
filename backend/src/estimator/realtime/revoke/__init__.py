"""RT-008 · отзыв доступа и завершение сессий в WebSocket (FR-SESS-02, FR-SESS-05, BR-ROLE-06).

Два пути, оба укладываются в 5 секунд:

1. **Сразу.** Сервис сессий AUTH-002 после ``COMMIT`` сообщает о завершённой сессии (выход,
   отзыв, блокировка, смена пароля, смена режима входа). Слушатель :func:`session_ended_message`
   превращает это в сообщение ``rt:control``; каждый экземпляр API отправляет ``session.ended``
   в ``user:{id}`` соединениям этой сессии и закрывает их кодом 4401.
2. **Перепроверка.** Каждое соединение раз в ``revalidate_seconds`` (по умолчанию 2 с) заново
   проверяет сессию без продления (истечение по бездействию и абсолютному сроку, блокировка,
   удаление пользователя) и права на каждый подписанный проект по актуальным данным БД:
   исключение из команды, снятие ролей, конец режима поддержки, проект в «Подготовке» для
   эксперта — ``access.revoked`` и отписка от каналов проекта; пропавший TOTP-гейт или
   ``money.read`` — тихое снятие ``:money``/``:notes``. Событие ``member.updated`` о самом
   подписчике запускает перепроверку его соединения немедленно.

Смена системных ролей сессию не завершает (AUTH её не отзывает): действует через перепроверку
прав — пропавшие проекты получают ``access.revoked`` (толкование FR-SESS-05).
"""

from __future__ import annotations

from typing import Any

from estimator.auth.sessions import SessionEnded

#: ``sessions.revoke_reason`` → ``session.ended.reason`` (contracts/ws-events.schema.json)
REVOKE_TO_ENDED = {
    "logout": "logged_out",
    "expired": "idle_timeout",
    "user_revoked": "revoked",
    "blocked": "user_blocked",
    "password_changed": "password_changed",
    "ad_check": "user_blocked",
    "mode_switch": "auth_mode_switched",
    "superseded": "revoked",
}
#: Причина отказа :func:`estimator.auth.context.resolve_principal` → ``session.ended.reason``
UNAUTH_TO_ENDED = {
    "idle": "idle_timeout",
    "absolute": "absolute_timeout",
    "pre_mfa_limit": "idle_timeout",
    "blocked": "user_blocked",
}
DEFAULT_ENDED = "revoked"

CONTROL_SESSION_ENDED = "session_ended"


def ended_reason(revoke_reason: str) -> str:
    return REVOKE_TO_ENDED.get(revoke_reason, DEFAULT_ENDED)


def session_ended_message(event: SessionEnded) -> dict[str, Any]:
    """Сообщение ``rt:control`` о завершённой сессии (без идентификатора сессии — только хэш)."""
    return {
        "kind": CONTROL_SESSION_ENDED,
        "user_id": str(event.user_id),
        "session_hash": event.session_hash.hex(),
        "reason": ended_reason(event.reason),
    }
