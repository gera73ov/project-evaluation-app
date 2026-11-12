"""Кэш расчёта проекта в памяти экземпляра API для ответа правки (SPEC 15.3, NFR-PERF-03,
ARCH-02; QA-019).

Ответу ``PATCH /nodes/{id}`` и ``POST /projects/{id}/nodes`` нужны итоги узла, его предков и
проекта. Полный пересчёт на 2 000 узлах — это чтение всех строк и расчёт, около 50 мс процессора,
и всё это время стоит цикл событий экземпляра. Поэтому экземпляр держит последнее состояние
расчёта проекта (:class:`~estimator.domain.calc.incremental.CalcState`) с версией проекта.

Как состояние догоняет версию в БД. Каждое изменение проекта — это ``version++`` и строка
``change_log`` с событием (ARCH-02); по тем же событиям догоняют дерево клиенты. Экземпляр читает
события после своей версии: если там только правки и создания узлов (:data:`NODE_EVENTS`) и
события, которые на часы не влияют (:data:`NEUTRAL_EVENTS`), он перечитывает из БД только эти
узлы и пересчитывает их и предков (:func:`~estimator.domain.calc.incremental.refresh`). Правки
с других реплик так тоже подхватываются. Любое другое событие (перенос, удаление,
восстановление, копирование, статус ветки, параметры проекта), пропуск версии, слишком длинный
хвост, другие фазы, дисциплины или статусы веток в БД — и состояние строится заново по всем
узлам, как раньше.

Состояние запоминается только после commit транзакции (:func:`after_commit`): при откате версия
достанется другой транзакции, и чужое состояние под ней было бы неверным.
"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from estimator.db.models.projects import Project
from estimator.db.models.tree import ChangeLog, Node
from estimator.db.session import after_commit
from estimator.domain import calc
from estimator.domain.calc import incremental
from estimator.metrics import counter

if TYPE_CHECKING:
    from estimator.services.tree.load import DisciplineRow, PhaseRow

#: События, после которых достаточно перечитать узел ``data.node.id`` и пересчитать его предков
NODE_EVENTS = frozenset({"node.updated", "node.created"})
#: События проекта, которые не меняют ни узлы, ни параметры расчёта
NEUTRAL_EVENTS = frozenset({
    "message.created", "message.updated", "thread.created", "thread.resolved", "thread.reopened",
    "customer_question.updated", "member.updated", "document.scanned", "money.updated",
})  # fmt: skip
#: Длиннее — дешевле построить заново
MAX_DELTA = 200
#: Сколько проектов держит экземпляр (на 5 000 узлах состояние — единицы МБ)
MAX_PROJECTS = 32
#: Предел возраста состояния, с. Страховка: изменение мимо ``change_log`` проживёт не дольше
MAX_AGE = 300.0

_RESULTS = counter(
    "estimator_calc_cache_total",
    "Расчёт проекта для ответа правки: hit — версия совпала, delta — догнали по change_log, "
    "rebuild — построили заново",
    ["result"],
)


@dataclass(frozen=True)
class Snapshot:
    version: int
    meta: Hashable  # параметры расчёта помимо узлов (:func:`fingerprint`)
    state: incremental.CalcState
    at: float  # time.monotonic() постройки


_snapshots: OrderedDict[uuid.UUID, Snapshot] = OrderedDict()
_clock: Callable[[], float] = time.monotonic


def clear() -> None:
    """Забыть все состояния (тесты)."""
    _snapshots.clear()


def remember(project_id: uuid.UUID, snapshot: Snapshot) -> None:
    """Запомнить состояние, если оно не старее уже известного."""
    known = _snapshots.get(project_id)
    if known is not None and known.version > snapshot.version:
        return
    _snapshots[project_id] = snapshot
    _snapshots.move_to_end(project_id)
    while len(_snapshots) > MAX_PROJECTS:
        _snapshots.popitem(last=False)


def fingerprint(
    project: Project,
    phases: Sequence[PhaseRow],
    disciplines: Sequence[DisciplineRow],
    statuses: Mapping[tuple[uuid.UUID, uuid.UUID], str],
) -> Hashable:
    """Всё, что кроме узлов входит в расчёт (:func:`~estimator.services.tree.load.calc_input`)."""
    return (
        project.pm_percent,
        str(project.quote_figure),
        str(project.detail_level),
        tuple((p.phase_id, p.is_cross_cutting, p.is_enabled, p.in_pm_base) for p in phases),
        tuple((d.discipline_id, d.name) for d in disciplines),
        tuple(sorted((str(ph), str(d), s) for (ph, d), s in statuses.items())),
    )


async def project_state(
    db: AsyncSession,
    project: Project,
    meta: Hashable,
    build: Callable[[Sequence[Any]], calc.ProjectInput],
    columns: Sequence[str],
) -> incremental.CalcState:
    """Состояние расчёта проекта на ``project.version`` (версия уже с правками транзакции).

    ``build`` — вход расчёта из строк узлов (колонки ``columns``); нужен и для догона по
    изменённым строкам, и для полной постройки.
    """
    snapshot = _snapshots.get(project.id)
    state = None
    if (
        snapshot is not None
        and snapshot.meta == meta
        and snapshot.version <= project.version
        and _clock() - snapshot.at < MAX_AGE
    ):
        if snapshot.version == project.version:
            state, result = snapshot.state, "hit"
        else:
            state, result = await _catch_up(db, project, snapshot, build, columns), "delta"
    if state is None:
        rows = await _live_rows(db, project.id, columns)
        state, result = incremental.build(build(rows)), "rebuild"
    _RESULTS.labels(result).inc()
    project_id, fresh = project.id, Snapshot(project.version, meta, state, _clock())
    after_commit(db, lambda: remember(project_id, fresh))  # объект проекта после commit истёк
    return state


async def _catch_up(
    db: AsyncSession,
    project: Project,
    snapshot: Snapshot,
    build: Callable[[Sequence[Any]], calc.ProjectInput],
    columns: Sequence[str],
) -> incremental.CalcState | None:
    """Догнать состояние по ``change_log``; ``None`` — хвост не годится, строить заново."""
    if project.version - snapshot.version > MAX_DELTA:
        return None
    log = (
        await db.execute(
            select(
                ChangeLog.version,
                ChangeLog.event["event"].astext,
                ChangeLog.event["data"]["node"]["id"].astext,
            )
            .where(
                ChangeLog.project_id == project.id,
                ChangeLog.version > snapshot.version,
                ChangeLog.version <= project.version,
            )
            .order_by(ChangeLog.version)
        )
    ).all()
    if [v for v, _, _ in log] != list(range(snapshot.version + 1, project.version + 1)):
        return None  # версия без события: что изменилось — неизвестно
    ids: set[uuid.UUID] = set()
    for _, event, node_id in log:
        if event in NODE_EVENTS and node_id:
            ids.add(uuid.UUID(node_id))
        elif event not in NEUTRAL_EVENTS:
            return None
    if not ids:
        return snapshot.state
    table = Node.__table__
    rows = (
        await db.execute(
            select(*(table.c[name] for name in columns)).where(
                table.c.id.in_(ids), table.c.project_id == project.id, table.c.deleted_at.is_(None)
            )
        )
    ).all()
    if len(rows) != len(ids):
        return None  # узел успели удалить — это уже не правка
    try:
        return incremental.refresh(snapshot.state, build(rows).nodes)
    except calc.TreeError:
        return None


async def _live_rows(db: AsyncSession, project_id: uuid.UUID, columns: Sequence[str]) -> list[Any]:
    from estimator.services.tree.load import live_nodes

    return await live_nodes(db, project_id, columns)
