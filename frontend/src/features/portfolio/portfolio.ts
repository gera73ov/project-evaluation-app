/**
 * FE-050 · правила портфеля руководителя пресейла (SPEC 11.13, FR-PORT-01…03): период по
 * умолчанию, показатели сводки, полосы по месяцам, «договор / в КП» и доступность «Стать модератором».
 */
import type { components } from '../../shared/api/client';
import { D } from '../../shared/calc/decimal';

export type PortfolioItem = components['schemas']['PortfolioItem'];
export type PortfolioSummary = components['schemas']['PortfolioSummary'];

export interface Period {
  from: string;
  to: string;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Период по умолчанию: с 1-го числа месяца четыре месяца назад по сегодня (как на макете: 01.07 – 03.11). */
export function defaultPeriod(today: Date): Period {
  const from = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth() - 4, 1));
  return { from: iso(from), to: iso(today) };
}

const countOf = (map: object, keys: readonly string[]) => {
  const entries = new Map(Object.entries(map as Record<string, number>));
  return keys.reduce((acc, k) => acc + (entries.get(k) ?? 0), 0);
};

export const IN_WORK = ['preparation', 'estimation', 'consolidation'] as const;

export interface Kpis {
  total: number;
  inWork: number;
  completed: number;
  archived: number;
  won: number;
  decided: number;
  cancelled: number;
  unknown: number;
  wonPct: string | null;
  moneyPct: string | null;
  wonRub: string | null;
  decidedRub: string | null;
  /** медиана «договор / в КП» как отношение (0,93), не процент */
  contractRatio: string | null;
  /** насколько обычно уступаем, % (7) */
  discountPct: string | null;
  inWorkRub: string | null;
  firstSnapshotDays: string | null;
}

/** Карточки показателей (11.13 №2) из сводки за период. */
export function kpis(s: PortfolioSummary): Kpis {
  const inWork = countOf(s.by_status, IN_WORK);
  const completed = countOf(s.by_status, ['completed']);
  const archived = countOf(s.by_status, ['archived']);
  const won = countOf(s.by_outcome, ['won']);
  const lost = countOf(s.by_outcome, ['lost']);
  const ratio = s.contract_to_quote_median_pct === null ? null : new D(s.contract_to_quote_median_pct).div(100);
  return {
    total: inWork + completed + archived,
    inWork,
    completed,
    archived,
    won,
    decided: won + lost,
    cancelled: countOf(s.by_outcome, ['cancelled']),
    unknown: countOf(s.by_outcome, ['unknown']),
    wonPct: s.won_share_count_pct,
    moneyPct: s.won_share_money_pct,
    wonRub: s.sum_won_cur,
    decidedRub:
      s.sum_won_cur === null || s.sum_lost_cur === null ? null : new D(s.sum_won_cur).plus(s.sum_lost_cur).toFixed(),
    contractRatio: ratio === null ? null : ratio.toFixed(),
    discountPct: ratio === null ? null : new D(1).minus(ratio).times(100).toFixed(),
    inWorkRub: s.sum_in_progress_cur,
    firstSnapshotDays: s.first_snapshot_median_days,
  };
}

export interface MonthBar {
  month: string;
  won: number;
  lost: number;
  /** без итога: всего за месяц минус выигранные, проигранные и отменённые */
  none: number;
  total: number;
}

/**
 * Полосы «Результаты по месяцам» (11.13 №3). В сводке по месяцам нет числа проектов без итога,
 * поэтому всего за месяц берётся из реестра за тот же период (по дате создания).
 */
export function monthBars(s: PortfolioSummary, items: readonly PortfolioItem[]): MonthBar[] {
  const totals = new Map<string, number>();
  for (const item of items) {
    const month = item.created_at.slice(0, 7);
    totals.set(month, (totals.get(month) ?? 0) + 1);
  }
  const months = new Set([...s.by_month.map((m) => m.month), ...totals.keys()]);
  return [...months].sort().map((month) => {
    const m = s.by_month.find((x) => x.month === month) ?? { won: 0, lost: 0, cancelled: 0 };
    const decided = m.won + m.lost + m.cancelled;
    const total = Math.max(totals.get(month) ?? 0, decided);
    return { month, won: m.won, lost: m.lost, none: total - m.won - m.lost, total };
  });
}

/** «Июль» из `2026-07`. */
export function monthName(month: string): string {
  const [y, m] = month.split('-').map(Number);
  const name = new Intl.DateTimeFormat('ru-RU', { month: 'long', timeZone: 'UTC' }).format(
    new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, 1)),
  );
  return name.charAt(0).toUpperCase() + name.slice(1);
}

export interface ContractRatio {
  id: string;
  name: string;
  ratio: string;
}

/** «Договор к „в КП“» (11.13 №5): выигранные с суммой договора, последние изменённые сверху. */
export function contractRatios(items: readonly PortfolioItem[]): ContractRatio[] {
  return items
    .filter((i) => i.outcome === 'won' && i.money.contract_amount !== null && i.money.quote_cur)
    .filter((i) => !new D(i.money.quote_cur ?? '0').isZero())
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
    .map((i) => ({
      id: i.id,
      name: i.name,
      ratio: new D(i.money.contract_amount ?? '0').div(i.money.quote_cur ?? '1').toFixed(),
    }));
}

/**
 * «Стать модератором проекта» (FR-PORT-03, R-06): нет, если уже модератор; в «Архиве» —
 * неактивна с подсказкой.
 */
export function joinState(item: PortfolioItem, meId: string): 'hidden' | 'archived' | 'available' {
  if (item.moderators.some((m) => m.id === meId)) return 'hidden';
  return item.status === 'archived' ? 'archived' : 'available';
}
