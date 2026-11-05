"""DB-003…DB-009: перечисления моделей совпадают со сводкой
contracts/db/schema.md раздел 7."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest

from estimator.db import enums

pytestmark = pytest.mark.spec("14.2")

SCHEMA_MD = Path(__file__).resolve().parents[4] / "contracts" / "db" / "schema.md"

MODEL_ENUMS: dict[str, type[StrEnum]] = {
    "user_source": enums.UserSource,
    "user_status": enums.UserStatus,
    "user_block_reason": enums.UserBlockReason,
    "system_role": enums.SystemRole,
    "role_source": enums.RoleSource,
    "auth_token_kind": enums.AuthTokenKind,
    "audit_result": enums.AuditResult,
    "node_type_proposal": enums.NodeTypeProposal,
    "comment_tag_category": enums.CommentTagCategory,
    "project_status": enums.ProjectStatus,
    "project_outcome": enums.ProjectOutcome,
    "quote_figure": enums.QuoteFigure,
    "detail_level": enums.DetailLevel,
    "project_role": enums.ProjectRole,
    "branch_status_value": enums.BranchStatusValue,
    "node_kind": enums.NodeKind,
    "node_action": enums.NodeAction,
    "thread_status": enums.ThreadStatus,
    "customer_question_status": enums.CustomerQuestionStatus,
    "message_kind": enums.MessageKind,
    "message_history_reason": enums.MessageHistoryReason,
    "addressee_type": enums.AddresseeType,
    "scan_status": enums.ScanStatus,
    "export_status": enums.ExportStatus,
}


def contract_enums() -> dict[str, list[str]]:
    text = SCHEMA_MD.read_text(encoding="utf-8").split("## 7. Перечисления", 1)[1]
    found = {}
    for name, values in re.findall(r"^\| `(\w+)` \| ([^|]+) \|", text, flags=re.M):
        found[name] = [v.strip() for v in values.split(",")]
    return found


@pytest.mark.parametrize("name", sorted(MODEL_ENUMS))
def test_enum_matches_contract(name: str) -> None:
    assert [m.value for m in MODEL_ENUMS[name]] == contract_enums()[name]
