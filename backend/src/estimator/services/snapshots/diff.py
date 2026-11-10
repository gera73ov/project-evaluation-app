"""CORE-061 · сравнение со снимком (SPEC FR-SNAP-03, FR-SNAP-04, 11.12 №1–4, TC-SNAP-01; 15.2
``GET /snapshots/{id}/diff?with=``; CR-008).

``base`` — снимок ``{id}``, ``with`` — другой снимок того же проекта (в том числе «ошибочный») или
текущее состояние (``current``). Все разницы — ``with − base``. Обе стороны — ``payload`` снимка
(текущее состояние собирается тем же :func:`~estimator.services.snapshots.capture`), часы
пересчитываются одним расчётным модулем, поэтому стороны сопоставимы.

* Узлы сопоставляются по id (FR-SNAP-04): только в ``with`` — «добавлен», только в ``base`` —
  «удалён»; изменились название, O/R/P, ×N, тип или комментарий — «изменён» (``fields`` —
  что именно); иначе сменились родитель, позиция, фаза или дисциплина — «перемещён». Строки без
  собственных изменений (у предка поменялась только сумма) не выводятся.
* ``delta_e`` — по E узла (сумма листьев); итоги — ``totals_delta``. Пересчёт УП — строкой ``pm``.
* Автор и время последней правки — со стороны ``with`` (для удалённого — ``base``).
* ``params`` — процент УП, «Цифра для КП», включённые фазы и фазы в базе УП; денежные строки
  (ставки, валюта, курс, НДС) и блок ``money`` — только с ``money.read`` (BR-MONEY-01).
* ``money``: «в КП» без НДС каждой стороны; по строкам — разница стоимости по E (E узла × ставка
  дисциплины), строка УП — с ``node_id: null``; влияние ставок — итог ``with`` по ставкам
  ``with`` минус итог ``with`` по ставкам ``base``; влияние курса — «в КП» ``with`` в валюте
  минус тот же итог в рублях по курсу ``base``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from estimator.api.common.decimal import format_decimal
from estimator.domain import calc
from estimator.services.common import hours, user_ref
from estimator.services.money import snapshot as snapshot_money
from estimator.services.snapshots import recalc

CONTENT_FIELDS = (
    ("title", "title"),
    ("o", "o"),
    ("r", "r"),
    ("p", "p"),
    ("multiplier", "multiplier"),
    ("type_id", "type"),
    ("comment_lines", "comment"),
)
MOVE_FIELDS = (
    ("parent_id", "parent"),
    ("position", "position"),
    ("phase_id", "phase"),
    ("discipline_id", "discipline"),
)
ZERO = Decimal(0)


@dataclass(frozen=True)
class Side:
    snapshot_id: str | None
    label: str
    payload: Mapping[str, Any]
    money: Mapping[str, Any] | None


def _signed_hours(value: Decimal) -> str:
    return hours(value) or "0.00"


def _money_dec(value: Decimal | None) -> str | None:
    return None if value is None else format_decimal(calc.round_half_up(value, 0))


def _node_e(result: calc.ProjectResult, node_id: str) -> Decimal:
    found = result.tree.nodes.get(node_id)
    return ZERO if found is None else found.totals.e


def _estimate(node: Mapping[str, Any], result: calc.ProjectResult) -> dict[str, Any]:
    found = result.tree.nodes.get(node["id"])
    leaf = found is not None and found.is_leaf
    return {
        "o": node["o"] if leaf else None,
        "r": node["r"] if leaf else None,
        "p": node["p"] if leaf else None,
        "multiplier": max(1, int(node["multiplier"] or 1)),
        "e": hours(_node_e(result, node["id"])) or "0.00",
    }


def _names(payload: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    phases = {p["id"]: p["name"] for p in payload["phases"]}
    disciplines = {d["id"]: d["name"] for d in payload["disciplines"]}
    return phases, disciplines


def _title(node: Mapping[str, Any], payload: Mapping[str, Any]) -> str:
    if node["title"]:
        return str(node["title"])
    phases, disciplines = _names(payload)
    if node["kind"] == "phase":
        return phases.get(node["phase_id"], "")
    if node["kind"] == "discipline" and node["discipline_id"]:
        return disciplines.get(node["discipline_id"], "")
    return ""


def _path(node: Mapping[str, Any], payload: Mapping[str, Any]) -> list[str]:
    by_id = {n["id"]: n for n in payload["nodes"]}
    out: list[str] = []
    parent = node["parent_id"]
    seen: set[str] = set()
    while parent and parent in by_id and parent not in seen:
        seen.add(parent)
        out.append(_title(by_id[parent], payload))
        parent = by_id[parent]["parent_id"]
    return list(reversed(out))


def _author(node: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any] | None:
    uid = node.get("updated_by")
    if not uid:
        return None
    return user_ref(uid, payload.get("users", {}).get(uid, "?"))  # type: ignore[arg-type]


def _rows(base: Side, with_: Side, rb: calc.ProjectResult, rw: calc.ProjectResult) -> list[dict]:
    nb = {n["id"]: n for n in base.payload["nodes"]}
    nw = {n["id"]: n for n in with_.payload["nodes"]}
    rows: list[dict[str, Any]] = []
    for node_id in nb.keys() | nw.keys():
        before, after = nb.get(node_id), nw.get(node_id)
        if before is None:
            change, fields = "added", []
        elif after is None:
            change, fields = "removed", []
        else:
            fields = [name for key, name in CONTENT_FIELDS if before.get(key) != after.get(key)]
            moved = [name for key, name in MOVE_FIELDS if before.get(key) != after.get(key)]
            if fields:
                change, fields = "changed", fields + moved
            elif moved:
                change, fields = "moved", moved
            else:
                continue
        node: Mapping[str, Any] = after or before or {}
        side = with_ if after is not None else base
        rows.append(
            {
                "node_id": node_id,
                "change": change,
                "title": _title(node, side.payload),
                "path": _path(node, side.payload),
                "before": None if before is None else _estimate(before, rb),
                "after": None if after is None else _estimate(after, rw),
                "delta_e": _signed_hours(
                    (_node_e(rw, node_id) if after else ZERO)
                    - (_node_e(rb, node_id) if before else ZERO)
                ),
                "fields": fields,
                "last_changed_by": _author(node, side.payload),
                "last_changed_at": node.get("updated_at"),
            }
        )
    rows.sort(key=lambda r: (r["path"], r["title"], r["node_id"]))
    return rows


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).lower() if isinstance(value, bool) else str(value)


def _param(
    key: str,
    label: str,
    before: Any,
    after: Any,
    *,
    is_money: bool = False,
    discipline_id: str | None = None,
    phase_id: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "discipline_id": discipline_id,
        "phase_id": phase_id,
        "before": _text(before),
        "after": _text(after),
        "is_money": is_money,
        "last_changed_by": None,
        "last_changed_at": None,
    }  # fmt: skip


def _params(base: Side, with_: Side, with_money: bool) -> list[dict[str, Any]]:
    pb, pw = base.payload["project"], with_.payload["project"]
    out: list[dict[str, Any]] = []
    if Decimal(pb["pm_percent"]) != Decimal(pw["pm_percent"]):
        out.append(_param("pm_percent", "% УП", pb["pm_percent"], pw["pm_percent"]))
    if pb["quote_figure"] != pw["quote_figure"]:
        out.append(_param("quote_figure", "Цифра для КП", pb["quote_figure"], pw["quote_figure"]))
    phb = {p["id"]: p for p in base.payload["phases"]}
    phw = {p["id"]: p for p in with_.payload["phases"]}
    for pid in sorted(phb.keys() | phw.keys()):
        b, w = phb.get(pid), phw.get(pid)
        name = (w or b or {}).get("name", "")
        if (b or {}).get("enabled") != (w or {}).get("enabled"):
            out.append(_param("phase_enabled", f"Фаза · {name}", (b or {}).get("enabled"),
                              (w or {}).get("enabled"), phase_id=pid))  # fmt: skip
        if (b or {}).get("in_pm_base") != (w or {}).get("in_pm_base"):
            out.append(_param("pm_base", f"База УП · {name}", (b or {}).get("in_pm_base"),
                              (w or {}).get("in_pm_base"), phase_id=pid))  # fmt: skip
    if not with_money or base.money is None or with_.money is None:
        return out
    mb, mw = base.money, with_.money
    _, disciplines = _names(with_.payload)
    disciplines.update({k: v for k, v in _names(base.payload)[1].items() if k not in disciplines})
    rb, rw = dict(mb["rates"]), dict(mw["rates"])
    for key in sorted(rb.keys() | rw.keys(), key=lambda k: (k == snapshot_money.PM_KEY, k)):
        if rb.get(key) != rw.get(key):
            pm = key == snapshot_money.PM_KEY
            label = "Ставка · УП" if pm else f"Ставка · {disciplines.get(key, key)}"
            out.append(_param("rate", label, rb.get(key), rw.get(key), is_money=True,
                              discipline_id=None if pm else key))  # fmt: skip
    if mb["currency"] != mw["currency"]:
        out.append(_param("currency", "Валюта КП", mb["currency"], mw["currency"], is_money=True))
    if Decimal(mb["exchange_rate"]) != Decimal(mw["exchange_rate"]):
        out.append(_param("exchange_rate", f"Курс {mw['currency']}", mb["exchange_rate"],
                          mw["exchange_rate"], is_money=True))  # fmt: skip
    if mb.get("vat_percent") != mw.get("vat_percent"):
        out.append(_param("vat", "НДС", mb.get("vat_percent"), mw.get("vat_percent"),
                          is_money=True))  # fmt: skip
    return out


def _cost(e: Decimal, rate: Decimal | None) -> Decimal | None:
    return None if rate is None else calc.round_half_up(e * rate, 0)


def _money(
    base: Side, with_: Side, rb: calc.ProjectResult, rw: calc.ProjectResult, rows: list[dict]
) -> dict[str, Any] | None:
    if base.money is None or with_.money is None:
        return None
    sb = snapshot_money.settings_from_payload(base.money)
    sw = snapshot_money.settings_from_payload(with_.money)
    qb = calc.calculate_money(rb, sb).quote
    qw = calc.calculate_money(rw, sw).quote

    def side(q: calc.FigureMoney | None, s: calc.MoneySettings) -> dict[str, Any]:
        return {
            "total_rub": None if q is None else _money_dec(q.total_rub),
            "total_cur": None if q is None else _money_dec(q.total_cur),
            "currency": s.currency,
            "exchange_rate": format_decimal(s.exchange_rate),
        }

    nb = {n["id"]: n for n in base.payload["nodes"]}
    nw = {n["id"]: n for n in with_.payload["nodes"]}
    money_rows: list[dict[str, Any]] = []
    for row in rows:
        nid = row["node_id"]
        before, after = nb.get(nid), nw.get(nid)
        cb = (
            ZERO
            if before is None
            else _cost(_node_e(rb, nid), sb.rates.get(before["discipline_id"]))
        )
        cw = (
            ZERO if after is None else _cost(_node_e(rw, nid), sw.rates.get(after["discipline_id"]))
        )
        delta = None if cb is None or cw is None else cw - cb
        money_rows.append({"node_id": nid, "delta_cost_rub": _money_dec(delta)})
    pm_b, pm_w = _cost(rb.pm.e, sb.rates.get(None)), _cost(rw.pm.e, sw.rates.get(None))
    if pm_b != pm_w:
        delta = None if pm_b is None or pm_w is None else pm_w - pm_b
        money_rows.append({"node_id": None, "delta_cost_rub": _money_dec(delta)})

    rates_changed = dict(sb.rates) != dict(sw.rates)
    rates_effect: Decimal | None = None
    if qw is not None and qw.total_rub is not None:
        with_base_rates = calc.calculate_money(rw, replace(sw, rates=sb.rates)).quote
        if with_base_rates is not None and with_base_rates.total_rub is not None:
            rates_effect = qw.total_rub - with_base_rates.total_rub
    exchange_effect: Decimal | None = None
    if qw is not None and qw.total_rub is not None and qw.total_cur is not None:
        exchange_effect = qw.total_cur - calc.round_half_up(qw.total_rub / sb.exchange_rate, 0)

    def delta(a: Decimal | None, b: Decimal | None) -> str | None:
        return None if a is None or b is None else _money_dec(b - a)

    return {
        "base": side(qb, sb),
        "with": side(qw, sw),
        "rows": money_rows,
        "rates_changed": rates_changed,
        "rates_effect_rub": _money_dec(rates_effect),
        "exchange_effect_cur": _money_dec(exchange_effect),
        "total_delta_rub": delta(qb and qb.total_rub, qw and qw.total_rub),
        "total_delta_cur": delta(qb and qb.total_cur, qw and qw.total_cur),
    }


def _totals(result: calc.ProjectResult) -> dict[str, str]:
    t = result.total
    return {
        "e": _signed_hours(t.e),
        "sigma": _signed_hours(t.sigma),
        "p80": _signed_hours(t.p80),
        "p90": _signed_hours(t.p90),
    }


def compare(base: Side, with_: Side, *, with_money: bool) -> dict[str, Any]:
    """Тело ``Diff`` контракта."""
    rb, rw = recalc(base.payload), recalc(with_.payload)
    rows = _rows(base, with_, rb, rw)
    tb, tw = rb.total, rw.total
    pm = None
    if rb.pm.e != rw.pm.e:
        pm = {
            "percent_before": base.payload["project"]["pm_percent"],
            "percent_after": with_.payload["project"]["pm_percent"],
            "delta_e": _signed_hours(rw.pm.e - rb.pm.e),
        }
    out: dict[str, Any] = {
        "base": {"snapshot_id": base.snapshot_id, "label": base.label, "totals": _totals(rb)},
        "with": {"snapshot_id": with_.snapshot_id, "label": with_.label, "totals": _totals(rw)},
        "rows": rows,
        "params": _params(base, with_, with_money),
        "pm": pm,
        "totals_delta": {
            "e": _signed_hours(tw.e - tb.e),
            "sigma": _signed_hours(tw.sigma - tb.sigma),
            "p80": _signed_hours(tw.p80 - tb.p80),
            "p90": _signed_hours(tw.p90 - tb.p90),
        },
    }
    if with_money:
        money = _money(base, with_, rb, rw, rows)
        if money is not None:
            out["money"] = money
    return out
