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

/** Снимки, сделанные за сессию, и пометки «ошибочный» (FR-SNAP-01/02). */
const created: {
  project: string;
  snapshot: ReturnType<typeof seededSnapshots>[number];
}[] = [];
const invalidated = new Set<string>();
let counter = 0;

export function resetDemoSnapshots(): void {
  created.length = 0;
  invalidated.clear();
  counter = 0;
}

export function snapshotsOf(p: DemoProject) {
  return [
    ...created.filter((c) => c.project === p.key).map((c) => c.snapshot),
    ...seededSnapshots(p),
  ].map((s) => (invalidated.has(s.id) ? { ...s, is_invalid: true } : s));
}

/** `POST /projects/{id}/snapshots`: снимок текущего состояния. */
export function createSnapshot(
  p: DemoProject,
  body: Record<string, unknown>,
  by: ReturnType<typeof userRef>,
) {
  counter += 1;
  const total = p.totals.total;
  const snapshot = {
    id: uuidFrom("snapshot", p.key, "session", String(counter)),
    name: String(body.name ?? ""),
    description: String(body.description ?? ""),
    created_by: by,
    created_at: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    is_invalid: false,
    project_version: 20 + counter,
    totals: {
      e: hours(total.e),
      sigma: hours(total.sigma),
      p80: hours(total.p80 ?? total.e),
      p90: hours(total.p90 ?? total.e),
    },
    money: {
      currency: p.money.currency,
      quote_cur: p.money.figures.p80.total_cur,
    },
  };
  created.unshift({ project: p.key, snapshot });
  return snapshot;
}

/** `POST /snapshots/{id}/invalidate`: снимок остаётся в списке зачёркнутым. */
export function invalidateSnapshot(p: DemoProject, id: string) {
  const snap = snapshotsOf(p).find((s) => s.id === id);
  if (!snap) return undefined;
  invalidated.add(id);
  return { ...snap, is_invalid: true };
}

