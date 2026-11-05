"""Справочники по умолчанию: фазы, дисциплины и профили, типы узлов с нормами, метки, валюты, НДС,
причины проигрыша, контрольное соотношение, ключи ``method.*``.

Ревизия: 0005_seed_dictionaries
Предыдущая: 0004_dictionaries
Задача PLAN.md: DB-010. Шаг: migrate (миграция данных).

Значения — SPEC v0.5: 2 и 6.3 (фазы, сквозная «Управление проектом»), 5.2 (типы, нормы, иконки,
профили дисциплин), 6.6 (QA к Бэкенд + Фронтенд 25–35 %), 7.5, BR-PRJ-05 (причины проигрыша),
BR-MONEY-03 (7 валют), BR-MONEY-05 и C-31 (НДС, по умолчанию 22 %), BR-PRJ-03 и Q-13 (180 дней),
BR-TREE-09 (пороги 80/40 ч). Ключи иконок — DESIGN.md (набор типов), ключи ``method.*`` и значения
по умолчанию — contracts/settings.schema.json.
Цвета и короткие имена дисциплин — как в моках FE-001.
Данные пишутся через ``sa.table`` (без SQL-строк со значениями, SEC-WEB-05); создатель — «Система»
(``created_by IS NULL``). ``downgrade`` удаляет все строки этих справочников.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from estimator.db.uuid7 import uuid7

revision: str = "0005_seed_dictionaries"
down_revision: str | None = "0004_dictionaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (название, сквозная). Порядок = sort_order.
PHASES = [
    ("Анализ и проектирование", False),
    ("Разработка", False),
    ("Тестирование", False),
    ("Внедрение", False),
    ("Гарантийная поддержка", False),
    ("Управление проектом", True),
]

#: (ключ иконки, название, нормы [(вариант, O, R, P)], системный)
NODE_TYPES = [
    ("module", "Модуль", [], False),
    ("function", "Функция", [], False),
    (
        "screen",
        "Экран",
        [("простой", "2", "4", "6"), ("средний", "5", "7", "10"), ("сложный", "12", "16", "24")],
        False,
    ),
    (
        "integration",
        "Интеграция",
        [("простая", "16", "24", "40"), ("сложная", "40", "60", "100")],
        False,
    ),
    ("report", "Отчёт", [("отчёт", "8", "12", "20")], False),
    ("entity", "Сущность", [("CRUD", "6", "8", "12")], False),
    ("service", "Сервис", [], False),
    ("test_suite", "Тест-набор", [("на кейс", "0.5", "1", "2")], False),
    ("document", "Документ", [("на раздел", "2", "4", "6")], False),
    ("work", "Работа", [], True),
]

#: (название, короткое, цвет, [(профиль, цепочка ключей типов)]); первый профиль — по умолчанию
DISCIPLINES = [
    (
        "Бэкенд",
        "BE",
        "#2f9e6e",
        [
            ("Модуль → Функция", ["module", "function"]),
            ("Сервис → Функция", ["service", "function"]),
            ("Плоский список функций", ["function"]),
        ],
    ),
    (
        "Фронтенд",
        "FE",
        "#d08a2f",
        [
            ("Экран", ["screen"]),
            ("Модуль → Экран", ["module", "screen"]),
            ("Функция", ["function"]),
        ],
    ),
    ("Аналитика", "Анал", "#7b61c9", [("Документ", ["document"]), ("Функция", ["function"])]),
    (
        "QA",
        "QA",
        "#c0504d",
        [("Тест-набор", ["test_suite"]), ("Функция", ["function"]), ("Экран", ["screen"])],
    ),
    (
        "Архитектура",
        "Арх",
        "#3e8ed0",
        [("Работа", ["work"]), ("Сервис", ["service"]), ("Интеграция", ["integration"])],
    ),
    ("DevOps", "DevOps", "#5f6b7a", [("Работа", ["work"]), ("Сервис", ["service"])]),
]

#: (название, короткое имя, цвет, категория статистики)
COMMENT_TAGS = [
    ("Ограничение", "Огр.", "#8a6d3b", "constraint"),
    ("Технология", "Тех.", "#3e8ed0", "tech"),
    ("Риск", "Риск", "#c0504d", "risk"),
    ("Допущение", "Допущение", "#7b61c9", "assumption"),
]

CURRENCIES = [
    ("RUB", "₽"),
    ("USD", "$"),
    ("EUR", "€"),
    ("CNY", "¥"),
    ("KZT", "₸"),
    ("BYN", "Br"),
    ("AED", "AED"),
]

#: (название, процент или None, по умолчанию)
VAT_RATES = [
    ("Без НДС", None, False),
    ("0%", "0", False),
    ("5%", "5", False),
    ("7%", "7", False),
    ("10%", "10", False),
    ("20%", "20", False),
    ("22%", "22", True),
]

#: (название, «Другое» — требует текст)
LOSS_REASONS = [
    ("Цена", False),
    ("Сроки", False),
    ("Выбран конкурент", False),
    ("Отказ от проекта", False),
    ("Другое", True),
]

#: Ключи method.* и значения по умолчанию (contracts/settings.schema.json, DB-D01)
METHOD_SETTINGS = {
    "method.large_leaf_hours": {"medium": 80, "detailed": 40},
    "method.medium_expected_units": {"min": 5, "max": 15},
    "method.pm_percent_default": 18,
    "method.autoarchive_days": 180,
}

#: Контрольное соотношение 6.6: (дисциплина A, дисциплины B, мин %, макс %)
CONTROL_RATIOS = [("QA", ["Бэкенд", "Фронтенд"], "25", "35")]

phases = sa.table(
    "phases",
    sa.column("id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("sort_order", sa.Integer),
    sa.column("is_cross_cutting", sa.Boolean),
)
node_types = sa.table(
    "node_types",
    sa.column("id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("icon", sa.Text),
    sa.column("norms", pg.JSONB),
    sa.column("is_system", sa.Boolean),
)
disciplines = sa.table(
    "disciplines",
    sa.column("id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("short_name", sa.String),
    sa.column("color", sa.String),
    sa.column("default_profile_id", pg.UUID),
)
discipline_profiles = sa.table(
    "discipline_profiles",
    sa.column("id", pg.UUID),
    sa.column("discipline_id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("type_chain", pg.ARRAY(pg.UUID)),
)
comment_tags = sa.table(
    "comment_tags",
    sa.column("id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("short_name", sa.String),
    sa.column("color", sa.String),
    sa.column("category", pg.ENUM(name="comment_tag_category", create_type=False)),
)
currencies = sa.table("currencies", sa.column("code", sa.String), sa.column("symbol", sa.String))
vat_rates = sa.table(
    "vat_rates",
    sa.column("id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("percent", sa.Numeric),
    sa.column("is_default", sa.Boolean),
)
loss_reasons = sa.table(
    "loss_reasons",
    sa.column("id", pg.UUID),
    sa.column("name", sa.String),
    sa.column("is_other", sa.Boolean),
)
control_ratios = sa.table(
    "control_ratios",
    sa.column("id", pg.UUID),
    sa.column("discipline_a_id", pg.UUID),
    sa.column("disciplines_b", pg.ARRAY(pg.UUID)),
    sa.column("min_pct", sa.Numeric),
    sa.column("max_pct", sa.Numeric),
)
system_settings = sa.table(
    "system_settings", sa.column("key", sa.Text), sa.column("value", pg.JSONB)
)

SEEDED_TABLES = (
    "control_ratios",
    "loss_reasons",
    "vat_rates",
    "currencies",
    "comment_tags",
    "discipline_profiles",
    "disciplines",
    "node_types",
    "phases",
)


def upgrade() -> None:
    op.bulk_insert(
        phases,
        [
            {"id": uuid7(), "name": name, "sort_order": i, "is_cross_cutting": cross}
            for i, (name, cross) in enumerate(PHASES, start=1)
        ],
    )

    type_ids: dict[str, object] = {}
    rows = []
    for icon, name, norms, system in NODE_TYPES:
        type_ids[icon] = uuid7()
        rows.append(
            {
                "id": type_ids[icon],
                "name": name,
                "icon": icon,
                "norms": [{"label": lbl, "o": o, "r": r, "p": p} for lbl, o, r, p in norms],
                "is_system": system,
            }
        )
    op.bulk_insert(node_types, rows)

    discipline_ids: dict[str, object] = {}
    disc_rows, profile_rows = [], []
    for name, short, color, profiles in DISCIPLINES:
        discipline_ids[name] = uuid7()
        profile_ids = [uuid7() for _ in profiles]
        disc_rows.append(
            {
                "id": discipline_ids[name],
                "name": name,
                "short_name": short,
                "color": color,
                "default_profile_id": profile_ids[0],
            }
        )
        for pid, (pname, chain) in zip(profile_ids, profiles, strict=True):
            profile_rows.append(
                {
                    "id": pid,
                    "discipline_id": discipline_ids[name],
                    "name": pname,
                    "type_chain": [type_ids[key] for key in chain],
                }
            )
    # Внешний ключ disciplines.default_profile_id отложенный (DEFERRABLE INITIALLY DEFERRED)
    op.bulk_insert(disciplines, disc_rows)
    op.bulk_insert(discipline_profiles, profile_rows)

    op.bulk_insert(
        comment_tags,
        [
            {"id": uuid7(), "name": n, "short_name": s, "color": c, "category": cat}
            for n, s, c, cat in COMMENT_TAGS
        ],
    )
    op.bulk_insert(currencies, [{"code": c, "symbol": s} for c, s in CURRENCIES])
    op.bulk_insert(
        vat_rates,
        [{"id": uuid7(), "name": n, "percent": p, "is_default": d} for n, p, d in VAT_RATES],
    )
    op.bulk_insert(
        loss_reasons, [{"id": uuid7(), "name": n, "is_other": o} for n, o in LOSS_REASONS]
    )
    op.bulk_insert(
        control_ratios,
        [
            {
                "id": uuid7(),
                "discipline_a_id": discipline_ids[a],
                "disciplines_b": [discipline_ids[b] for b in bs],
                "min_pct": lo,
                "max_pct": hi,
            }
            for a, bs, lo, hi in CONTROL_RATIOS
        ],
    )
    # Ключ мог уже записать администратор (повторная установка) — тогда не трогаем
    op.execute(
        pg.insert(system_settings)
        .values([{"key": k, "value": v} for k, v in METHOD_SETTINGS.items()])
        .on_conflict_do_nothing(index_elements=["key"])
    )


def downgrade() -> None:
    op.execute(system_settings.delete().where(system_settings.c.key.in_(list(METHOD_SETTINGS))))
    op.execute(sa.update(disciplines).values(default_profile_id=None))
    for name in SEEDED_TABLES:
        op.execute(sa.table(name).delete())
