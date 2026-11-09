/**
 * FE-044 · правила сравнения со снимком (SPEC 11.12, FR-SNAP-03/04): какая сторона «было», а какая
 * «стало», числа на фильтрах, итоги сторон по итогу снимка и разнице, остаток разницы — пересчёт УП.
 */
import type { components } from '../../shared/api/client';
import { D } from '../../shared/calc/decimal';

type Diff = components['schemas']['Diff'];
export type DiffRow = Diff['rows'][number];
export type Change = DiffRow['change'];

export const CHANGES: readonly Change[] = ['added', 'removed', 'changed', 'moved'];

/**
 * Стороны из адреса `?a=&b=`: справа («было») — снимок `a`, слева («стало») — снимок `b` или
 * текущее состояние. Без `a` сравнивать не с чем.
 */
export function sidesOf(a: string | null, b: string | null): { left: string; right: string } | null {
  if (!a) return null;
  return { left: b ?? 'current', right: a };
}

/** Адрес экрана сравнения для пары сторон. */
export function compareHref(projectId: string, left: string, right: string): string {
  return `/projects/${projectId}/stats/compare?a=${right}${left === 'current' ? '' : `&b=${left}`}`;
}

/** Для «Сравнить два»: «было» — более ранний снимок. */
export function orderPair<T extends { id: string; created_at: string }>(x: T, y: T): { older: T; newer: T } {
  return x.created_at <= y.created_at ? { older: x, newer: y } : { older: y, newer: x };
}

export function countByChange(rows: readonly DiffRow[]): Map<Change | 'all', number> {
  const out = new Map<Change | 'all', number>([['all', rows.length]]);
  for (const c of CHANGES) out.set(c, rows.filter((r) => r.change === c).length);
  return out;
}

/** «Было → стало» итога: «было» — итог снимка справа, «стало» — он же плюс разница. */
export function beforeAfter(before: string, delta: string): { before: string; after: string; pct: number | null } {
  const b = new D(before);
  const d = new D(delta);
  return {
    before: b.toFixed(),
    after: b.plus(d).toFixed(),
    pct: b.isZero() ? null : Math.round(d.div(b).times(1000).toNumber()) / 10,
  };
}

/** Разница E, не объяснённая строками узлов, — пересчёт УП (11.12: «одной строкой-пояснением»). */
export function pmDelta(diff: Diff): string {
  const rows = diff.rows.reduce((acc, r) => acc.plus(r.delta_e), new D(0));
  return new D(diff.totals_delta.e).minus(rows).toFixed();
}

/** Знак разницы для цвета: рост часов — `bad`, уменьшение — `ok` (как на `compare.png`). */
export function deltaTone(value: string): 'bad' | 'ok' | null {
  const d = new D(value);
  return d.isZero() ? null : d.isNegative() ? 'ok' : 'bad';
}
