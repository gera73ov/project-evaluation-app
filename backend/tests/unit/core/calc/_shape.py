"""Перевод результата расчёта в форму ``expected`` фикстур и сравнение по правилам
contracts/fixtures/calc/README.md раздел 2 (ROUND_HALF_UP до числа знаков ожидаемой строки)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from estimator.domain.calc import (
    PM_ROW,
    DetailLevel,
    ProjectInput,
    QuoteFigure,
    calculate,
    calculate_money,
    project_cache,
    round_half_up,
)
from estimator.domain.calc.analytics import control_ratio, decomposition, shares, volumes
from estimator.domain.calc.project import ProjectResult

FIXTURES = Path(__file__).resolve().parents[5] / "contracts" / "fixtures" / "calc"
PORTAL = json.loads((FIXTURES / "portal-dilerov.json").read_text(encoding="utf-8"))
EDGE = json.loads((FIXTURES / "edge-cases.json").read_text(encoding="utf-8"))


def _places(expected: str) -> int:
    return len(expected.split(".")[1]) if "." in expected else 0


def assert_matches(actual: Any, expected: Any, path: str = "") -> None:
    """Рекурсивно сравнить: проверяются только ключи, которые есть в ожидании."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: ожидался объект, получено {actual!r}"
        for key, value in expected.items():
            if key == "from_spec":
                continue
            assert key in actual, f"{path}.{key}: нет в результате"
            assert_matches(actual[key], value, f"{path}.{key}")
    elif isinstance(expected, str) and isinstance(actual, Decimal):
        got = str(round_half_up(actual, _places(expected)))
        assert got == expected, f"{path}: {got} ≠ {expected} (точно {actual})"
    else:
        assert actual == expected, f"{path}: {actual!r} ≠ {expected!r}"


def _figures(f: Any) -> dict[str, Decimal]:
    return {"e": f.e, "sigma": f.sigma, "p80": f.p80, "p90": f.p90}


def _money_shape(money: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "quote_figure": money.quote_figure.value,
        "rates_missing": money.rates_missing,
        "vat_label": money.vat_label,
    }
    if money.rates_missing_text is not None:
        out["text"] = money.rates_missing_text
    if money.by_figure is not None:
        out["by_figure"] = {
            figure.value: {
                "k": block.k,
                "rows_rub": block.rows_rub,
                "total_rub": block.total_rub,
                "vat_rub": block.vat_rub,
                "total_with_vat_rub": block.total_with_vat_rub,
                "rows_cur": block.rows_cur,
                "total_cur": block.total_cur,
                "vat_cur": block.vat_cur,
                "total_with_vat_cur": block.total_with_vat_cur,
                "total_cur_overflow": block.overflow_cur,
            }
            for figure, block in money.by_figure.items()
        }
    return out


def shape(data: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    """Посчитать вход фикстуры и вернуть результат в форме ``expected``."""
    project_input = ProjectInput.from_dict(data)
    result = calculate(project_input)
    nodes: dict[str, Any] = {}
    leaves: dict[str, Any] = {}
    for node_id, node in result.tree.nodes.items():
        t = node.totals
        values: dict[str, Any] = {
            "e": t.e,
            "sigma": t.sigma,
            "p80": t.p80,
            "p90": t.p90,
            "sum_o": t.sum_o,
            "sum_r": t.sum_r,
            "sum_p": t.sum_p,
        }
        if node.leaf is not None:
            values["e_unit"] = node.leaf.e_unit
            leaves[node_id] = values
        nodes[node_id] = values
    out: dict[str, Any] = {
        "leaves": {"values": leaves},
        "nodes": {"values": nodes} if "values" in expected.get("nodes", {}) else nodes,
        "leaf_state": {r.node.id: r.leaf.state.value for r in result.tree.nodes.values() if r.leaf},
        "disciplines": {"values": {d: _figures(f) for d, f in result.disciplines.items()}},
        "phases": {"values": {p: _figures(f) for p, f in result.phases.items()}},
        "works": _with_values(
            expected,
            "works",
            {
                **_figures(result.works),
                "sigma_squared": result.works.sigma**2,
            },
        ),
        "pm": _with_values(
            expected,
            "pm",
            {
                **_figures(result.pm),
                "sigma_exact": result.pm.sigma,
                "base_e": result.pm.base_e,
            },
        ),
        "total": _with_values(
            expected,
            "total",
            {
                **_figures(result.total),
                "e_precise": result.total.e,
                "p80_precise": result.total.p80,
                "unaccounted_leaves": result.unaccounted_leaves,
            },
        ),
        "warning": {
            "unaccounted_leaves": result.unaccounted_leaves,
            "text": result.unaccounted_warning(),
        },
    }
    if "collapse_suggestion" in expected:
        node_id = expected["collapse_suggestion"]["node_id"]
        s = result.tree.collapse_suggestion(node_id)
        out["collapse_suggestion"] = {
            "node_id": node_id,
            "o": s.o,
            "r": s.r,
            "p": s.p,
            "multiplier": s.multiplier,
        }
    money = None
    if project_input.money is not None:
        money = calculate_money(result, project_input.money)
        out["money"] = _money_shape(money)
    cache = project_cache(result, money)
    out["cache"] = {"e": cache.e, "cost_rub": cache.cost_rub, "quote_cur": cache.quote_cur}
    sh = shares(result)
    all_none = all(v is None for v in sh.disciplines.values())
    out["shares"] = "not_computed" if all_none else "computed"
    if "analytics" in expected:
        out["analytics"] = _analytics(result, expected["analytics"])
    return out


def _with_values(expected: dict[str, Any], key: str, values: dict[str, Any]) -> dict[str, Any]:
    return {"values": values} if "values" in expected.get(key, {}) else values


def _analytics(result: ProjectResult, expected: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    ratio = expected.get("control_ratio_qa")
    if ratio is not None:
        cr = control_ratio(
            result,
            ratio["discipline_a"],
            ratio["disciplines_b"],
            Decimal(ratio["min_pct"]),
            Decimal(ratio["max_pct"]),
        )
        out["control_ratio_qa"] = {
            "discipline_a": cr.discipline_a,
            "disciplines_b": list(cr.disciplines_b),
            "min_pct": ratio["min_pct"],
            "max_pct": ratio["max_pct"],
            "pct": cr.pct,
            "verdict": cr.verdict.value if cr.verdict else None,
        }
    found = volumes(result)
    out["volumes"] = {name: found.get(name) for name in expected.get("volumes", {})}
    for key, level in (
        ("large_leaves_medium", DetailLevel.MEDIUM),
        ("large_leaves_detailed", DetailLevel.DETAILED),
    ):
        level_result = _with_level(result, level)
        d = decomposition(level_result)
        out[key] = {
            "threshold_hours": d.threshold_hours,
            "large": d.large,
            "repeating": d.repeating,
        }
        if level is result.input.detail_level:
            out["wide_fork_over_30pct"] = d.wide_forks
    return out


def _with_level(result: ProjectResult, level: DetailLevel) -> ProjectResult:
    from dataclasses import replace

    return calculate(replace(result.input, detail_level=level))


__all__ = ["EDGE", "PM_ROW", "PORTAL", "QuoteFigure", "assert_matches", "shape"]
