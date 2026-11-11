"""Создать .env из .env.example со случайными паролями (INF-004, `make env`).

Существующий .env не переписывается: в него только добавляются переменные, которых в нём ещё
нет (новые пароли — случайные). Только стандартная библиотека Python 3.
"""

from __future__ import annotations

import base64
import secrets
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _encryption_key() -> str:
    """Мастер-ключ SEC-003 в формате ``<id>:<base64url 32 байта>``."""
    raw = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    return f"{datetime.now(UTC):k%Y%m%d}:{raw}"


RANDOM = {
    "ENCRYPTION_KEY": _encryption_key,
    "POSTGRES_PASSWORD": lambda: secrets.token_hex(24),
    "REDIS_PASSWORD": lambda: secrets.token_hex(24),
    "BACKUP_CIPHER_PASSWORD": lambda: secrets.token_hex(32),
    # политика паролей AD: заглавные, строчные, цифры
    "SAMBA_ADMIN_PASSWORD": lambda: f"Est-{secrets.token_hex(12)}-9",
    "SAMBA_TEST_PASSWORD": lambda: f"Est-{secrets.token_hex(12)}-9",
}


def render(example: str) -> str:
    lines = []
    for line in example.splitlines():
        name = line.split("=", 1)[0]
        lines.append(f"{name}={RANDOM[name]()}" if name in RANDOM else line)
    return "\n".join(lines) + "\n"


def missing(example: str, current: str) -> list[str]:
    """Строки ``.env.example`` с переменными, которых в ``current`` нет (новые со временем)."""
    have = {line.split("=", 1)[0] for line in current.splitlines() if "=" in line}
    rendered = render(example).splitlines()
    return [line for line in rendered if "=" in line and not line.startswith("#")
            and line.split("=", 1)[0] not in have]  # fmt: skip


def main() -> int:
    target = ROOT / ".env"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    if target.exists():
        current = target.read_text(encoding="utf-8")
        added = missing(example, current)
        if not added:
            print(".env уже есть, не меняю")
            return 0
        tail = "" if current.endswith("\n") or not current else "\n"
        target.write_text(current + tail + "\n".join(added) + "\n", encoding="utf-8")
        names = ", ".join(line.split("=", 1)[0] for line in added)
        print(f".env дополнен новыми переменными: {names}")
        return 0
    target.write_text(render(example), encoding="utf-8")
    target.chmod(0o600)
    print("создан .env со случайными паролями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
