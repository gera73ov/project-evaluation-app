/**
 * FE-041 · снимки и динамика итога в демо (FR-SNAP-01, 11.9 №4, GAP-01): одна точка в день
 * (`project_totals_daily`) за последние 8 дней и два снимка «Портала дилеров» на этой кривой.
 * Последняя точка — текущий итог проекта. Цифры условные, форма — как на `stats-totals.png`.
 */
import Decimal from "decimal.js";

import { PERSONAS } from "./personas";
import { type DemoProject, hours, userRef } from "./data";
import { TODAY, uuidFrom } from "./ids";

/** Доля итога на конец каждого дня: оценка растёт быстро, потом выходит на плато. */
const CURVE = ["0.28", "0.52", "0.67", "0.77", "0.86", "0.92", "0.94", "1"];

const dayBefore = (days: number) =>
  new Date(Date.parse(`${TODAY}T12:00:00Z`) - days * 86_400_000)
    .toISOString()
    .slice(0, 10);

const scaled = (value: string, k: string) =>
  hours(new Decimal(value).times(k).times(2).round().div(2).toFixed(1));

export function dynamicsOf(p: DemoProject) {
  const total = p.totals.total;
  return CURVE.map((k, i) => ({
    date: dayBefore(CURVE.length - 1 - i),
    e: scaled(total.e, k),
    p80: scaled(total.p80 ?? total.e, k),
  }));
}

/** Сумма «в КП» в валюте КП на конец каждого дня — та же кривая. */
export function moneyDynamicsOf(p: DemoProject) {
  const quote = p.money.figures.p80.total_cur;
  return CURVE.map((k, i) => ({
    date: dayBefore(CURVE.length - 1 - i),
    quote_cur: quote === null ? null : new Decimal(quote).times(k).toFixed(0),
  }));
}

/** Снимки демо: у «Портала дилеров» — v2, v1 «КП отправлено» и ошибочный v0; у ФНС снимков нет. */
const SNAPS = [
  { key: "v2", name: "v2 — после ответов заказчика", day: 1, curve: 6 },
  { key: "v1", name: "v1 — КП отправлено", day: 2, curve: 5 },
  // ошибочный снимок: в списке зачёркнут, на графике не отмечается
  { key: "v0", name: "v0 — черновик", day: 7, curve: 0 },
];

const DESCRIPTIONS = new Map([
  ["v2", "Учтён REST для 1С"],
  ["v1", "Предварительная цифра"],
  ["v0", "Снят с не той ставкой QA"],
]);

export function snapshotsOf(p: DemoProject) {
  if (p.key !== "portal") return [];
  const total = p.totals.total;
  const quote = p.money.figures.p80.total_cur;
  return SNAPS.map((s) => {
    const k = CURVE[s.curve] ?? "1";
    return {
      id: uuidFrom("snapshot", p.key, s.key),
      name: s.name,
      description: DESCRIPTIONS.get(s.key) ?? "",
      created_by: userRef(PERSONAS.moderator),
      created_at: `${dayBefore(s.day)}T15:00:00Z`,
      is_invalid: s.key === "v0",
      project_version: s.key === "v2" ? 19 : s.key === "v1" ? 17 : 9,
      totals: {
        e: scaled(total.e, k),
        sigma: scaled(total.sigma, k),
        p80: scaled(total.p80 ?? total.e, k),
        p90: scaled(total.p90 ?? total.e, k),
      },
      money: {
        currency: p.money.currency,
        quote_cur:
          quote === null ? null : new Decimal(quote).times(k).toFixed(0),
      },
    };
  });
}
