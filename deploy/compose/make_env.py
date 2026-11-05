"""Создать .env из .env.example со случайными паролями (INF-004, `make env`).

Существующий .env не трогается. Только стандартная библиотека Python 3.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RANDOM = {
    "POSTGRES_PASSWORD": lambda: secrets.token_hex(24),
    "REDIS_PASSWORD": lambda: secrets.token_hex(24),
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


def main() -> int:
    target = ROOT / ".env"
    if target.exists():
        print(".env уже есть, не меняю")
        return 0
    target.write_text(render((ROOT / ".env.example").read_text(encoding="utf-8")), encoding="utf-8")
    target.chmod(0o600)
    print("создан .env со случайными паролями")
    return 0


if __name__ == "__main__":
    sys.exit(main())
