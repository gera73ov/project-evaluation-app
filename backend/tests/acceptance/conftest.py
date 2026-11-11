"""QA-002 · приёмочные сценарии SPEC 17.2 (pytest-bdd, уровень API).

* Тег ``@G-NN`` становится маркером ``gherkin("G-NN")`` — сценарий попадает в отчёт
  трассировки (tools/traceability.py).
* Тег ``@pending`` — шаги сценария ещё не реализованы: тест пропускается со статусом
  ``pending`` (итог прогона показывает «26 pending»). Трек, который реализует шаги
  (QA-012…QA-017), снимает тег в том же PR; шаг без определения тогда роняет тест.
* Тег ``@samba`` — сценарий идёт против Samba AD DC (``make test-ad``); без Samba пропускается.
* Теги ``@api`` и ``@ui`` — уровень проверки: ``@ui``-сценарии дополнительно проходят в
  Playwright (e2e/features/README.md).
"""

from __future__ import annotations

import re

import pytest

G_TAG = re.compile(r"G-\d{2}")
LAYER_TAGS = {"api", "ui"}

# Фикстуры приложения целиком (как у CORE и ADM), Samba AD и шаги сценариев (QA-012…QA-017).
from tests.acceptance.steps.ad_steps import *  # noqa: E402, F403
from tests.acceptance.steps.admin_steps import *  # noqa: E402, F403
from tests.acceptance.steps.auth_steps import *  # noqa: E402, F403
from tests.acceptance.steps.common import *  # noqa: E402, F403
from tests.acceptance.steps.cq_steps import *  # noqa: E402, F403
from tests.acceptance.steps.money_steps import *  # noqa: E402, F403
from tests.acceptance.steps.portfolio_steps import *  # noqa: E402, F403
from tests.acceptance.steps.tree_steps import *  # noqa: E402, F403
from tests.integration.core.conftest import (  # noqa: E402, F401
    api,
    clock,
    encryption_key,
    events,
    world,
)
from tests.integration.rt.conftest import stage  # noqa: E402, F401
from tests.support.samba import samba, samba_env  # noqa: E402, F401


def pytest_bdd_apply_tag(tag: str, function):  # type: ignore[no-untyped-def]
    """Превратить теги сценария в зарегистрированные маркеры (иначе --strict-markers упадёт)."""
    if G_TAG.fullmatch(tag):
        pytest.mark.gherkin(tag)(function)
        return True
    if tag == "pending":
        pytest.mark.pending(function)
        pytest.mark.skip(reason="pending: шаги сценария не реализованы")(function)
        return True
    if tag == "samba":
        pytest.mark.samba(function)  # нужен Samba AD (make test-ad); без него шаг пропускает
        return True
    if tag in LAYER_TAGS:
        return True  # уровень проверки — только метка в .feature
    return None


def pytest_report_teststatus(report: pytest.TestReport, config: pytest.Config):  # type: ignore[no-untyped-def]
    """Пропущенный ``@pending``-сценарий считается в итоге отдельно: «N pending»."""
    if report.skipped and "pending" in report.keywords:
        return "pending", "P", "PENDING"
    return None
