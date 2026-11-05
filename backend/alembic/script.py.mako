"""${message}

Ревизия: ${up_revision}
Предыдущая: ${down_revision | comma,n}
Создана: ${create_date}

Задача PLAN.md: <ID>. Шаг: expand | migrate | contract (alembic/README.md).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "raise NotImplementedError"}


def downgrade() -> None:
    # Обязателен (DB-002): `alembic downgrade base` проверяется в CI.
    ${downgrades if downgrades else "raise NotImplementedError"}
