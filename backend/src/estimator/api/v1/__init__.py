"""Зона трека API (API-контракт), PLAN.md раздел 5.

:data:`router` собирает роутеры доменов ``api/v1/*``; приложение подключает его под ``/api/v1``.
"""

from fastapi import APIRouter

from estimator.api.v1 import auth

PREFIX = "/api/v1"

router = APIRouter()
router.include_router(auth.router)
