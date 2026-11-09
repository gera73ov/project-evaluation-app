"""Зона трека API (API-контракт), PLAN.md раздел 5.

:data:`router` собирает роутеры доменов ``api/v1/*``; приложение подключает его под ``/api/v1``.
"""

from fastapi import APIRouter

from estimator.api.v1 import (
    admin_calendar,
    auth,
    disciplines,
    me,
    members,
    node_types,
    notifications,
    projects,
    tree,
    view_state,
)

PREFIX = "/api/v1"

router = APIRouter()
router.include_router(auth.router)
router.include_router(me.router)
router.include_router(view_state.router)
router.include_router(projects.router)
router.include_router(tree.router)
router.include_router(members.router)
router.include_router(disciplines.router)
router.include_router(node_types.router)
router.include_router(notifications.router)
router.include_router(admin_calendar.router)
