/**
 * FE-041 · снимки и динамика итога в демо (FR-SNAP-01, 11.9 №4, GAP-01): одна точка в день
 * (`project_totals_daily`) за последние 8 дней и два снимка «Портала дилеров» на этой кривой.
 * Последняя точка — текущий итог проекта. Цифры условные, форма — как на `stats-totals.png`.
 */
import Decimal from "decimal.js";

import { PERSONAS } from "./personas";
import { type DemoProject, PEOPLE, hours, userRef } from "./data";
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

// --- FE-044: сравнение со снимком ----------------------------------------------------------

type Totals = { e: string; sigma: string; p80: string; p90: string };

const nodeKey = (p: DemoProject, key: string) => uuidFrom("node", p.key, key);

/**
 * Строки сравнения демо: доли общей разницы E по листам «Портала дилеров» (обмен с 1С изменён,
 * тесты обмена добавлены, регресс изменён по ×N); остаток — пересчёт УП. Отрицательную разницу
 * контракт пока не допускает (CR-008), поэтому строки только с ростом.
 */
const DIFF_ROWS: {
  key: string;
  change: "added" | "changed";
  title: string;
  path: string[];
  share: string;
  fields: string[];
  by: "expert" | "orlova";
}[] = [
  {
    key: "n-1c",
    change: "changed",
    title: "Обмен с 1С",
    path: ["Разработка", "Бэкенд"],
    share: "0.55",
    fields: ["o", "r", "p"],
    by: "expert",
  },
  {
    key: "n-1c-tests",
    change: "added",
    title: "Тесты обмена с 1С",
    path: ["Тестирование", "QA"],
    share: "0.3",
    fields: [],
    by: "orlova",
  },
];

/** Итоги стороны сравнения: `current` — текущий проект, иначе снимок. */
function totalsOf(p: DemoProject, side: string): Totals | null {
  if (side === "current") return p.totals.total as unknown as Totals;
  return snapshotsOf(p).find((s) => s.id === side)?.totals ?? null;
}

function quoteOf(p: DemoProject, side: string): string | null {
  if (side === "current") return p.money.figures.p80.total_cur;
  return snapshotsOf(p).find((s) => s.id === side)?.money.quote_cur ?? null;
}

const labelOf = (p: DemoProject, side: string) =>
  side === "current"
    ? "Текущее состояние"
    : (snapshotsOf(p).find((s) => s.id === side)?.name ?? side);

const minus = (a: string, b: string) => {
  const d = new Decimal(a).minus(b);
  return hours((d.isNegative() ? new Decimal(0) : d).toFixed(2));
};

/** `GET /snapshots/{id}/diff?with=`: «было» — снимок `id`, «стало» — `with`. */
export function diffOf(p: DemoProject, id: string, side: string) {
  const base = totalsOf(p, id);
  const next = totalsOf(p, side);
  if (!base || !next) return undefined;
  const delta = {
    e: minus(next.e, base.e),
    sigma: minus(next.sigma, base.sigma),
    p80: minus(next.p80, base.p80),
    p90: minus(next.p90, base.p90),
  };
  const grows = new Decimal(delta.e).greaterThan(0);
  const people = new Map<string, ReturnType<typeof userRef>>([
    ["expert", userRef(PERSONAS.expert)],
    ["orlova", userRef(PEOPLE.orlova)],
  ]);
  const rows = grows
    ? DIFF_ROWS.map((r) => ({
        node_id: nodeKey(p, r.key),
        change: r.change,
        title: r.title,
        path: r.path,
        delta_e: hours(new Decimal(delta.e).times(r.share).toFixed(2)),
        fields: r.fields,
        last_changed_by: people.get(r.by) ?? userRef(PERSONAS.moderator),
      }))
    : [];
  const quoteBase = quoteOf(p, id);
  const quoteNext = quoteOf(p, side);
  const rub = p.money.figures.p80.total_rub;
  const rubDelta = new Decimal(rub)
    .times(new Decimal(delta.p80).div(next.p80 === "0.00" ? 1 : next.p80))
    .round();
  return {
    base: { snapshot_id: id, label: labelOf(p, id) },
    with: {
      snapshot_id: side === "current" ? null : side,
      label: labelOf(p, side),
    },
    rows,
    totals_delta: delta,
    money: {
      rows: rows.map((r) => ({
        node_id: r.node_id,
        delta_cost_rub: rubDelta
          .times(new Decimal(r.delta_e).div(delta.e === "0.00" ? 1 : delta.e))
          .round()
          .toFixed(0),
      })),
      rates_effect_rub: "0",
      exchange_effect_cur:
        side === "current" && quoteBase !== null && quoteNext !== null
          ? new Decimal(quoteBase).times("-0.027").round().toFixed(0)
          : "0",
      total_delta_rub: rubDelta.toFixed(0),
    },
  };
}
