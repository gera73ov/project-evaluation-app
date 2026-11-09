"""Позиции соседей — дробные ключи (fractional indexing, CORE-014; SPEC 14.2 ``nodes.position``).

Ключ — строка из алфавита ``0-9A-Za-z``; порядок — побайтовое сравнение (столбец ``position``
с ``COLLATE "C"``). Между любыми двумя ключами есть третий, поэтому вставка и перестановка не
перенумеровывают соседей.

Ключ = целая часть + дробная. Первый символ целой части задаёт её длину (``a`` — 2 символа,
``b`` — 3, …, ``z`` — 27; ``Z``…``A`` — то же вниз), поэтому дописывание в конец и в начало
растит ключ логарифмически: ``a0``…``az``, ``b00``…``bzz``, ``c000``… Дробная часть нужна для
вставки между соседями и не оканчивается на ``0``. Алгоритм — «Implementing Fractional
Indexing» (D. Greenspan), как в библиотеке fractional-indexing.
"""

from __future__ import annotations

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_INDEX = {c: i for i, c in enumerate(DIGITS)}
_SMALLEST_INTEGER = "A" + DIGITS[0] * 26
FIRST = "a" + DIGITS[0]


class PositionError(ValueError):
    """Ключи не упорядочены или ключ недопустим."""


def _integer_length(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise PositionError(f"недопустимый первый символ ключа: {head!r}")


def _integer_part(key: str) -> str:
    length = _integer_length(key[0])
    if length > len(key):
        raise PositionError(f"недопустимый ключ позиции: {key!r}")
    return key[:length]


def validate(key: str) -> None:
    if not key or any(c not in _INDEX for c in key):
        raise PositionError(f"недопустимый ключ позиции: {key!r}")
    if key == _SMALLEST_INTEGER:
        raise PositionError("ключ меньше всех допустимых")
    fraction = key[len(_integer_part(key)) :]
    if fraction.endswith(DIGITS[0]):
        raise PositionError(f"дробная часть ключа оканчивается на 0: {key!r}")


def _midpoint(a: str, b: str | None) -> str:
    """Дробная часть строго между ``a`` и ``b`` (``b=None`` — без верхней границы)."""
    while True:
        if b is not None:
            n = 0
            while (a[n] if n < len(a) else DIGITS[0]) == b[n]:
                n += 1
            if n > 0:
                return b[:n] + _midpoint(a[n:], b[n:])
        digit_a = _INDEX[a[0]] if a else 0
        digit_b = _INDEX[b[0]] if b is not None else len(DIGITS)
        if digit_b - digit_a > 1:
            return DIGITS[(digit_a + digit_b + 1) // 2]
        if b is not None and len(b) > 1:
            return b[0]
        # digit_a и следующий за ним: дописываем символ к a
        return DIGITS[digit_a] + _midpoint(a[1:], None)


def _increment(x: str) -> str | None:
    head, digits = x[0], list(x[1:])
    for i in reversed(range(len(digits))):
        d = _INDEX[digits[i]] + 1
        if d < len(DIGITS):
            digits[i] = DIGITS[d]
            return head + "".join(digits)
        digits[i] = DIGITS[0]
    if head == "Z":
        return "a" + DIGITS[0]
    if head == "z":
        return None
    new_head = chr(ord(head) + 1)
    if new_head > "a":
        digits.append(DIGITS[0])
    else:
        digits.pop()
    return new_head + "".join(digits)


def _decrement(x: str) -> str | None:
    head, digits = x[0], list(x[1:])
    for i in reversed(range(len(digits))):
        d = _INDEX[digits[i]] - 1
        if d >= 0:
            digits[i] = DIGITS[d]
            return head + "".join(digits)
        digits[i] = DIGITS[-1]
    if head == "a":
        return "Z" + DIGITS[-1]
    if head == "A":
        return None
    new_head = chr(ord(head) - 1)
    if new_head < "Z":
        digits.append(DIGITS[-1])
    else:
        digits.pop()
    return new_head + "".join(digits)


def key_between(before: str | None, after: str | None) -> str:
    """Ключ между соседями: ``before=None`` — в начало, ``after=None`` — в конец."""
    if before is not None:
        validate(before)
    if after is not None:
        validate(after)
    if before is not None and after is not None and before >= after:
        raise PositionError(f"ключи не упорядочены: {before!r} ≥ {after!r}")
    if before is None:
        if after is None:
            return FIRST
        ib = _integer_part(after)
        fb = after[len(ib) :]
        if ib == _SMALLEST_INTEGER:  # pragma: no cover — 62²⁶ вставок в начало
            return ib + _midpoint("", fb)
        if ib < after:
            return ib
        res = _decrement(ib)
        if res is None:  # pragma: no cover
            raise PositionError("нельзя вставить в начало")
        return res
    ia = _integer_part(before)
    fa = before[len(ia) :]
    if after is None:
        nxt = _increment(ia)
        return ia + _midpoint(fa, None) if nxt is None else nxt
    ib = _integer_part(after)
    fb = after[len(ib) :]
    if ia == ib:
        return ia + _midpoint(fa, fb)
    nxt = _increment(ia)
    if nxt is None:  # pragma: no cover
        raise PositionError("нельзя вставить ключ")
    if nxt < after:
        return nxt
    return ia + _midpoint(fa, None)


def keys_after(last: str | None, count: int) -> list[str]:
    """``count`` ключей подряд после ``last`` (в конец списка)."""
    keys: list[str] = []
    for _ in range(count):
        last = key_between(last, None)
        keys.append(last)
    return keys
