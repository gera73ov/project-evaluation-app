/**
 * FE-041 · правила вкладки «Итоги» (SPEC 11.9 №1–4, 6.3, BR-MONEY-04): строки по фазам и по
 * дисциплинам, доли, ставки и стоимость, шкала и точки графика динамики.
 */
import type { components } from '../../../shared/api/client';
import { D } from '../../../shared/calc/decimal';

type Project = components['schemas']['Project'];
type Stats = components['schemas']['Stats'];
type Hours = components['schemas']['HoursTotals'];

export interface Row {
  id: string;
  name: string;
  hours: Hours | null;
  /** доля, %: у фаз — от итога проекта, у дисциплин — от работ */
  share: string | null;
  cost: string | null;
}

const pct = (part: string, whole: string) =>
  new D(whole).isZero() ? null : new D(part).div(whole).times(100).toFixed();

/** По фазам (11.9 №1): включённые фазы с часами в порядке проекта; доля — от итога. */
export function phaseRows(project: Project, stats: Stats): Row[] {
  const byPhase = new Map(stats.totals.by_phase.map((r) => [r.phase_id, r.hours]));
  const cost = new Map((stats.money?.cost_by_phase ?? []).map((c) => [c.phase_id, c.cost_rub]));
  return project.phases
    .filter((p) => p.is_enabled && byPhase.has(p.phase_id))
    .map((p) => {
      const hours = byPhase.get(p.phase_id) ?? null;
      return {
        id: p.phase_id,
        name: p.name,
        hours,
        share: hours ? pct(hours.e, stats.totals.total.e) : null,
        cost: cost.get(p.phase_id) ?? null,
      };
    });
}

/**
 * По дисциплинам (11.9 №2): все дисциплины проекта, у дисциплины без часов `hours = null`
 * (серая строка); доля — от работ; стоимость при пустой ставке — null («—»).
 */
export function disciplineRows(project: Project, stats: Stats): Row[] {
  const byDisc = new Map(stats.totals.by_discipline.map((r) => [r.discipline_id, r.hours]));
  const cost = new Map((stats.money?.cost_by_discipline ?? []).map((c) => [c.discipline_id, c.cost_rub]));
  return project.disciplines.map((d) => {
    const hours = byDisc.get(d.discipline_id) ?? null;
    const empty = !hours || new D(hours.e).isZero();
    return {
      id: d.discipline_id,
      name: d.name,
      hours: empty ? null : hours,
      share: empty || !hours ? null : pct(hours.e, stats.totals.works.e),
      cost: cost.get(d.discipline_id) ?? null,
    };
  });
}

/** Доля строки в процентах от работ для режима «% работ»: каждая колонка — от своей колонки работ. */
export function shareOf(value: string, works: string): string | null {
  return pct(value, works);
}

/** «Работы» в деньгах — сумма округлённых строк (BR-MONEY-04); нет ни одной суммы — null. */
export function sumCosts(rows: readonly Row[]): string | null {
  const present = rows.filter((r) => r.cost !== null);
  if (present.length === 0) return null;
  return present.reduce((acc, r) => acc.plus(r.cost ?? '0'), new D(0)).toFixed(0);
}

/** Сколько фаз в базе процента УП (6.3): включённые и `in_pm_base`. */
export function pmBasePhases(project: Project): number {
  return project.phases.filter((p) => p.is_enabled && p.in_pm_base).length;
}

/** Верх шкалы и шаг подписей: «круглый» шаг 1/2/2,5/5 × 10^n, 3–4 деления. */
export function niceScale(max: number): { top: number; step: number } {
  if (!(max > 0)) return { top: 1, step: 1 };
  const raw = max / 3;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const step = ([1, 1.5, 2, 2.5, 5, 10].find((m) => m * pow >= raw) ?? 10) * pow;
  return { top: Math.ceil(max / step) * step, step };
}
