/**
 * FE-044 · правила сравнения со снимком (SPEC 11.12, FR-SNAP-03/04, CR-008): какая сторона «было»,
 * а какая «стало», числа на фильтрах (виды изменений узлов и параметры проекта), процент разницы
 * итога, вилка «O–R–P × N» строки.
 */
import type { components } from '../../shared/api/client';
import { D } from '../../shared/calc/decimal';
import { formatFork } from '../../shared/format/number';

type Diff = components['schemas']['Diff'];
export type DiffRow = Diff['rows'][number];
export type Change = DiffRow['change'];

export type DiffParam = components['schemas']['DiffParam'];
export type DiffEstimate = components['schemas']['DiffEstimate'];

export const CHANGES: readonly Change[] = ['added', 'removed', 'changed', 'moved'];
/** Фильтр таблицы: вид изменения узла или «Параметры» (11.12 №3). */
export type Filter = Change | 'params';
export const FILTERS: readonly Filter[] = [...CHANGES, 'params'];

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

/** Числа на фильтрах: строки узлов по видам и строки параметров; «все» — и те, и другие. */
export function countByFilter(rows: readonly DiffRow[], params: readonly DiffParam[]): Map<Filter | 'all', number> {
  const out = new Map<Filter | 'all', number>([['all', rows.length + params.length]]);
  for (const c of CHANGES) out.set(c, rows.filter((r) => r.change === c).length);
  out.set('params', params.length);
  return out;
}

/** Процент разницы от «было» с одним знаком после запятой; null — «было» ноль. */
export function deltaPct(before: string, delta: string): number | null {
  const b = new D(before);
  return b.isZero() ? null : Math.round(new D(delta).div(b).times(1000).toNumber()) / 10;
}

/** Вилка строки «30–40–60» и «× N», если множитель не 1; null — узла на этой стороне нет. */
export function forkOf(e: DiffEstimate | null): string | null {
  if (!e) return null;
  const fork = e.o === null && e.r === null && e.p === null ? e.e : formatFork(e.o, e.r, e.p);
  return e.multiplier === 1 ? fork : `${fork} × ${e.multiplier}`;
}

/** Знак разницы для цвета: рост часов — `bad`, уменьшение — `ok` (как на `compare.png`). */
export function deltaTone(value: string): 'bad' | 'ok' | null {
  const d = new D(value);
  return d.isZero() ? null : d.isNegative() ? 'ok' : 'bad';
}