function seededSnapshots(p: DemoProject) {
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
 * Строки сравнения демо — как на макете `compare.png` (CR-008): обмен с 1С и дашборд изменены,
 * тесты обмена добавлены, прототипы удалены; O–R–P «было → стало», ΔE по листу со знаком.
 * Остаток разницы итога E — пересчёт УП (строка-пояснение `pm`).
 */
type Orp = [string, string, string];
const DIFF_ROWS: {
  key: string;
  change: "added" | "removed" | "changed";
  title: string;
  path: string[];
  before: Orp | null;
  after: Orp | null;
  fields: string[];
  by: keyof typeof PEOPLE | "expert";
  at: string;
}[] = [
  {
    key: "n-1c",
    change: "changed",
    title: "Обмен с 1С",
    path: ["Разработка", "Бэкенд"],
    before: ["30", "40", "60"],
    after: ["40", "60", "100"],
    fields: ["o", "r", "p"],
    by: "expert",
    at: "2026-11-01T11:07:00Z",
  },
  {
    key: "n-1c-tests",
    change: "added",
    title: "Тесты обмена с 1С",
    path: ["Тестирование", "QA"],
    before: null,
    after: ["8", "12", "24"],
    fields: [],
    by: "orlova",
    at: "2026-11-02T09:30:00Z",
  },
  {
    key: "n-dashboard",
    change: "changed",
    title: "Дашборд",
    path: ["Разработка", "Фронтенд"],
    before: ["20", "28", "48"],
    after: ["16", "24", "40"],
    fields: ["o", "r", "p"],
    by: "petrov",
    at: "2026-11-02T12:15:00Z",
  },
  {
    key: "n-prototypes",
    change: "removed",
    title: "Прототипы",
    path: ["Анализ и проектирование", "Аналитика"],
    before: ["4", "6", "10"],
    after: null,
    fields: [],
    by: "kuznetsova",
    at: "2026-11-01T17:40:00Z",
  },
];

/** Оценка листа для строки сравнения: E = (O + 4R + P) / 6 × N. */
function estimate(orp: Orp | null) {
  if (!orp) return null;
  const [o, r, p] = orp;
  const e = new Decimal(o).plus(new Decimal(r).times(4)).plus(p).div(6);
  return { o, r, p, multiplier: 1, e: hours(e.toFixed(2)) };
}

/** Итоги стороны сравнения: `current` — текущий проект, иначе снимок. */
function totalsOf(p: DemoProject, side: string): Totals | null {
  const t =
    side === "current"
      ? (p.totals.total as unknown as Totals)
      : snapshotsOf(p).find((s) => s.id === side)?.totals;
  if (!t) return null;
  // HoursTotals: только E, σ, P80, P90 с двумя знаками
  return {
    e: hours(t.e),
    sigma: hours(t.sigma),
    p80: hours(t.p80),
    p90: hours(t.p90),
  };
}

function quoteOf(p: DemoProject, side: string): string | null {
  if (side === "current") return p.money.figures.p80.total_cur;
  return snapshotsOf(p).find((s) => s.id === side)?.money.quote_cur ?? null;
}

const labelOf = (p: DemoProject, side: string) =>
  side === "current"
    ? "Текущее состояние"
    : (snapshotsOf(p).find((s) => s.id === side)?.name ?? side);

/** Разница со знаком (SignedHoursString). */
const minus = (a: string, b: string) => new Decimal(a).minus(b).toFixed(2);

/** Курс КП в снимках демо — 90 (макет: «курс 90,0 → 92,5»). */
const SNAPSHOT_RATE = "90.0000";

/** Сравнение снимка `id` со стороной `side`; `money` — роль видит деньги (BR-MONEY-01). */
export function diffOf(p: DemoProject, id: string, side: string, money = true) {
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
  const personOf = (key: string) =>
    key === "expert"
      ? userRef(PERSONAS.expert)
      : userRef(PEOPLE[key as keyof typeof PEOPLE]);
  const rows = grows
    ? DIFF_ROWS.map((r) => {
        const before = estimate(r.before);
        const after = estimate(r.after);
        return {
          node_id: nodeKey(p, r.key),
          change: r.change,
          title: r.title,
          path: r.path,
          before,
          after,
          delta_e: minus(after?.e ?? "0", before?.e ?? "0"),
          fields: r.fields,
          last_changed_by: personOf(r.by),
          last_changed_at: r.at,
        };
      })
    : [];
  const rowsE = rows.reduce((acc, r) => acc.plus(r.delta_e), new Decimal(0));
  const pmE = new Decimal(delta.e).minus(rowsE);
  const pct = p.key === "portal" ? "18" : "15";
  const current = side === "current";
  const rateNext = current
    ? new Decimal(p.money.exchangeRate).toFixed(4)
    : SNAPSHOT_RATE;
  const params = current
    ? [
        {
          key: "exchange_rate" as const,
          label: `Курс ${p.money.currency}`,
          discipline_id: null,
          phase_id: null,
          before: SNAPSHOT_RATE,
          after: rateNext,
          is_money: true,
          last_changed_by: userRef(PERSONAS.moderator),
          last_changed_at: "2026-11-02T10:00:00Z",
        },
      ].filter((r) => money || !r.is_money)
    : [];
  // деньги сторон: «стало» — цифра КП, «было» — та же цифра по доле P80 и курсу снимка
  const curNext = quoteOf(p, side);
  const curBase = quoteOf(p, id);
  const rubNext =
    curNext === null
      ? null
      : current
        ? new Decimal(p.money.figures.p80.total_rub)
        : new Decimal(curNext).times(rateNext).round();
  const rubBase =
    curBase === null ? null : new Decimal(curBase).times(SNAPSHOT_RATE).round();
  const rubDelta =
    rubNext !== null && rubBase !== null ? rubNext.minus(rubBase) : null;
  const curDelta =
    curNext !== null && curBase !== null
      ? new Decimal(curNext).minus(curBase).round()
      : null;
  // вклад курса: рублёвая сумма «стало» по курсу «было» и по курсу «стало»
  const exchangeEffect =
    rubNext === null
      ? null
      : rubNext.div(rateNext).minus(rubNext.div(SNAPSHOT_RATE)).round();
  return {
    base: { snapshot_id: id, label: labelOf(p, id), totals: base },
    with: {
      snapshot_id: current ? null : side,
      label: labelOf(p, side),
      totals: next,
    },
    rows,
    params,
    pm: pmE.isZero()
      ? null
      : { percent_before: pct, percent_after: pct, delta_e: pmE.toFixed(2) },
    totals_delta: delta,
    money: {
      base: {
        total_rub: rubBase?.toFixed(0) ?? null,
        total_cur: curBase,
        currency: p.money.currency,
        exchange_rate: SNAPSHOT_RATE,
      },
      with: {
        total_rub: rubNext?.toFixed(0) ?? null,
        total_cur: curNext,
        currency: p.money.currency,
        exchange_rate: rateNext,
      },
      rows: rows.map((r) => ({
        node_id: r.node_id,
        delta_cost_rub:
          rubDelta === null || delta.e === "0.00"
            ? null
            : rubDelta.times(r.delta_e).div(delta.e).round().toFixed(0),
      })),
      rates_changed: false,
      rates_effect_rub: "0",
      exchange_effect_cur: exchangeEffect?.toFixed(0) ?? null,
      total_delta_rub: rubDelta?.toFixed(0) ?? null,
      total_delta_cur: curDelta?.toFixed(0) ?? null,
    },
  };
}
