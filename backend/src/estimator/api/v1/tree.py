"""Дерево проекта целиком (CORE-014; contracts/openapi.yaml «Дерево», ``GET /projects/{id}/tree``).

Ответ без денег (SEC-AUTHZ-04). Право ``tree.read`` проверяет gate ``ApiRouter``.

Ответ на 5 000 узлах — около 3,5 МБ JSON. :func:`load_tree` уже собирает его из примитивов JSON
по схеме ``Tree``, поэтому он отдаётся как есть, без повторной проверки и сериализации pydantic
(вдвое дольше; NFR-PERF-02). ``response_model`` остаётся для контракта OpenAPI, а совпадение
ответа со схемой проверяют тесты (``test_tree_body_matches_schema``).
"""

from __future__ import annotations

import json
import uuid

from fastapi import HTTPException, Response

from estimator.api.common.router import ApiRouter
from estimator.api.v1 import core_schemas as s
from estimator.auth.mfa_policy import ActivePrincipal
from estimator.db.models.projects import Project
from estimator.db.session import DbSession
from estimator.services.tree.load import load_tree

router = ApiRouter(tags=["Дерево"])


@router.get(
    "/projects/{id}/tree",
    permission="tree.read",
    response_model=s.Tree,
    response_model_exclude_unset=True,
)
async def get_tree(
    id: uuid.UUID,  # noqa: A002 — имя параметра из контракта
    principal: ActivePrincipal,
    db: DbSession,
) -> Response:
    project = await db.get(Project, id)
    if project is None:  # pragma: no cover — gate уже ответил 404
        raise HTTPException(404, detail={"code": "NOT_FOUND"})
    tree = await load_tree(db, project, principal.user_id)
    body = json.dumps(tree, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return Response(body.encode(), media_type="application/json")
