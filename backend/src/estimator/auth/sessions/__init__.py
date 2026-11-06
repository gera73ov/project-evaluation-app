"""Серверные сессии (AUTH-002): сервис в :mod:`.service`, cookie в :mod:`.cookie`."""

from estimator.auth.sessions.cookie import (
    BACKGROUND_HEADER,
    COOKIE_NAME,
    clear_session_cookie,
    is_background,
    session_id_from,
    set_session_cookie,
)
from estimator.auth.sessions.service import (
    ExpiryReason,
    LoadedSession,
    RevokeReason,
    SessionEnded,
    SessionInfo,
    SessionRecord,
    SessionService,
    add_session_ended_listener,
    id_hash,
    remove_session_ended_listener,
)

__all__ = [
    "BACKGROUND_HEADER",
    "COOKIE_NAME",
    "ExpiryReason",
    "LoadedSession",
    "RevokeReason",
    "SessionEnded",
    "SessionInfo",
    "SessionRecord",
    "SessionService",
    "add_session_ended_listener",
    "clear_session_cookie",
    "id_hash",
    "is_background",
    "remove_session_ended_listener",
    "session_id_from",
    "set_session_cookie",
]
