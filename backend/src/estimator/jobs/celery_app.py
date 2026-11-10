"""Celery-приложение (INF-008; SPEC 13.1, 13.2).

Брокер — Redis, результаты задач не хранятся (ничего не читает их обратно). Расписания
считаются в часовом поясе приложения (FR-UI-02). Модули задач треков перечислены в
:data:`TASK_MODULES`; периодические задачи регистрируются в :mod:`estimator.jobs.schedule`.

Запуск: ``celery -A estimator.jobs.celery_app worker`` и
``celery -A estimator.jobs.celery_app beat -S estimator.jobs.schedule:LockedScheduler``.
"""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path
from typing import Any

from celery import Celery
from celery.signals import setup_logging
from redis import Redis

from estimator.config import Settings, get_settings
from estimator.logging import configure_logging

#: Очереди. Трек, которому нужна своя очередь (например, тяжёлые выгрузки EXP), добавляет её
#: сюда, в compose — отдельный worker с ``-Q <очередь>``.
QUEUES: tuple[str, ...] = ("default",)

#: Модули с задачами треков (``estimator.<трек>.tasks``); подключаются при старте worker.
TASK_MODULES: tuple[str, ...] = (
    "estimator.jobs.builtin",
    "estimator.db.tasks",
    "estimator.notifications.tasks",
    "estimator.security.tasks",
    "estimator.security.alerts.tasks",
    "estimator.security.siem.tasks",
    "estimator.realtime.tasks",
    "estimator.services.trash.tasks",
    "estimator.services.projects.totals",
)


def make_celery(settings: Settings | None = None) -> Celery:
    """Создать Celery-приложение по настройкам процесса."""
    settings = settings or get_settings()
    app = Celery("estimator", include=list(TASK_MODULES))
    app.conf.update(
        broker_url=settings.celery_broker_url.get_secret_value(),
        broker_connection_retry_on_startup=True,
        task_default_queue=QUEUES[0],
        task_ignore_result=True,
        result_backend=None,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone=settings.app_timezone,
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        worker_hijack_root_logger=False,
        worker_send_task_events=False,
        beat_max_loop_interval=10,
        # файловая система контейнера только для чтения, кроме временного каталога (SEC-SDLC-04)
        beat_schedule_filename=str(Path(tempfile.gettempdir()) / "celerybeat-schedule"),
    )
    from estimator.jobs.schedule import build_beat_schedule

    # Модули треков регистрируют свои периодические задачи при импорте (register_periodic),
    # поэтому импортируем их до сборки расписания, а не лениво при старте worker.
    for module in TASK_MODULES:
        importlib.import_module(module)
    app.conf.beat_schedule = build_beat_schedule()
    from estimator.security.alerts import notify as alerts

    alerts.install()  # события аудита в задачах (проверка цепочки) оповещают ИБ (SEC-011)
    return app


@setup_logging.connect
def _setup_logging(**_kwargs: Any) -> None:
    """Логи worker и beat — в тот же JSON-формат (NFR-MNT-04)."""
    configure_logging(get_settings().log_level)


def queue_lengths(settings: Settings) -> dict[str, int]:
    """Длина очередей Celery в Redis (для метрики SPEC 18.4)."""
    client = Redis.from_url(
        settings.celery_broker_url.get_secret_value(),
        socket_timeout=0.5,
        socket_connect_timeout=0.5,
    )
    try:
        return {queue: int(client.llen(queue)) for queue in QUEUES}
    finally:
        client.close()


celery_app = make_celery()
app = celery_app  # имя, которое ищет ``celery -A``
