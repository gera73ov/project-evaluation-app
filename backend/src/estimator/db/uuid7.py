"""UUID версии 7 (RFC 9562), генерируется приложением (DB-002; contracts/db/schema.md G-2).

Первичные ключи без ``DEFAULT`` в БД: идентификатор задаёт приложение до вставки, поэтому его можно
вернуть клиенту и записать в событие до commit. UUID v7 начинается с времени в миллисекундах, значит
ключи растут монотонно: индекс B-tree не фрагментируется, курсорная пагинация по ``id`` идёт
в порядке создания (``project_journal``, contracts/db/schema.md раздел 3).

Монотонность внутри одной миллисекунды обеспечивает 12-битный счётчик в поле ``rand_a``
(RFC 9562, 6.2, метод 1). Счётчик стартует со случайного значения в младшей половине диапазона,
чтобы оставался запас; при переполнении время сдвигается на 1 мс вперёд.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_COUNTER_BITS = 12
_COUNTER_MAX = (1 << _COUNTER_BITS) - 1

_lock = threading.Lock()
_last_ms = -1
_counter = 0


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _next_state(now_ms: int) -> tuple[int, int]:
    """Следующая пара (миллисекунды, счётчик), не меньше предыдущей."""
    global _last_ms, _counter
    if now_ms > _last_ms:
        _last_ms = now_ms
        _counter = secrets.randbits(_COUNTER_BITS - 1)
    elif _counter < _COUNTER_MAX:
        # та же миллисекунда или часы ушли назад: продолжаем от последнего значения
        _counter += 1
    else:
        _last_ms += 1
        _counter = 0
    return _last_ms, _counter


def from_parts(unix_ms: int, counter: int, rand_b: int) -> uuid.UUID:
    """Собрать UUID v7 из частей (для тестов и :func:`uuid7`)."""
    if not 0 <= unix_ms < (1 << 48):
        raise ValueError("время вне диапазона 48 бит")
    if not 0 <= counter <= _COUNTER_MAX:
        raise ValueError("счётчик вне диапазона 12 бит")
    value = (unix_ms << 80) | (0x7 << 76) | (counter << 64) | (0b10 << 62)
    value |= rand_b & ((1 << 62) - 1)
    return uuid.UUID(int=value)


def uuid7() -> uuid.UUID:
    """Новый UUID v7; внутри процесса значения строго возрастают."""
    with _lock:
        unix_ms, counter = _next_state(_now_ms())
    return from_parts(unix_ms, counter, secrets.randbits(62))


def timestamp_ms(value: uuid.UUID) -> int:
    """Миллисекунды Unix из UUID v7."""
    if value.version != 7:
        raise ValueError("ожидался UUID версии 7")
    return value.int >> 80
